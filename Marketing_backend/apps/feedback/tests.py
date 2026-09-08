"""Phase 6 — feedback capture and the training engine."""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.brands.models import Brand
from apps.content.models import ContentItem
from apps.feedback.embeddings import LOCAL_MODEL, cosine, local_embedding
from apps.feedback.models import Feedback, FeedbackElement
from apps.feedback.services import capture
from apps.feedback.training import MIN_OCCURRENCES, rules_for_prompt, training_report
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()


class Base(APITestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.other = MarketingWorkspace.objects.create(customer_id='b', workspace_name='Beta')

        self.manager = User.objects.create_user(username='mgr', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.manager, role=WorkspaceMember.Role.MANAGER
        )
        self.editor = User.objects.create_user(username='ed', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.editor, role=WorkspaceMember.Role.EDITOR
        )
        self.outsider = User.objects.create_user(username='out', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.other, user=self.outsider, role=WorkspaceMember.Role.OWNER
        )

        self.brand = Brand.objects.create(workspace=self.ws, name='Alpha Co', is_default=True)
        # The vocabulary arrives from the seed migration; these two are the
        # ones the tests tag with.
        self.element = FeedbackElement.objects.get(key='logo_placement')
        FeedbackElement.objects.get(key='font_size')

    def item(self, workspace=None, **kwargs):
        return ContentItem.objects.create(
            workspace=workspace or self.ws,
            brand=self.brand if (workspace or self.ws) == self.ws else None,
            **{
                'headline': 'Festive drop',
                'status': ContentItem.Status.PENDING_REVIEW,
                **kwargs,
            },
        )

    def as_(self, user, ws=None):
        self.client.force_authenticate(user=user)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str((ws or self.ws).id))


class EmbeddingTests(Base):
    def test_same_text_embeds_identically(self):
        a = local_embedding('the logo is in the wrong corner')
        b = local_embedding('the logo is in the wrong corner')
        self.assertEqual(a, b)
        self.assertAlmostEqual(cosine(a, b), 1.0, places=6)

    def test_unrelated_text_is_not_similar(self):
        a = local_embedding('the logo is in the wrong corner')
        b = local_embedding('shipping times need updating in the caption')
        self.assertLess(cosine(a, b), 0.5)

    def test_mismatched_lengths_do_not_raise(self):
        # A workspace can hold vectors from two models if the provider was
        # switched; those simply do not compare.
        self.assertEqual(cosine([1.0, 0.0], [1.0, 0.0, 0.0]), 0.0)
        self.assertEqual(cosine([], [1.0]), 0.0)


