"""
PR6 CTO blockers, pinned.

Three defects: the calibration stage completed on one verdict out of three;
directions claimed to test visual dimensions while generating only text, then
learned LAYOUT and IMAGERY from a sentence of copy; and Adjust recorded a note
that influenced nothing. Each fix gets a regression here.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.ai.models import Capability
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.context.services.context_gateway import (
    TaskType,
    build_generation_context,
    context_as_brief,
)
from apps.learning.models import BrandPreference, BrandRule, LearningEvent
from apps.workspaces.models import WorkspaceMember

from .models import BrandOnboarding, CalibrationDirection
from .services import (
    ensure_onboarding,
    generate_calibration_round,
    record_calibration_verdict,
    refresh_stage,
    skip_stage,
)

FAKE_TEXT = {
    'headline': 'Roasted this week',
    'caption': 'Beans that were green on Monday.',
    'hashtags': '#coffee',
    'raw': {},
    'provider': 'FAKE',
    'provider_name': 'Fake',
    'latency_ms': 5,
}
FAKE_IMAGE = {
    'image_url': 'https://cdn.example.com/direction.png',
    'provider': 'FAKE',
}


def multimodal_dispatch(self_router, capability, brief, content_item_id=None):
    if capability == Capability.TEXT:
        return dict(FAKE_TEXT)
    if capability == Capability.IMAGE:
        return dict(FAKE_IMAGE)
    raise RuntimeError(f'unexpected {capability}')


def text_only_dispatch(self_router, capability, brief, content_item_id=None):
    if capability == Capability.TEXT:
        return dict(FAKE_TEXT)
    raise RuntimeError('no image provider')


class CalibrationBlockerBase(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'acme-1')
        self.owner, self.client = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'owner'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', industry='Coffee',
            tagline='Roasted this week',
        )
        # Stage derivation stops at the first incomplete stage, and these
        # tests are about calibration, not the stages before it. Skip the
        # earlier ones so the stage under observation is the one under test.
        onboarding = ensure_onboarding(self.brand)
        skip_stage(onboarding, BrandOnboarding.Stage.KNOWLEDGE)
        skip_stage(onboarding, BrandOnboarding.Stage.INSPIRATIONS)

    def make_round(self, dispatch=multimodal_dispatch):
        with patch('apps.ai.router.AIRouter.dispatch', dispatch):
            return generate_calibration_round(self.workspace, self.brand)

    def stage(self):
        return refresh_stage(ensure_onboarding(self.brand)).current_stage


class AllThreeVerdictsRequiredTests(CalibrationBlockerBase):
    def test_one_verdict_does_not_complete_the_stage(self):
        directions = self.make_round()
        record_calibration_verdict(
            directions[0], CalibrationDirection.Verdict.LIKED, user=self.owner
        )
        self.assertEqual(self.stage(), BrandOnboarding.Stage.CALIBRATION)

        record_calibration_verdict(
            directions[1], CalibrationDirection.Verdict.NOT_US, user=self.owner
        )
        self.assertEqual(self.stage(), BrandOnboarding.Stage.CALIBRATION)

    def test_all_three_verdicts_complete_the_stage(self):
        directions = self.make_round()
        for direction in directions:
            record_calibration_verdict(
                direction, CalibrationDirection.Verdict.LIKED, user=self.owner
            )
        self.assertEqual(self.stage(), BrandOnboarding.Stage.FIRST_GENERATION)

    def test_a_new_round_reopens_the_requirement(self):
        for direction in self.make_round():
            record_calibration_verdict(
                direction, CalibrationDirection.Verdict.LIKED, user=self.owner
            )
        self.assertEqual(self.stage(), BrandOnboarding.Stage.FIRST_GENERATION)

        # A fresh round means fresh, unjudged directions: the latest round
        # governs, so the stage reopens until they are decided too.
        self.make_round()
        self.assertEqual(self.stage(), BrandOnboarding.Stage.CALIBRATION)

    def test_an_explicit_skip_releases_the_remainder(self):
        directions = self.make_round()
        record_calibration_verdict(
            directions[0], CalibrationDirection.Verdict.LIKED, user=self.owner
        )
        self.assertEqual(self.stage(), BrandOnboarding.Stage.CALIBRATION)

        skip_stage(ensure_onboarding(self.brand), BrandOnboarding.Stage.CALIBRATION)
        self.assertEqual(self.stage(), BrandOnboarding.Stage.FIRST_GENERATION)


class VisualCalibrationEvidenceTests(CalibrationBlockerBase):
    def test_directions_display_the_visuals_they_claim_to_test(self):
        directions = self.make_round()
        self.assertEqual(len(directions), 3)
        for direction in directions:
            with self.subTest(direction=direction.label):
                self.assertEqual(
                    direction.preview_url, 'https://cdn.example.com/direction.png'
                )

    def test_a_visual_direction_teaches_its_visual_attributes(self):
        directions = self.make_round()
        # Direction A tests LAYOUT/density alongside its copy dimensions.
        record_calibration_verdict(
            directions[0], CalibrationDirection.Verdict.LIKED, user=self.owner
        )
        self.assertTrue(
            BrandPreference.objects.filter(
                brand=self.brand, category='LAYOUT', attribute='density'
            ).exists()
        )

    def test_visual_attributes_are_never_learned_from_text_only_output(self):
        """The blocker itself: no visual shown, no visual verdict recorded."""
        directions = self.make_round(dispatch=text_only_dispatch)
        for direction in directions:
            self.assertEqual(direction.preview_url, '')

        # Direction B claims LAYOUT/density, TONE/register, IMAGERY/style.
        record_calibration_verdict(
            directions[1], CalibrationDirection.Verdict.LIKED, user=self.owner
        )

        self.assertTrue(
            BrandPreference.objects.filter(
                brand=self.brand, category='TONE', attribute='register'
            ).exists(),
            "the copy dimension the user actually saw must still be learned",
        )
        for category in ('LAYOUT', 'IMAGERY'):
            with self.subTest(category=category):
                self.assertFalse(
                    BrandPreference.objects.filter(
                        brand=self.brand, category=category
                    ).exists(),
                    f"{category} was learned from output that displayed no visual",
                )


class AdjustLearningTests(CalibrationBlockerBase):
    NOTE = 'Less text. Image feels too corporate.'

    def adjust_direction_a(self):
        directions = self.make_round()
        direction, learned = record_calibration_verdict(
            directions[0], CalibrationDirection.Verdict.ADJUSTED,
            user=self.owner, note=self.NOTE,
        )
        return direction, learned

    def test_adjust_becomes_persistent_soft_learning(self):
        direction, learned = self.adjust_direction_a()
        self.assertTrue(learned, "an adjustment must actually teach something")

        adjustments = BrandPreference.objects.filter(
            brand=self.brand, attribute__endswith='adjustment'
        )
        self.assertTrue(adjustments.exists())
        for preference in adjustments:
            with self.subTest(attribute=preference.attribute):
                # Verbatim, emerging, and nowhere near a rule.
                self.assertEqual(preference.value, self.NOTE)
                self.assertEqual(preference.state, BrandPreference.State.EMERGING)
        self.assertFalse(
            BrandRule.objects.filter(brand=self.brand).exists(),
            "a single correction must never mint a rule",
        )

    def test_the_original_correction_is_preserved_verbatim(self):
        direction, _ = self.adjust_direction_a()
        direction.refresh_from_db()
        self.assertEqual(direction.adjustment_note, self.NOTE)
        # And the learning event carries it too, for the audit trail.
        event = LearningEvent.objects.get(pk=direction.learning_event_id)
        self.assertEqual(event.context['note'], self.NOTE)

    def test_the_adjustment_reaches_the_next_generation_context(self):
        self.adjust_direction_a()

        context = build_generation_context(self.workspace, self.brand, TaskType.COPY)
        values = [c['value'] for c in context['preferences']]
        self.assertIn(self.NOTE, values, "the correction never reached the context")

        brief = context_as_brief(context)
        self.assertTrue(
            any(self.NOTE in line for line in brief['brand_context']),
            "the correction is in the context but not in the brief the provider sees",
        )

    def test_adjustment_learning_is_traceable_to_its_event(self):
        direction, _ = self.adjust_direction_a()
        preference = BrandPreference.objects.filter(
            brand=self.brand, attribute__endswith='adjustment'
        ).first()
        self.assertEqual(
            list(
                preference.evidence.values_list('learning_event_id', flat=True)
            ),
            [direction.learning_event_id],
        )

    def test_a_repeated_adjust_is_idempotent(self):
        direction, _ = self.adjust_direction_a()
        before = BrandPreference.objects.filter(brand=self.brand).count()
        _, learned_again = record_calibration_verdict(
            direction, CalibrationDirection.Verdict.ADJUSTED,
            user=self.owner, note='Different note entirely',
        )
        self.assertFalse(learned_again)
        direction.refresh_from_db()
        self.assertEqual(direction.adjustment_note, self.NOTE)
        self.assertEqual(
            BrandPreference.objects.filter(brand=self.brand).count(), before
        )
