"""
End-to-end walk through every M1 layer built so far.

Each PR has its own suite proving its own rules. Nothing until now proved they
compose: that a fact captured in PR1 reaches the brain compiled in PR4, and —
the half that actually breaks in practice — that revoking it at the bottom
makes it disappear from the top.

One brand, one narrative:

    PR1  a roasting guideline is uploaded and a fact confirmed from it
    PR2  a competitor post is saved; a human states a type preference, a model
         infers a different one
    PR3  two reviewer rejections become evidence, a colour preference
         establishes, an owner states a hard rule
    PR4  all of it compiles into one deterministic snapshot

then every layer is revoked in turn and the brain is recompiled after each.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common.testing import TenantFixtureMixin
from apps.feedback.models import Feedback
from apps.feedback.services import capture
from apps.inspirations.models import BrandInspiration, InspirationSignal
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import BrandPreference, BrandRule, LearningEvent
from apps.learning.services import (
    create_explicit_rule,
    promote_preference_to_rule,
    reinforce_preference,
)
from apps.workspaces.models import WorkspaceMember

from .models import Brand
from .services.brand_brain import compile_brand_brain, rebuild_brand_brain

User = get_user_model()


class M1PipelineTests(TenantFixtureMixin, TestCase):
    """Layer 1 → 4, then the same journey backwards."""

    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'acme-1')
        self.owner, self.client = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'owner'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', industry='Coffee',
            tagline='Roasted this week', brand_tone='Warm, unfussy',
        )
        # A second brand in the same workspace, present in every assertion
        # below purely to prove nothing leaks sideways.
        self.sibling = Brand.objects.create(workspace=self.workspace, name='Acme Tea')

    # -- layer 1 : knowledge ---------------------------------------------

    def build_knowledge(self):
        source = BrandSource.objects.create(
            workspace=self.workspace, brand=self.brand,
            source_type=BrandSource.SourceType.PDF, title='Roasting guideline',
            status=BrandSource.SourceStatus.READY, created_by=self.owner,
        )
        memory = BrandMemory.objects.create(
            workspace=self.workspace, brand=self.brand, source=source,
            memory_type=BrandMemory.MemoryType.PRODUCT_TRUTH,
            content='Every bag is roasted within 48 hours of shipping',
            normalized_key='roast_freshness',
            status=BrandMemory.MemoryStatus.CONFIRMED,
        )
        return source, memory

    # -- layer 2 : inspirations ------------------------------------------

    def build_inspirations(self, source):
        inspiration = BrandInspiration.objects.create(
            workspace=self.workspace, brand=self.brand, source=source,
            inspiration_type=BrandInspiration.InspirationType.POST,
            title='Competitor launch post',
            annotation='The type, not the photography.',
            reference_url='https://example.com/post',
            usage_scope=BrandInspiration.UsageScope.SPECIFIC_ELEMENTS,
            focus_areas=['TYPOGRAPHY'],
            created_by=self.owner,
        )
        stated = InspirationSignal.objects.create(
            inspiration=inspiration, category='TYPOGRAPHY',
            attribute='headline_face', value='Condensed grotesque',
            sentiment=InspirationSignal.Sentiment.LIKED,
            origin=InspirationSignal.Origin.USER,
            user_confirmation=InspirationSignal.UserConfirmation.CONFIRMED,
            created_by=self.owner,
        )
        return inspiration, stated

    # -- layer 3 : learning ----------------------------------------------

    def build_learning(self):
        """Two reviewer rejections, through the real feedback path."""
        from apps.content.models import ContentItem

        events = []
        for index in range(2):
            item = ContentItem.objects.create(
                workspace=self.workspace, brand=self.brand,
                headline=f'Draft {index}', status=ContentItem.Status.PENDING_REVIEW,
            )
            feedback = capture(
                content_item=item, user=self.owner,
                verdict=Feedback.Verdict.REJECT,
                feedback_text='The accent colour is too cold',
            )
            events.append(LearningEvent.objects.get(source_id=feedback.pk))

        for event in events:
            preference = reinforce_preference(
                workspace=self.workspace, brand=self.brand, event=event,
                category='COLOR', attribute='accent', value='muted earth',
            )
        rule = create_explicit_rule(
            workspace=self.workspace, brand=self.brand,
            text='Never show a competitor logo', hardness=BrandRule.Hardness.HARD,
            priority=10, created_by=self.owner,
            structured={'category': 'BRANDING', 'attribute': 'competitor_logo',
                        'value': 'never'},
        )
        return events, preference, rule

    # -- the walk ---------------------------------------------------------

    def test_every_layer_reaches_the_brain_and_every_revocation_leaves_it(self):
        source, memory = self.build_knowledge()
        inspiration, stated = self.build_inspirations(source)
        events, preference, rule = self.build_learning()

        # An inference that contradicts the stated preference. PR2 holds it,
        # so it must never surface as brand truth in PR4 either.
        contradicting = InspirationSignal.objects.create(
            inspiration=BrandInspiration.objects.create(
                workspace=self.workspace, brand=self.brand, title='Another ref',
                reference_url='https://example.com/other',
            ),
            category='TYPOGRAPHY', attribute='headline_face',
            value='Serif display', sentiment=InspirationSignal.Sentiment.LIKED,
            origin=InspirationSignal.Origin.AI,
        )

        # ---------- layer 4: everything composes ----------
        brain = rebuild_brand_brain(self.brand)
        baseline_version = brain['brain_version']

        self.assertIn(memory.content, brain['verified_product_truth'])
        self.assertEqual([r['text'] for r in brain['hard_rules']],
                         ['Never show a competitor logo'])
        self.assertEqual(brain['unresolved_conflict_count'], 0)

        by_attribute = {c['attribute']: c for c in brain['preferences']}
        self.assertEqual(by_attribute['headline_face']['value'], 'Condensed grotesque')
        self.assertEqual(by_attribute['headline_face']['authority'], 'explicit_preference')
        self.assertEqual(by_attribute['accent']['value'], 'muted earth')
        self.assertEqual(by_attribute['accent']['authority'], 'established_preference')
        self.assertEqual(by_attribute['competitor_logo']['authority'], 'hard_explicit_rule')

        # The contradicting inference never became brand truth. It sits on a
        # DIFFERENT inspiration, so PR2 does not suppress it - its authority
        # rule is per-reference, and each reference may legitimately say
        # something about typography. Resolving across references is exactly
        # what PR4 is for, and precedence does it: the inference is a compiled
        # input, visibly outranked, never the brand's position.
        self.assertNotIn('Serif display', [c['value'] for c in brain['preferences']])
        self.assertIn(str(contradicting.pk), brain['sources']['inspiration_signal_ids'])
        outranked = [o for o in brain['overridden'] if o['value'] == 'Serif display']
        self.assertEqual(len(outranked), 1)
        self.assertEqual(outranked[0]['authority'], 'inspiration_signal')

        # The sibling brand saw none of it.
        self.assertEqual(compile_brand_brain(self.sibling)['verified_product_truth'], [])
        self.assertEqual(compile_brand_brain(self.sibling)['hard_rules'], [])

        # Deterministic, and rebuildable from nothing.
        self.brand.creative_brain = {}
        self.brand.save(update_fields=['creative_brain'])
        self.assertEqual(rebuild_brand_brain(self.brand)['brain_version'], baseline_version)

        # ---------- now revoke each layer in turn ----------

        # PR1: archive the source. The fact goes; the row stays for audit.
        source.status = BrandSource.SourceStatus.ARCHIVED
        source.save(update_fields=['status'])
        brain = rebuild_brand_brain(self.brand)
        self.assertEqual(brain['verified_product_truth'], [])
        self.assertTrue(BrandMemory.objects.filter(pk=memory.pk).exists())
        self.assertNotEqual(brain['brain_version'], baseline_version)

        # PR2: archiving the reference takes ITS signals out of the brain.
        # The other reference is untouched, so what the human's statement was
        # outranking becomes the only claimant - and the brain says plainly
        # that the attribute is now carried by an inference rather than
        # quietly keeping the old answer.
        inspiration.lifecycle_status = BrandInspiration.LifecycleStatus.ARCHIVED
        inspiration.save(update_fields=['lifecycle_status'])
        brain = rebuild_brand_brain(self.brand)
        headline = {c['attribute']: c for c in brain['preferences']}['headline_face']
        self.assertEqual(headline['value'], 'Serif display')
        self.assertEqual(headline['authority'], 'inspiration_signal')
        self.assertNotIn(str(stated.pk), brain['sources']['inspiration_signal_ids'])
        self.assertTrue(InspirationSignal.objects.filter(pk=stated.pk).exists())

        # Archive the second reference too, and the attribute goes entirely.
        contradicting.inspiration.lifecycle_status = (
            BrandInspiration.LifecycleStatus.ARCHIVED
        )
        contradicting.inspiration.save(update_fields=['lifecycle_status'])
        brain = rebuild_brand_brain(self.brand)
        self.assertNotIn('headline_face', [c['attribute'] for c in brain['preferences']])

        # PR3: retire the preference, deactivate the rule.
        preference.state = BrandPreference.State.RETIRED
        preference.save(update_fields=['state'])
        rule.is_active = False
        rule.save(update_fields=['is_active'])
        brain = rebuild_brand_brain(self.brand)
        self.assertEqual(brain['hard_rules'], [])
        self.assertNotIn('accent', [c['attribute'] for c in brain['preferences']])

        # What is left is a valid, empty-of-learning brain — not a broken one.
        self.assertEqual(brain['identity']['name'], 'Acme Coffee')
        self.assertEqual(brain['unresolved_conflict_count'], 0)
        self.assertEqual(brain['schema_version'], 1)

        # And every source record survived the whole journey.
        self.assertEqual(LearningEvent.objects.filter(workspace=self.workspace).count(), 2)
        self.assertTrue(BrandRule.objects.filter(pk=rule.pk).exists())
        self.assertTrue(BrandPreference.objects.filter(pk=preference.pk).exists())

    def test_a_learned_rule_earned_through_the_whole_stack_reaches_the_brain(self):
        """The other direction: evidence accumulating into an instruction."""
        source, _ = self.build_knowledge()
        self.build_inspirations(source)
        events, preference, _ = self.build_learning()

        self.assertEqual(preference.state, BrandPreference.State.ESTABLISHED)
        self.assertEqual(preference.evidence_count, 2)

        learned = promote_preference_to_rule(preference=preference)
        self.assertEqual(learned.origin, BrandRule.Origin.LEARNED)
        # Inferred instructions are never hard, however much evidence backs them.
        self.assertEqual(learned.hardness, BrandRule.Hardness.SOFT)
        self.assertEqual(
            set(learned.evidence_event_ids), {str(e.pk) for e in events}
        )

        brain = rebuild_brand_brain(self.brand)
        self.assertIn(learned.text, [r['text'] for r in brain['soft_rules']])
        self.assertIn(str(learned.pk), brain['sources']['rule_ids'])

    def test_one_rejection_never_reaches_the_brain_as_a_rule(self):
        """The acceptance criterion, end to end: an opinion is not law."""
        from apps.content.models import ContentItem

        item = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand, headline='Draft',
            status=ContentItem.Status.PENDING_REVIEW,
        )
        feedback = capture(
            content_item=item, user=self.owner, verdict=Feedback.Verdict.REJECT,
            feedback_text='Too cold',
        )
        event = LearningEvent.objects.get(source_id=feedback.pk)
        preference = reinforce_preference(
            workspace=self.workspace, brand=self.brand, event=event,
            category='COLOR', attribute='accent', value='muted earth',
        )

        self.assertEqual(preference.state, BrandPreference.State.EMERGING)
        with self.assertRaises(Exception):
            promote_preference_to_rule(preference=preference)

        brain = rebuild_brand_brain(self.brand)
        self.assertEqual(brain['hard_rules'], [])
        self.assertEqual(brain['soft_rules'], [])
        # It is present, but only as the weak signal it is.
        accent = [c for c in brain['preferences'] if c['attribute'] == 'accent']
        self.assertEqual(accent[0]['authority'], 'emerging_preference')