class TrainingEngineTests(Base):
    def reject(self, text='logo sits over the product', elements=('logo_placement',),
               fix='keep the logo in the top left'):
        return capture(
            content_item=self.item(),
            user=self.manager,
            verdict=Feedback.Verdict.REJECT,
            element_keys=list(elements),
            feedback_text=text,
            fix_request=fix,
        )

    def test_first_rejection_learns_nothing(self):
        feedback = self.reject()
        self.assertEqual(feedback.rules_updated, [])
        self.brand.refresh_from_db()
        self.assertEqual(rules_for_prompt(self.brand), [])

    def test_second_rejection_for_the_same_reason_writes_a_rule(self):
        self.reject()
        second = self.reject()

        self.assertTrue(second.pattern_extracted['is_pattern'])
        self.assertIn('logo_placement', second.pattern_extracted['recurring_elements'])
        self.assertEqual(len(second.rules_updated), 1)

        self.brand.refresh_from_db()
        rules = rules_for_prompt(self.brand)
        self.assertEqual(len(rules), 1)
        self.assertIn('Logo placement', rules[0])
        self.assertIn('keep the logo in the top left', rules[0])

    def test_repeat_sharpens_rather_than_duplicates(self):
        from apps.feedback.training import learned_rules

        for _ in range(3):
            self.reject()
        self.brand.refresh_from_db()
        rules = learned_rules(self.brand)
        self.assertEqual(len(rules), 1)
        self.assertGreaterEqual(rules[0].structured['occurrences'], 3)

    def test_a_learned_rule_is_soft_and_cites_its_evidence(self):
        """PR3's authority model: an inference never becomes a constraint, and
        it must be able to name the reviews it came from."""
        from apps.learning.models import BrandRule, LearningEvent

        self.reject()
        self.reject()

        rule = BrandRule.objects.get(brand=self.brand)
        self.assertEqual(rule.origin, BrandRule.Origin.LEARNED)
        self.assertEqual(rule.hardness, BrandRule.Hardness.SOFT)
        self.assertGreaterEqual(
            len(rule.evidence_event_ids), BrandRule.MIN_EVIDENCE_FOR_LEARNED_RULE
        )
        # Every cited id is a real event for this brand, not a number.
        events = LearningEvent.objects.filter(pk__in=rule.evidence_event_ids)
        self.assertEqual(events.count(), len(rule.evidence_event_ids))
        for event in events:
            self.assertEqual(event.brand_id, self.brand.pk)

    def test_a_learned_rule_survives_a_brand_brain_rebuild(self):
        """The defect this replaced: the rule lived in the compiled snapshot,
        so the next compile deleted it."""
        from apps.brands.services.brand_brain import rebuild_brand_brain
        from apps.feedback.training import rules_for_prompt

        self.reject()
        self.reject()
        self.assertEqual(len(rules_for_prompt(self.brand)), 1)

        rebuild_brand_brain(self.brand)
        self.brand.refresh_from_db()

        self.assertEqual(len(rules_for_prompt(self.brand)), 1)
        # And the compiler carries it into the snapshot generation reads.
        texts = [rule['text'] for rule in self.brand.creative_brain['soft_rules']]
        self.assertTrue(any('Logo placement' in text for text in texts), texts)
        self.assertEqual(self.brand.creative_brain['hard_rules'], [])

    def test_review_learning_reaches_the_generation_context(self):
        """Teach -> review -> learn -> the next generation is told."""
        from apps.context.services.context_gateway import build_generation_context

        self.reject()
        self.reject()

        context = build_generation_context(self.ws, self.brand)
        soft = ' '.join(rule['text'] for rule in context['soft_rules'])
        self.assertIn('Logo placement', soft)

    def test_a_different_complaint_does_not_reinforce(self):
        self.reject()
        second = self.reject(
            text='headline is far too small to read',
            elements=('font_size',),
            fix='raise the headline size',
        )
        self.assertEqual(second.rules_updated, [])

    def test_approvals_never_become_rules(self):
        for _ in range(3):
            capture(
                content_item=self.item(),
                user=self.manager,
                verdict=Feedback.Verdict.APPROVE,
                element_keys=['logo_placement'],
                feedback_text='logo placement is perfect',
            )
        self.brand.refresh_from_db()
        self.assertEqual(rules_for_prompt(self.brand), [])

    def test_untagged_repeat_wording_still_counts_as_similar(self):
        note = 'the logo sits right over the product and hides it'
        capture(
            content_item=self.item(), user=self.manager,
            verdict=Feedback.Verdict.REJECT, feedback_text=note,
        )
        second = capture(
            content_item=self.item(), user=self.manager,
            verdict=Feedback.Verdict.REJECT, feedback_text=note,
        )
        self.assertEqual(second.pattern_extracted['occurrences'], MIN_OCCURRENCES)
        self.assertGreaterEqual(
            second.pattern_extracted['similar_feedback'][0]['similarity'], 0.55
        )

    def test_learning_stays_inside_the_workspace(self):
        self.reject()
        foreign_brand = Brand.objects.create(workspace=self.other, name='Beta Co')
        foreign_item = ContentItem.objects.create(
            workspace=self.other, brand=foreign_brand, headline='Theirs'
        )
        feedback = capture(
            content_item=foreign_item, user=self.outsider,
            verdict=Feedback.Verdict.REJECT,
            element_keys=['logo_placement'],
            feedback_text='logo sits over the product',
        )
        # Alpha's identical complaint must not count towards Beta's pattern.
        self.assertEqual(feedback.rules_updated, [])

    def test_embedding_falls_back_to_local_when_nothing_is_routed(self):
        feedback = self.reject()
        self.assertEqual(feedback.embedding_model, LOCAL_MODEL)
        self.assertTrue(feedback.embedding)

    def test_sentiment_is_inferred(self):
        self.assertEqual(self.reject().sentiment, Feedback.Sentiment.NEGATIVE)


