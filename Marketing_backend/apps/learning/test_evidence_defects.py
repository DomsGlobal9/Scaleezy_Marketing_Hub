"""
Three ways a person's judgment was being thrown away.

Each of these is a case where somebody told the system something and the
system either lost it or overruled them. They are regressions, not features:
every test here fails against the code as it stood before.

* Retiring a preference used to black-hole the attribute forever — the lookup
  found the retired row and refused, so no later evidence about that
  attribute could ever be recorded again.
* Switching off a learned rule used to be undone by the next matching review,
  because the lookup only saw active rules and simply created a new one.
* In a workspace with two brands, one brand's reviews were pulled into the
  other's evidence, where the same-brand check then rejected the whole batch.
"""
from django.test import TestCase

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.content.models import ContentItem
from apps.learning.models import (
    BrandPreference,
    BrandRule,
    LearningEvent,
    LearningScope,
    PreferenceEvidence,
)
from apps.learning.services import (
    LearningError,
    deactivate_rule,
    record_event,
    reinforce_preference,
    upsert_learned_rule,
)
from apps.workspaces.models import WorkspaceMember


class EvidenceDefectTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.user, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'owner@acme.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', is_default=True,
            status=Brand.Status.ACTIVE,
        )

    def an_event(self, note='x'):
        return record_event(
            workspace=self.workspace,
            brand=self.brand,
            event_type=LearningEvent.EventType.REJECTED,
            outcome=LearningEvent.Outcome.NEGATIVE,
            context={'note': note},
        )

    # ───────────────────────────── a retired preference is not a black hole

    def test_retiring_a_preference_does_not_discard_every_later_judgment(self):
        first = reinforce_preference(
            workspace=self.workspace, brand=self.brand,
            category='COPY_STYLE', attribute='length', value='short',
            event=self.an_event('one'), scope=LearningScope.BRAND,
        )
        first.state = BrandPreference.State.RETIRED
        first.save(update_fields=['state'])

        # The judgment that follows must land somewhere. Before the fix the
        # lookup found the retired row and raised, so this evidence — and all
        # evidence about this attribute, forever — was simply lost.
        second = reinforce_preference(
            workspace=self.workspace, brand=self.brand,
            category='COPY_STYLE', attribute='length', value='long',
            event=self.an_event('two'), scope=LearningScope.BRAND,
        )
        self.assertNotEqual(second.pk, first.pk, 'a new record, not a revival')
        self.assertEqual(second.value, 'long')
        self.assertNotEqual(second.state, BrandPreference.State.RETIRED)

        # The retired row is untouched: retiring still means retired.
        first.refresh_from_db()
        self.assertEqual(first.state, BrandPreference.State.RETIRED)
        self.assertEqual(
            PreferenceEvidence.objects.filter(preference=first).count(), 1,
            'the retired row keeps its own history and gains nothing new',
        )

        # And the successor accumulates normally, so it can still establish.
        reinforce_preference(
            workspace=self.workspace, brand=self.brand,
            category='COPY_STYLE', attribute='length', value='long',
            event=self.an_event('three'), scope=LearningScope.BRAND,
        )
        second.refresh_from_db()
        self.assertEqual(second.state, BrandPreference.State.ESTABLISHED)

    # ──────────────────────── a rule a person switched off stays switched off

    def test_a_deactivated_learned_rule_is_not_silently_re_created(self):
        events = [self.an_event('a'), self.an_event('b')]
        rule = upsert_learned_rule(
            workspace=self.workspace, brand=self.brand, key='headline:length',
            text='Keep headlines under nine words.', evidence_events=events,
            structured={'category': 'COPY_STYLE', 'attribute': 'length'},
        )
        self.assertTrue(rule.is_active)

        deactivate_rule(rule=rule, user=self.user)
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)

        # The same pattern recurs. Before the fix this created a SECOND rule
        # under a new id and the person's decision was reverted with no trace.
        with self.assertRaises(LearningError) as refused:
            upsert_learned_rule(
                workspace=self.workspace, brand=self.brand, key='headline:length',
                text='Keep headlines under nine words.',
                evidence_events=[self.an_event('c'), self.an_event('d')],
                structured={'category': 'COPY_STYLE', 'attribute': 'length'},
            )
        self.assertIn('switched off', str(refused.exception))
        self.assertEqual(
            BrandRule.objects.filter(brand=self.brand, is_active=True).count(), 0
        )
        self.assertEqual(BrandRule.objects.filter(brand=self.brand).count(), 1)

        # A different pattern is unaffected — the refusal is per key, not a
        # blanket stop on learning.
        other = upsert_learned_rule(
            workspace=self.workspace, brand=self.brand, key='cta:tone',
            text='Keep the call to action warm.',
            evidence_events=[self.an_event('e'), self.an_event('f')],
            structured={'category': 'CTA', 'attribute': 'tone'},
        )
        self.assertTrue(other.is_active)

    def test_an_active_learned_rule_still_sharpens_in_place(self):
        """The fix must not break the ordinary path it sits in front of."""
        rule = upsert_learned_rule(
            workspace=self.workspace, brand=self.brand, key='headline:length',
            text='Keep headlines short.',
            evidence_events=[self.an_event('a'), self.an_event('b')],
            structured={'category': 'COPY_STYLE', 'attribute': 'length'},
        )
        again = upsert_learned_rule(
            workspace=self.workspace, brand=self.brand, key='headline:length',
            text='Keep headlines under nine words.',
            evidence_events=[self.an_event('c'), self.an_event('d')],
            structured={'category': 'COPY_STYLE', 'attribute': 'length'},
        )
        self.assertEqual(again.pk, rule.pk, 'sharpened in place, not duplicated')
        self.assertEqual(again.text, 'Keep headlines under nine words.')
        self.assertEqual(BrandRule.objects.filter(brand=self.brand).count(), 1)
        # Still LEARNED and still SOFT: seeing it again never promotes it.
        self.assertEqual(again.origin, BrandRule.Origin.LEARNED)
        self.assertEqual(again.hardness, BrandRule.Hardness.SOFT)


class SiblingBrandEvidenceTests(TenantFixtureMixin, TestCase):
    """One brand's reviews must not decide another brand's rules."""

    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.user, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.MANAGER, 'owner@acme.test'
        )
        self.coffee = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', is_default=True,
            status=Brand.Status.ACTIVE,
        )
        self.tea = Brand.objects.create(
            workspace=self.workspace, name='Acme Tea', status=Brand.Status.ACTIVE,
        )

    def test_similar_feedback_never_crosses_a_brand_boundary(self):
        from apps.feedback.models import Feedback
        from apps.feedback.training import TrainingEngine

        def a_feedback(brand):
            item = ContentItem.objects.create(
                workspace=self.workspace, brand=brand, headline='A post',
            )
            return Feedback.objects.create(
                workspace=self.workspace,
                brand=brand,
                content_item=item,
                verdict=Feedback.Verdict.REJECT,
                element_keys=['headline'],
                feedback_text='The headline is far too long.',
            )

        a_feedback(self.tea)
        a_feedback(self.coffee)
        subject = a_feedback(self.coffee)

        matches = TrainingEngine(subject)._similar(subject.embedding or [])
        matched_brands = {
            str(Feedback.objects.get(pk=m['id']).brand_id) for m in matches
        }
        self.assertNotIn(
            str(self.tea.pk), matched_brands,
            'a sibling brand review must never count as evidence here',
        )
        self.assertTrue(
            matched_brands <= {str(self.coffee.pk)},
            f'evidence leaked across brands: {matched_brands}',
        )
