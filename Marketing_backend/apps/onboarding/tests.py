"""
PR6 — onboarding, calibration, the learning loop, and the accelerator.

The chain under test is the demo the mission requires: create brand → basics →
knowledge → inspiration → three calibration directions → verdicts → persistent
learning → brain rebuild → readiness moves → first generation persists.
"""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework import status

from apps.ai.models import Capability
from apps.ai.router import NoProviderAvailable
from apps.brands.models import Brand
from apps.brands.services.brand_brain import rebuild_brand_brain
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.content.models import ContentItem
from apps.context.services.context_gateway import build_generation_context, TaskType
from apps.context.services.generation import generate_copy_and_image, retry_image
from apps.context.services.readiness import brand_readiness
from apps.inspirations.models import BrandInspiration
from apps.knowledge.models import BrandSource
from apps.learning.models import BrandPreference, LearningEvent
from apps.workspaces.models import WorkspaceMember

from .models import BrandOnboarding, CalibrationDirection
from .services import (
    ensure_onboarding,
    generate_calibration_round,
    record_calibration_verdict,
    refresh_stage,
)

ONBOARDING_URL = '/api/marketing/onboarding/'
DIRECTIONS_URL = '/api/marketing/calibration-directions/'
GENERATE_URL = '/api/marketing/gemini/generate/'

FAKE_TEXT = {
    'headline': 'Roasted this week', 'caption': 'Fresh beans.',
    'hashtags': '#coffee', 'raw': {}, 'provider': 'OPENAI',
    'provider_name': 'OpenAI', 'latency_ms': 10,
}
FAKE_IMAGE = {
    'image_url': 'https://cdn.example.com/poster.png',
    'provider': 'STABILITY', 'provider_name': 'Stability', 'latency_ms': 20,
}


def fake_router(calls=None, image_fails=False):
    def dispatch(self_router, capability, brief, content_item_id=None):
        if calls is not None:
            calls.append({'capability': capability, 'brief': brief})
        if capability == Capability.TEXT:
            return dict(FAKE_TEXT)
        if capability == Capability.IMAGE:
            if image_fails:
                raise NoProviderAvailable('image route down')
            return dict(FAKE_IMAGE)
        raise NoProviderAvailable(f'no {capability}')
    return dispatch