class ReviewIntegrationTests(Base):
    def test_rejecting_twice_changes_the_next_prompt(self):
        """The Phase 6 acceptance criterion, end to end through the API."""
        self.as_(self.manager)
        payload = {
            'note': 'logo sits over the product',
            'elements': ['logo_placement'],
            'fix_request': 'keep the logo in the top left',
        }
        for _ in range(2):
            res = self.client.post(
                f'/api/marketing/content/{self.item().id}/reject/', payload, format='json'
            )
            self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.brand.refresh_from_db()
        rules = rules_for_prompt(self.brand)
        self.assertEqual(len(rules), 1)

        from apps.gemini.services.generator import GeminiGeneratorService

        block = GeminiGeneratorService._rules_block(rules)
        self.assertIn('LEARNED BRAND RULES', block)
        self.assertIn('Logo placement', block)
        # And nothing is added before anything has been learned.
        self.assertEqual(GeminiGeneratorService._rules_block([]), '')

    def test_approve_records_feedback(self):
        self.as_(self.manager)
        item = self.item()
        self.client.post(f'/api/marketing/content/{item.id}/approve/', {}, format='json')
        self.assertEqual(
            Feedback.objects.filter(
                content_item=item, verdict=Feedback.Verdict.APPROVE
            ).count(),
            1,
        )

    def test_submit_is_not_a_verdict(self):
        self.as_(self.editor)
        item = self.item(status=ContentItem.Status.DRAFT)
        self.client.post(f'/api/marketing/content/{item.id}/submit/', {}, format='json')
        self.assertFalse(Feedback.objects.filter(content_item=item).exists())

    def test_unknown_element_is_rejected(self):
        self.as_(self.manager)
        res = self.client.post(
            f'/api/marketing/content/{self.item().id}/reject/',
            {'elements': ['not_a_real_element']},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Feedback.objects.exists())


