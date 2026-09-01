"""Phase 6 — feedback capture and the training engine."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.brands.models import Brand
from apps.content.models import ContentItem
from apps.feedback.embeddings import LOCAL_MODEL, cosine, local_embedding
from apps.feedback.models import Feedback, FeedbackElement
from apps.feedback.services import capture
from apps.feedback.training import rules_for_prompt, training_report
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

    def test_first_tagged_rejection_writes_a_soft_cited_rule(self):
        from apps.learning.models import BrandRule, LearningEvent

        feedback = self.reject()
        self.assertEqual(len(feedback.rules_updated), 1)
        self.brand.refresh_from_db()
        rule = BrandRule.objects.get(brand=self.brand)
        self.assertEqual(rule.origin, BrandRule.Origin.LEARNED)
        self.assertEqual(rule.hardness, BrandRule.Hardness.SOFT)
        self.assertEqual(rule.structured['occurrences'], 1)
        self.assertEqual(rule.structured['evidence_count'], 1)
        self.assertEqual(len(rule.evidence_event_ids), 1)
        event = LearningEvent.objects.get(pk=rule.evidence_event_ids[0])
        self.assertEqual(event.brand_id, self.brand.pk)
        self.assertEqual(event.outcome, LearningEvent.Outcome.NEGATIVE)
        self.assertIn('Logo placement', rules_for_prompt(self.brand)[0])

    def test_second_rejection_for_the_same_reason_strengthens_the_rule(self):
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
        from apps.feedback.training import learned_rules

        rule = learned_rules(self.brand)[0]
        self.assertEqual(rule.structured['occurrences'], 2)
        self.assertEqual(len(rule.evidence_event_ids), 2)

    def test_repeat_sharpens_rather_than_duplicates(self):
        from apps.feedback.training import learned_rules

        for _ in range(3):
            self.reject()
        self.brand.refresh_from_db()
        rules = learned_rules(self.brand)
        self.assertEqual(len(rules), 1)
        self.assertGreaterEqual(rules[0].structured['occurrences'], 3)

    def test_replaying_the_same_training_pass_does_not_double_count(self):
        from apps.feedback.training import TrainingEngine, learned_rules

        feedback = self.reject()
        TrainingEngine(feedback).learn()

        rules = learned_rules(self.brand)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].structured['evidence_count'], 1)
        self.assertEqual(len(rules[0].evidence_event_ids), 1)

    def test_replaying_an_older_review_does_not_overwrite_newer_guidance(self):
        from apps.feedback.training import TrainingEngine, learned_rules

        older = self.reject(fix='keep the logo in the top left')
        self.reject(fix='move the logo below the product image')
        current = learned_rules(self.brand)[0]
        self.assertIn('move the logo below the product image', current.text)

        TrainingEngine(older).learn()

        current.refresh_from_db()
        self.assertIn('move the logo below the product image', current.text)
        self.assertEqual(current.structured['occurrences'], 2)
        self.assertEqual(len(current.evidence_event_ids), 2)

    def test_a_learned_rule_is_soft_and_cites_its_evidence(self):
        """PR3's authority model: an inference never becomes a constraint, and
        it must be able to name the reviews it came from."""
        from apps.learning.models import BrandRule, LearningEvent

        self.reject()

        rule = BrandRule.objects.get(brand=self.brand)
        self.assertEqual(rule.origin, BrandRule.Origin.LEARNED)
        self.assertEqual(rule.hardness, BrandRule.Hardness.SOFT)
        self.assertEqual(len(rule.evidence_event_ids), 1)
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

        context = build_generation_context(self.ws, self.brand)
        soft = ' '.join(rule['text'] for rule in context['soft_rules'])
        self.assertIn('Logo placement', soft)

    def test_brain_compile_failure_is_exposed_as_not_current(self):
        with patch(
            'apps.brands.services.brand_brain.rebuild_brand_brain_safely',
            return_value=None,
        ):
            feedback = self.reject()

        feedback.refresh_from_db()
        self.assertFalse(feedback.pattern_extracted['brain_rebuilt'])

    def test_a_different_complaint_creates_an_independent_rule(self):
        from apps.feedback.training import learned_rules

        self.reject()
        second = self.reject(
            text='headline is far too small to read',
            elements=('font_size',),
            fix='raise the headline size',
        )
        self.assertEqual(len(second.rules_updated), 1)
        rules = learned_rules(self.brand)
        self.assertEqual(len(rules), 2)
        self.assertEqual(
            {rule.structured['element'] for rule in rules},
            {'logo_placement', 'font_size'},
        )
        self.assertTrue(all(rule.structured['occurrences'] == 1 for rule in rules))

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

    def test_untagged_repeat_wording_is_evidence_but_not_an_actionable_rule(self):
        note = 'the logo sits right over the product and hides it'
        capture(
            content_item=self.item(), user=self.manager,
            verdict=Feedback.Verdict.REJECT, feedback_text=note,
        )
        second = capture(
            content_item=self.item(), user=self.manager,
            verdict=Feedback.Verdict.REJECT, feedback_text=note,
        )
        self.assertEqual(second.pattern_extracted['occurrences'], 2)
        self.assertGreaterEqual(
            second.pattern_extracted['similar_feedback'][0]['similarity'], 0.55
        )
        self.assertEqual(rules_for_prompt(self.brand), [])

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
        # Each brand learns its own first correction; neither reinforces the other.
        self.assertEqual(len(feedback.rules_updated), 1)
        from apps.feedback.training import learned_rules

        alpha = learned_rules(self.brand)
        beta = learned_rules(foreign_brand)
        self.assertEqual(len(alpha), 1)
        self.assertEqual(len(beta), 1)
        self.assertEqual(alpha[0].structured['occurrences'], 1)
        self.assertEqual(beta[0].structured['occurrences'], 1)
        self.assertTrue(set(alpha[0].evidence_event_ids).isdisjoint(beta[0].evidence_event_ids))

    def test_immediate_rule_proves_the_event_against_its_feedback_source(self):
        from apps.learning.adapters import record_feedback_event
        from apps.learning.models import LearningEvent
        from apps.learning.services import LearningError, upsert_review_rule

        feedback = Feedback.objects.create(
            workspace=self.ws,
            brand=self.brand,
            content_item=self.item(),
            user=self.manager,
            verdict=Feedback.Verdict.REJECT,
            element_keys=['logo_placement'],
            feedback_text='The logo obscures the product.',
        )
        event = record_feedback_event(feedback)
        LearningEvent.objects.filter(pk=event.pk).update(created_by=self.outsider)
        event.refresh_from_db()

        with self.assertRaises(LearningError):
            upsert_review_rule(
                workspace=self.ws,
                brand=self.brand,
                key='review:logo_placement',
                text='Keep the logo clear of the product.',
                evidence_events=[event],
                structured={
                    'source': 'review_feedback',
                    'element': 'logo_placement',
                },
            )

    def test_embedding_falls_back_to_local_when_nothing_is_routed(self):
        feedback = self.reject()
        self.assertEqual(feedback.embedding_model, LOCAL_MODEL)
        self.assertTrue(feedback.embedding)

    def test_sentiment_is_inferred(self):
        self.assertEqual(self.reject().sentiment, Feedback.Sentiment.NEGATIVE)


class ReviewIntegrationTests(Base):
    def test_first_tagged_rejection_changes_the_next_prompt(self):
        """The Phase 6 acceptance criterion, end to end through the API."""
        self.as_(self.manager)
        payload = {
            'note': 'logo sits over the product',
            'elements': ['logo_placement'],
            'fix_request': 'keep the logo in the top left',
        }
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

    def test_first_tagged_request_edits_also_learns(self):
        self.as_(self.manager)
        item = self.item()
        res = self.client.post(
            f'/api/marketing/content/{item.id}/request-edits/',
            {
                'note': 'headline is difficult to read',
                'elements': ['font_size'],
                'fix_request': 'increase the headline size',
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('Font size', rules_for_prompt(self.brand)[0])

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
            {
                'content_item': str(foreign.id),
                'verdict': 'REJECT',
                'element_keys': ['logo_placement'],
                'feedback_text': 'Keep the logo clear of the product.',
            },
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

    def test_direct_corrective_feedback_requires_a_tag_and_guidance(self):
        self.as_(self.manager)
        endpoint = '/api/marketing/feedback/'
        content_id = str(self.item().id)

        without_tag = self.client.post(
            endpoint,
            {
                'content_item': content_id,
                'verdict': 'REJECT',
                'feedback_text': 'The logo covers the product.',
            },
            format='json',
        )
        without_guidance = self.client.post(
            endpoint,
            {
                'content_item': content_id,
                'verdict': 'NEEDS_EDITS',
                'element_keys': ['logo_placement'],
            },
            format='json',
        )

        self.assertEqual(without_tag.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(without_guidance.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Feedback.objects.exists())

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
        self.assertTrue(res.data['data']['provisional'])

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
        self.assertTrue(data['brain_current'])
        self.assertEqual(len(data['rules']), 1)
        self.assertEqual(data['rules'][0]['occurrences'], 1)
        self.assertEqual(len(data['rules'][0]['evidence_event_ids']), 1)

    def test_report_is_scoped_to_the_callers_workspace(self):
        capture(
            content_item=self.item(), user=self.manager,
            verdict=Feedback.Verdict.REJECT, feedback_text='mine',
        )
        self.as_(self.outsider, self.other)
        res = self.client.get('/api/marketing/feedback/training-report/')
        self.assertEqual(res.data['data']['total_feedback'], 0)


class VocabularySeedTests(APITestCase):
    def test_seed_matches_the_documented_group_counts(self):
        expected = {
            'TYPOGRAPHY': 8, 'COPY': 10, 'LINE_BY_LINE': 10, 'LOGO': 6,
            'VISUAL': 6, 'LAYOUT': 5, 'AUDIO': 3, 'FORMAT': 4, 'STRATEGY': 4,
        }
        for group, count in expected.items():
            self.assertEqual(
                FeedbackElement.objects.filter(group=group).count(), count, group
            )
        self.assertEqual(FeedbackElement.objects.count(), sum(expected.values()))

    def test_seeded_rows_are_flagged_provisional(self):
        self.assertFalse(FeedbackElement.objects.filter(is_provisional=False).exists())