class OnboardingTestBase(TenantFixtureMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.workspace1 = self.make_workspace('Workspace 1', 'c1')
        self.user1, self.client1 = self.authenticate_as(
            self.workspace1, WorkspaceMember.Role.ADMIN, 'user1'
        )
        self.viewer, self.viewer_client = self.authenticate_as(
            self.workspace1, WorkspaceMember.Role.VIEWER, 'viewer'
        )
        self.brand1 = Brand.objects.create(
            workspace=self.workspace1, name='Acme Coffee', industry='Coffee',
            is_default=True,
        )
        self.workspace2 = self.make_workspace('Workspace 2', 'c2')
        self.user2, self.client2 = self.authenticate_as(
            self.workspace2, WorkspaceMember.Role.ADMIN, 'user2'
        )
        self.brand2 = Brand.objects.create(
            workspace=self.workspace2, name='Rival', is_default=True,
        )

    def ws1(self):
        return workspace_header(self.workspace1)

    def add_knowledge(self, brand=None):
        return BrandSource.objects.create(
            workspace=(brand or self.brand1).workspace, brand=brand or self.brand1,
            title='Deck', status=BrandSource.SourceStatus.READY,
        )

    def add_inspiration(self, brand=None):
        return BrandInspiration.objects.create(
            workspace=(brand or self.brand1).workspace, brand=brand or self.brand1,
            title='Reference', reference_url='https://example.com/x',
        )

    def calibrated_direction(self):
        with patch('apps.ai.router.AIRouter.dispatch', fake_router()):
            return generate_calibration_round(self.workspace1, self.brand1)[0]


class OrchestrationTests(OnboardingTestBase):
    def test_stage_derives_from_what_actually_exists(self):
        onboarding = refresh_stage(ensure_onboarding(self.brand1))
        # Basics exist (name + industry), nothing else does.
        self.assertEqual(onboarding.current_stage, BrandOnboarding.Stage.KNOWLEDGE)
        self.assertEqual(onboarding.status, BrandOnboarding.Status.IN_PROGRESS)

        self.add_knowledge()
        onboarding = refresh_stage(onboarding)
        self.assertEqual(onboarding.current_stage, BrandOnboarding.Stage.INSPIRATIONS)

    def test_onboarding_resumes_from_persisted_state(self):
        """Refresh/exit/resume: a second retrieve sees the same derived state,
        including progress made outside the onboarding screen."""
        self.add_knowledge()
        first = self.client1.get(
            f'{ONBOARDING_URL}{self.brand1.id}/', **self.ws1()
        ).json()['data']
        self.add_inspiration()
        second = self.client1.get(
            f'{ONBOARDING_URL}{self.brand1.id}/', **self.ws1()
        ).json()['data']
        self.assertEqual(first['onboarding']['current_stage'], 'INSPIRATIONS')
        self.assertEqual(second['onboarding']['current_stage'], 'CALIBRATION')

    def test_generation_completes_onboarding(self):
        self.add_knowledge()
        self.add_inspiration()
        direction = self.calibrated_direction()
        record_calibration_verdict(
            direction, CalibrationDirection.Verdict.LIKED, user=self.user1
        )
        ContentItem.objects.create(
            workspace=self.workspace1, brand=self.brand1, headline='First',
        )
        onboarding = refresh_stage(ensure_onboarding(self.brand1))
        self.assertEqual(onboarding.status, BrandOnboarding.Status.COMPLETED)
        self.assertIsNotNone(onboarding.completed_at)

    def test_basics_cannot_be_skipped_but_inspirations_can(self):
        response = self.client1.post(
            f'{ONBOARDING_URL}{self.brand1.id}/skip/',
            {'stage': 'BASICS'}, format='json', **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        ok = self.client1.post(
            f'{ONBOARDING_URL}{self.brand1.id}/skip/',
            {'stage': 'INSPIRATIONS'}, format='json', **self.ws1(),
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.assertIn(
            'INSPIRATIONS',
            ok.json()['data']['onboarding']['skipped_steps'],
        )

    def test_onboarding_is_tenant_scoped(self):
        response = self.client2.get(
            f'{ONBOARDING_URL}{self.brand1.id}/', **workspace_header(self.workspace2)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_viewer_cannot_mutate_onboarding(self):
        for url, body in (
            (f'{ONBOARDING_URL}{self.brand1.id}/skip/', {'stage': 'KNOWLEDGE'}),
            (f'{ONBOARDING_URL}{self.brand1.id}/calibrate/', {}),
        ):
            with self.subTest(url=url):
                response = self.viewer_client.post(url, body, format='json', **self.ws1())
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class CalibrationTests(OnboardingTestBase):
    def test_calibration_generates_three_purposeful_directions(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', fake_router(calls)):
            response = self.client1.post(
                f'{ONBOARDING_URL}{self.brand1.id}/calibrate/', {}, format='json',
                **self.ws1(),
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        directions = response.json()['data']['directions']
        self.assertEqual(
            [d['tests_dimension'] for d in directions],
            ['minimal_restrained', 'expressive_editorial', 'conversion_focused'],
        )
        # Six router calls now - copy AND imagery per direction, because a
        # direction that claims to test layout must actually display one.
        # Each call carried gateway context.
        capabilities = [call['capability'] for call in calls]
        self.assertEqual(capabilities.count('TEXT'), 3)
        self.assertEqual(capabilities.count('IMAGE'), 3)
        for call in calls:
            self.assertIn('brand_context', call['brief'])

    def test_calibration_respects_hard_rules(self):
        from apps.learning.models import BrandRule
        from apps.learning.services import create_explicit_rule

        create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1,
            text='Never show a competitor logo', hardness=BrandRule.Hardness.HARD,
        )
        rebuild_brand_brain(self.brand1)

        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', fake_router(calls)):
            generate_calibration_round(self.workspace1, self.brand1)
        for call in calls:
            self.assertIn(
                'MUST: Never show a competitor logo', call['brief']['brand_context']
            )

    def test_no_provider_is_reported_honestly(self):
        response = self.client1.post(
            f'{ONBOARDING_URL}{self.brand1.id}/calibrate/', {}, format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(CalibrationDirection.objects.exists())


class VerdictLearningTests(OnboardingTestBase):
    def test_like_persists_learning_with_provenance(self):
        direction = self.calibrated_direction()
        direction, learned = record_calibration_verdict(
            direction, CalibrationDirection.Verdict.LIKED, user=self.user1
        )
        self.assertTrue(learned)
        event = LearningEvent.objects.get(pk=direction.learning_event_id)
        self.assertEqual(event.outcome, LearningEvent.Outcome.POSITIVE)
        self.assertEqual(event.subject_id, direction.pk)
        # Each tested attribute became preference evidence.
        self.assertEqual(
            BrandPreference.objects.filter(brand=self.brand1).count(),
            len(direction.tested_attributes),
        )

    def test_not_us_persists_negative_learning(self):
        direction = self.calibrated_direction()
        _, learned = record_calibration_verdict(
            direction, CalibrationDirection.Verdict.NOT_US, user=self.user1
        )
        self.assertTrue(learned)
        event = LearningEvent.objects.get(subject_id=direction.pk)
        self.assertEqual(event.outcome, LearningEvent.Outcome.NEGATIVE)
        self.assertTrue(
            BrandPreference.objects.filter(value__contains='avoided').exists()
        )

    def test_adjust_preserves_the_correction(self):
        direction = self.calibrated_direction()
        direction, _ = record_calibration_verdict(
            direction, CalibrationDirection.Verdict.ADJUSTED,
            user=self.user1, note='Less text, warmer photography.',
        )
        self.assertEqual(direction.adjustment_note, 'Less text, warmer photography.')
        event = LearningEvent.objects.get(pk=direction.learning_event_id)
        self.assertEqual(event.outcome, LearningEvent.Outcome.MIXED)
        self.assertEqual(event.context['note'], 'Less text, warmer photography.')

    def test_adjust_requires_a_note(self):
        direction = self.calibrated_direction()
        response = self.client1.post(
            f'{DIRECTIONS_URL}{direction.pk}/react/',
            {'reaction': 'adjust'}, format='json', **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_verdicts_are_idempotent(self):
        direction = self.calibrated_direction()
        record_calibration_verdict(
            direction, CalibrationDirection.Verdict.LIKED, user=self.user1
        )
        events_before = LearningEvent.objects.count()
        preferences_before = list(
            BrandPreference.objects.values_list('evidence_count', flat=True)
        )

        direction.refresh_from_db()
        _, learned = record_calibration_verdict(
            direction, CalibrationDirection.Verdict.NOT_US, user=self.user1
        )

        self.assertFalse(learned)
        direction.refresh_from_db()
        self.assertEqual(direction.verdict, CalibrationDirection.Verdict.LIKED)
        self.assertEqual(LearningEvent.objects.count(), events_before)
        self.assertEqual(
            list(BrandPreference.objects.values_list('evidence_count', flat=True)),
            preferences_before,
        )

    def test_learning_rebuilds_the_brain_and_moves_readiness(self):
        rebuild_brand_brain(self.brand1)
        before_version = self.brand1.creative_brain['brain_version']
        before_score = brand_readiness(self.brand1)['readiness_score']

        direction = self.calibrated_direction()
        record_calibration_verdict(
            direction, CalibrationDirection.Verdict.LIKED, user=self.user1
        )

        self.brand1.refresh_from_db()
        self.assertNotEqual(
            self.brand1.creative_brain['brain_version'], before_version
        )
        after_score = brand_readiness(self.brand1)['readiness_score']
        self.assertGreater(after_score, before_score)

    def test_readiness_does_not_move_without_real_learning(self):
        rebuild_brand_brain(self.brand1)
        before = brand_readiness(self.brand1)['readiness_score']
        # A repeated verdict on an already-decided direction learns nothing.
        direction = self.calibrated_direction()
        record_calibration_verdict(
            direction, CalibrationDirection.Verdict.LIKED, user=self.user1
        )
        moved = brand_readiness(self.brand1)['readiness_score']
        direction.refresh_from_db()
        record_calibration_verdict(
            direction, CalibrationDirection.Verdict.LIKED, user=self.user1
        )
        self.assertEqual(brand_readiness(self.brand1)['readiness_score'], moved)
        self.assertGreater(moved, before)

    def test_a_foreign_direction_is_unreachable(self):
        direction = self.calibrated_direction()
        response = self.client2.post(
            f'{DIRECTIONS_URL}{direction.pk}/react/',
            {'reaction': 'like'}, format='json',
            **workspace_header(self.workspace2),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        direction.refresh_from_db()
        self.assertEqual(direction.verdict, CalibrationDirection.Verdict.PENDING)
        self.assertFalse(LearningEvent.objects.filter(workspace=self.workspace2).exists())

    def test_sibling_brand_learning_stays_apart(self):
        sibling = Brand.objects.create(workspace=self.workspace1, name='Acme Tea')
        direction = self.calibrated_direction()
        record_calibration_verdict(
            direction, CalibrationDirection.Verdict.LIKED, user=self.user1
        )
        self.assertFalse(BrandPreference.objects.filter(brand=sibling).exists())


class AcceleratorTests(OnboardingTestBase):
    def test_generation_does_not_recompile_an_unchanged_brain(self):
        rebuild_brand_brain(self.brand1)
        with patch(
            'apps.context.services.context_gateway.compile_brand_brain'
        ) as compiler:
            build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
            compiler.assert_not_called()

    def test_bounded_context_is_reused_while_the_brain_is_unchanged(self):
        """The second call returns the cached cut, not a second selection."""
        rebuild_brand_brain(self.brand1)
        first = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
        # Selection reads brain['preferences']; strip it from the stored brain
        # so a REAL second selection would visibly differ. The cached cut must
        # come back identical anyway.
        self.brand1.creative_brain['preferences'] = [
            {'category': 'TONE', 'attribute': 'planted', 'value': 'planted',
             'sentiment': 'NEUTRAL', 'authority': 'emerging_preference',
             'source_type': 'brand_preference', 'source_id': 'x',
             'confidence': 0, 'weight': 0}
        ]
        self.brand1.save(update_fields=['creative_brain'])
        second = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
        self.assertEqual(first, second)
        self.assertNotIn(
            'planted', [c['attribute'] for c in second['preferences']]
        )

    def test_brain_version_change_invalidates_cached_context(self):
        rebuild_brand_brain(self.brand1)
        first = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)

        self.add_knowledge()
        from apps.knowledge.models import BrandMemory

        BrandMemory.objects.create(
            workspace=self.workspace1, brand=self.brand1,
            memory_type=BrandMemory.MemoryType.PRODUCT_TRUTH,
            content='Roasted within 48 hours',
            status=BrandMemory.MemoryStatus.CONFIRMED,
        )
        rebuild_brand_brain(self.brand1)
        second = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)

        self.assertNotEqual(first['brain_version'], second['brain_version'])
        self.assertIn('Roasted within 48 hours', second['verified_truth'])

    def test_the_context_cache_never_crosses_tenants(self):
        rebuild_brand_brain(self.brand1)
        rebuild_brand_brain(self.brand2)
        mine = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
        theirs = build_generation_context(self.workspace2, self.brand2, TaskType.COPY)
        self.assertNotEqual(mine['brand_id'], theirs['brand_id'])
        self.assertEqual(mine['brand_identity']['name'], 'Acme Coffee')
        self.assertEqual(theirs['brand_identity']['name'], 'Rival')

    def test_copy_survives_an_image_failure_and_only_the_image_retries(self):
        rebuild_brand_brain(self.brand1)
        with patch(
            'apps.ai.router.AIRouter.dispatch', fake_router(image_fails=True)
        ):
            outcome = generate_copy_and_image(
                self.workspace1, self.brand1, {}, instruction='Launch',
            )
        self.assertIsNotNone(outcome['text'])
        self.assertIsNone(outcome['image'])
        self.assertEqual(
            outcome['trace']['capabilities'][Capability.TEXT]['status'], 'OK'
        )
        self.assertEqual(
            outcome['trace']['capabilities'][Capability.IMAGE]['status'], 'FAILED'
        )

        # The retry touches ONLY the image capability.
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', fake_router(calls)):
            retried = retry_image(self.workspace1, self.brand1, {}, instruction='Launch')
        self.assertEqual(retried['image_url'], FAKE_IMAGE['image_url'])
        self.assertEqual([c['capability'] for c in calls], [Capability.IMAGE])

    def test_generation_trace_is_persisted_on_the_content_item(self):
        with patch('apps.ai.router.AIRouter.dispatch', fake_router()):
            response = self.client1.post(
                GENERATE_URL,
                {'campaignName': 'Spring', 'product': 'Beans'},
                format='json', **self.ws1(),
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = ContentItem.objects.get(id=response.json()['data']['contentItemId'])
        trace = item.layout_config['generation_trace']
        self.assertEqual(trace['capabilities'][Capability.TEXT]['provider'], 'OPENAI')
        self.assertTrue(trace['brain_version'])

    def test_provider_metadata_is_accurate(self):
        with patch('apps.ai.router.AIRouter.dispatch', fake_router()):
            response = self.client1.post(
                GENERATE_URL, {'campaignName': 'Spring'}, format='json', **self.ws1(),
            )
        data = response.json()['data']
        self.assertEqual(data['metadata']['provider'], 'OPENAI')
        item = ContentItem.objects.get(id=data['contentItemId'])
        self.assertEqual(item.ai_provider, 'OPENAI')


class FirstGenerationTests(OnboardingTestBase):
    def test_first_generation_uses_the_pr5_pipeline_and_persists(self):
        """The end of the demo: the normal production path, a real ContentItem,
        and onboarding moving to COMPLETED."""
        self.add_knowledge()
        self.add_inspiration()
        direction = self.calibrated_direction()
        record_calibration_verdict(
            direction, CalibrationDirection.Verdict.LIKED, user=self.user1
        )

        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', fake_router(calls)):
            response = self.client1.post(
                GENERATE_URL, {'campaignName': 'First post'}, format='json', **self.ws1(),
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Gateway context reached the router (PR5 pipeline, not a side door).
        self.assertIn('brand_context', calls[0]['brief'])
        item = ContentItem.objects.get(id=response.json()['data']['contentItemId'])
        self.assertEqual(item.workspace_id, self.workspace1.id)

        onboarding = refresh_stage(ensure_onboarding(self.brand1))
        self.assertEqual(onboarding.status, BrandOnboarding.Status.COMPLETED)