class FeedbackAPITests(Base):
    def test_anonymous_rejected(self):
        self.client.credentials()
        self.assertEqual(
            self.client.get('/api/marketing/feedback/').status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_list_is_workspace_scoped(self):
        capture(
            content_item=self.item(), user=self.manager,
            verdict=Feedback.Verdict.REJECT, feedback_text='mine',
        )
        foreign = ContentItem.objects.create(workspace=self.other, headline='Theirs')
        capture(
            content_item=foreign, user=self.outsider,
            verdict=Feedback.Verdict.REJECT, feedback_text='theirs',
        )

        self.as_(self.manager)
        res = self.client.get('/api/marketing/feedback/')
        self.assertEqual([f['feedback_text'] for f in res.data], ['mine'])

    def test_cannot_attach_feedback_to_another_tenants_content(self):
        foreign = ContentItem.objects.create(workspace=self.other, headline='Theirs')
        self.as_(self.manager)
        res = self.client.post(
            '/api/marketing/feedback/',
            {'content_item': str(foreign.id), 'verdict': 'REJECT'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Feedback.objects.exists())

    def test_embedding_is_never_serialised(self):
        self.as_(self.manager)
        res = self.client.post(
            '/api/marketing/feedback/',
            {
                'content_item': str(self.item().id),
                'verdict': 'REJECT',
                'element_keys': ['logo_placement'],
                'feedback_text': 'logo sits over the product',
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('embedding', res.data['data'])

    def test_elements_endpoint_returns_the_vocabulary_grouped(self):
        self.as_(self.editor)
        res = self.client.get('/api/marketing/feedback/elements/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        groups = {g['group'] for g in res.data['data']['groups']}
        self.assertIn(FeedbackElement.Group.LOGO, groups)
        self.assertEqual(
            res.data['data']['count'],
            FeedbackElement.objects.filter(is_active=True).count(),
        )
        # Migration 0003 promoted the vocabulary: nothing active is a stand-in.
        self.assertFalse(res.data['data']['provisional'])

    def test_training_report(self):
        capture(
            content_item=self.item(), user=self.manager,
            verdict=Feedback.Verdict.REJECT, element_keys=['logo_placement'],
            feedback_text='logo sits over the product',
        )
        self.as_(self.manager)
        res = self.client.get('/api/marketing/feedback/training-report/')
        data = res.data['data']
        self.assertEqual(data['total_feedback'], 1)
        self.assertEqual(data['by_verdict']['REJECT'], 1)
        self.assertEqual(data['top_elements'][0]['label'], 'Logo placement')

    def test_report_is_scoped_to_the_callers_workspace(self):
        capture(
            content_item=self.item(), user=self.manager,
            verdict=Feedback.Verdict.REJECT, feedback_text='mine',
        )
        self.as_(self.outsider, self.other)
        res = self.client.get('/api/marketing/feedback/training-report/')
        self.assertEqual(res.data['data']['total_feedback'], 0)


class VocabularySeedTests(APITestCase):
    """The promoted production vocabulary (migrations 0002 + 0003)."""

    ACTIVE_COUNTS = {
        'TYPOGRAPHY': 8, 'COPY': 10, 'LINE_BY_LINE': 10, 'LOGO': 6,
        'VISUAL': 6, 'LAYOUT': 5, 'AUDIO': 3, 'FORMAT': 4, 'STRATEGY': 4,
    }

    def test_active_vocabulary_matches_the_production_group_counts(self):
        for group, count in self.ACTIVE_COUNTS.items():
            self.assertEqual(
                FeedbackElement.objects.filter(group=group, is_active=True).count(),
                count,
                group,
            )
        self.assertEqual(
            FeedbackElement.objects.filter(is_active=True).count(),
            sum(self.ACTIVE_COUNTS.values()),
        )

    def test_active_vocabulary_is_fully_promoted(self):
        self.assertFalse(
            FeedbackElement.objects.filter(
                is_active=True, is_provisional=True
            ).exists()
        )

    def test_production_element_names_are_the_active_labels(self):
        # The labels a reviewer sees in the console, verbatim.
        self.assertTrue(
            FeedbackElement.objects.filter(
                key='repetitive_scene', label='Repetitive scene', is_active=True
            ).exists()
        )
        self.assertTrue(
            FeedbackElement.objects.filter(
                key='looks_ai_fake', label='Looks AI / fake', is_active=True
            ).exists()
        )

    def test_key_continuity_for_rows_learned_against_the_placeholders(self):
        # Rules and feedback recorded before promotion keyed on these rows;
        # the keys must survive with their identity intact.
        for key in ('logo_placement', 'font_size', 'tone_of_voice', 'audience_fit'):
            self.assertTrue(
                FeedbackElement.objects.filter(
                    key=key, is_active=True, is_provisional=False
                ).exists(),
                key,
            )

    def test_retired_placeholders_are_deactivated_not_deleted(self):
        # A fresh database has no placeholders to retire, so stage one: a row
        # left over from the pre-handover provisional seed.
        import importlib.util
        from pathlib import Path

        from django.apps import apps as django_apps

        migration_path = (
            Path(__file__).parent / 'migrations' / '0003_production_vocabulary.py'
        )
        spec = importlib.util.spec_from_file_location(
            'feedback_0003', migration_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        stale = FeedbackElement.objects.create(
            key='legacy_placeholder', label='Legacy placeholder',
            group=FeedbackElement.Group.VISUAL, is_provisional=True,
        )
        module.promote(django_apps, None)
        stale.refresh_from_db()
        self.assertFalse(stale.is_active)
        self.assertTrue(FeedbackElement.objects.filter(pk=stale.pk).exists())

        module.demote(django_apps, None)
        stale.refresh_from_db()
        self.assertTrue(stale.is_active)
