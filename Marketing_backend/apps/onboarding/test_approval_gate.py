"""
Signup approval gate.

A brand that arrived through signup is PENDING. While pending it can be read
and built on, but it cannot calibrate — calibration is real provider spend,
and approval is what says that spend is ours to incur. Approval unlocks it;
rejection archives and loses nothing; and no client-facing write can perform
the approval itself.
"""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework import status

from apps.ai.adapters.base import AIProviderAdapter
from apps.ai.models import AIProvider, Capability, WorkspaceAIProvider, WorkspaceAIRoute
from apps.ai.router import NoProviderAvailable
from apps.brands.models import Brand
from apps.brands.services.approval import approve_brand, reject_brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.knowledge.models import BrandSource
from apps.workspaces.models import WorkspaceMember

from .models import CalibrationDirection
from .services import BrandNotApproved, generate_calibration_round

ONBOARDING_URL = '/api/marketing/onboarding/'
BRANDS_URL = '/api/marketing/brands/'
GENERATE_URL = '/api/marketing/ai-generation/generate/'
GENERATE_ASYNC_URL = '/api/marketing/ai-generation/generate-async/'
ANALYZE_IMAGE_URL = '/api/marketing/ai-generation/analyze-image/'

FAKE_TEXT = {
    'headline': 'Roasted this week', 'caption': 'Fresh beans.',
    'hashtags': '#coffee', 'raw': {}, 'provider': 'OPENAI',
    'provider_name': 'OpenAI', 'latency_ms': 10,
}
FAKE_IMAGE = {
    'image_url': 'https://cdn.example.com/poster.png',
    'provider': 'STABILITY', 'provider_name': 'Stability', 'latency_ms': 20,
}


def fake_router(self_router, capability, brief, content_item_id=None):
    if capability == Capability.TEXT:
        return dict(FAKE_TEXT)
    if capability == Capability.IMAGE:
        return dict(FAKE_IMAGE)
    raise NoProviderAvailable(f'no {capability}')


class ApprovalGateTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.workspace = self.make_workspace('Workspace 1', 'c1')
        self.user, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner1'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', industry='Coffee',
            is_default=True, status=Brand.Status.PENDING,
        )

    def headers(self):
        return workspace_header(self.workspace)

    def calibrate(self):
        return self.api.post(
            f'{ONBOARDING_URL}{self.brand.id}/calibrate/', {}, format='json',
            **self.headers(),
        )

    # ------------------------------------------------------------ the gate

    def test_pending_brand_cannot_calibrate_and_no_provider_is_called(self):
        with patch('apps.ai.router.AIRouter.dispatch') as dispatch:
            response = self.calibrate()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        body = response.json()
        self.assertFalse(body['success'])
        self.assertEqual(body['error']['code'], 'BRAND_NOT_APPROVED')
        # The proof that a pending client incurs no spend: the router was
        # never reached, and nothing was written.
        dispatch.assert_not_called()
        self.assertFalse(CalibrationDirection.objects.exists())

    def test_service_refuses_a_pending_brand_even_when_called_directly(self):
        with patch('apps.ai.router.AIRouter.dispatch') as dispatch:
            with self.assertRaises(BrandNotApproved):
                generate_calibration_round(self.workspace, self.brand)
        dispatch.assert_not_called()

    def test_archived_brand_cannot_calibrate_either(self):
        reject_brand(self.brand, by=self.user)
        response = self.calibrate()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(CalibrationDirection.objects.exists())

    # ------------------------------------------------------------ still usable

    def test_pending_brand_is_readable_and_is_the_current_brand(self):
        summary = self.api.get(f'{ONBOARDING_URL}{self.brand.id}/', **self.headers())
        self.assertEqual(summary.status_code, status.HTTP_200_OK)

        # /brands/current/ must hand back the pending brand, not create a
        # second, already-approved one around the gate.
        current = self.api.get(f'{BRANDS_URL}current/', **self.headers())
        self.assertEqual(current.status_code, status.HTTP_200_OK)
        self.assertEqual(current.json()['data']['id'], str(self.brand.id))
        self.assertEqual(current.json()['data']['status'], 'PENDING')
        self.assertEqual(Brand.objects.filter(workspace=self.workspace).count(), 1)

    # ------------------------------------------------------------ no self-approval

    def test_client_cannot_approve_itself_through_a_brand_patch(self):
        response = self.api.patch(
            f'{BRANDS_URL}{self.brand.id}/', {'status': 'ACTIVE'}, format='json',
            **self.headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.status, Brand.Status.PENDING)

    def test_client_cannot_write_who_reviewed_it(self):
        response = self.api.patch(
            f'{BRANDS_URL}{self.brand.id}/',
            {'tagline': 'Fresh', 'reviewed_by': self.user.pk, 'reviewed_at': '2026-01-01T00:00:00Z'},
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.tagline, 'Fresh')
        self.assertIsNone(self.brand.reviewed_by)
        self.assertIsNone(self.brand.reviewed_at)

    def test_approved_brand_can_still_be_archived_and_restored_by_the_client(self):
        approve_brand(self.brand, by=self.user)
        for value in ('ARCHIVED', 'ACTIVE'):
            response = self.api.patch(
                f'{BRANDS_URL}{self.brand.id}/', {'status': value}, format='json',
                **self.headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
            self.brand.refresh_from_db()
            self.assertEqual(self.brand.status, value)

    # ------------------------------------------------------------ approval

    def test_approval_unlocks_calibration(self):
        approve_brand(self.brand, by=self.user)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.status, Brand.Status.ACTIVE)
        self.assertEqual(self.brand.reviewed_by, self.user)
        self.assertIsNotNone(self.brand.reviewed_at)

        with patch('apps.ai.router.AIRouter.dispatch', fake_router):
            response = self.calibrate()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertEqual(len(response.json()['data']['directions']), 3)

    def test_approve_is_idempotent(self):
        approve_brand(self.brand, by=self.user)
        self.brand.refresh_from_db()
        first = self.brand.reviewed_at
        approve_brand(self.brand, by=None)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.reviewed_at, first)
        self.assertEqual(self.brand.reviewed_by, self.user)

    def test_rejection_archives_and_keeps_everything(self):
        BrandSource.objects.create(
            workspace=self.workspace, brand=self.brand, title='Deck',
            status=BrandSource.SourceStatus.READY,
        )
        reject_brand(self.brand, by=self.user)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.status, Brand.Status.ARCHIVED)
        self.assertEqual(self.brand.reviewed_by, self.user)
        self.assertTrue(Brand.objects.filter(pk=self.brand.pk).exists())
        self.assertTrue(BrandSource.objects.filter(brand=self.brand).exists())

        # Reversible: approving an archived brand reinstates it.
        approve_brand(self.brand, by=self.user)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.status, Brand.Status.ACTIVE)


class GateTestAdapter(AIProviderAdapter):
    key = 'test-gate'
    display_name = 'Test Gate'
    capabilities = (Capability.TEXT, Capability.IMAGE, Capability.IMAGE_ANALYSIS)

    def health_check(self):
        return {'ok': True, 'detail': 'ready'}


class SpendGateAPITests(TenantFixtureMixin, TestCase):
    """No provider spend of any kind before approval — every AI endpoint."""

    def setUp(self):
        cache.clear()
        self.workspace = self.make_workspace('Pending Co', 'c-pending')
        self.user, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'pending-owner'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Pending Brand', industry='Coffee',
            is_default=True, status=Brand.Status.PENDING,
        )
        # A fully routed workspace, so the ONLY thing standing between the
        # request and the provider is approval.
        self.provider, _ = AIProvider.objects.update_or_create(
            key=GateTestAdapter.key,
            defaults={
                'display_name': GateTestAdapter.display_name,
                'capabilities': list(GateTestAdapter.capabilities),
                'unit_cost': 0,
                'is_available': True,
            },
        )
        self.wp = WorkspaceAIProvider.objects.create(
            workspace=self.workspace, provider=self.provider, enabled=True
        )
        for capability in GateTestAdapter.capabilities:
            WorkspaceAIRoute.objects.create(
                workspace=self.workspace, provider=self.provider,
                capability=capability, priority=10,
            )
        registry = patch(
            'apps.ai.registry.get_adapter_class',
            side_effect=lambda key: GateTestAdapter if key == self.provider.key else None,
        )
        registry.start()
        self.addCleanup(registry.stop)

    def headers(self):
        return workspace_header(self.workspace)

    def assert_blocked(self, response):
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        body = response.json()
        self.assertFalse(body['success'])
        self.assertEqual(body['error']['code'], 'CLIENT_NOT_APPROVED')

    def test_every_ai_endpoint_refuses_a_pending_client_without_reaching_a_provider(self):
        from apps.gemini.models import GeminiGenerationRequest
        from apps.ai.models import AIUsageLog

        with patch.object(GateTestAdapter, 'run') as run:
            self.assert_blocked(self.api.post(
                GENERATE_URL,
                {'creativeMode': 'AI_ORIGINAL', 'campaignName': 'Launch', 'product': 'Beans'},
                format='json', **self.headers(),
            ))
            self.assert_blocked(self.api.post(
                GENERATE_ASYNC_URL,
                {'creativeMode': 'AI_ORIGINAL', 'campaignName': 'Launch'},
                format='json', **self.headers(),
            ))
            self.assert_blocked(self.api.post(
                ANALYZE_IMAGE_URL, {'referenceImageBase64': 'aGVsbG8='},
                format='json', **self.headers(),
            ))
            self.assert_blocked(self.api.post(
                f'/api/marketing/ai/providers/{self.wp.id}/test/', {},
                format='json', **self.headers(),
            ))
        run.assert_not_called()
        self.assertFalse(AIUsageLog.objects.filter(workspace=self.workspace).exists())
        # No queued generation left behind to run the moment approval lands.
        self.assertFalse(GeminiGenerationRequest.objects.filter(workspace=self.workspace).exists())

    def test_the_router_itself_refuses_even_when_called_directly(self):
        from apps.ai.router import AIRouter
        from apps.brands.services.approval import SpendNotApproved

        with patch.object(GateTestAdapter, 'run') as run:
            with self.assertRaises(SpendNotApproved):
                AIRouter(self.workspace).dispatch(Capability.TEXT, {'prompt': 'x'})
        run.assert_not_called()

    def test_archived_only_client_is_refused_too(self):
        from apps.ai.router import AIRouter
        from apps.brands.services.approval import SpendNotApproved

        reject_brand(self.brand, by=self.user)
        with self.assertRaises(SpendNotApproved) as caught:
            AIRouter(self.workspace).dispatch(Capability.TEXT, {'prompt': 'x'})
        self.assertEqual(caught.exception.code, 'CLIENT_REJECTED')

    def test_a_workspace_without_any_brand_row_is_not_blocked(self):
        # Predates approval; nothing to approve. Existing tenants keep working.
        from apps.brands.services.approval import spend_block

        self.brand.delete()
        self.assertIsNone(spend_block(self.workspace))

    def test_approval_unlocks_generation(self):
        approve_brand(self.brand, by=self.user)
        with patch('apps.ai.router.AIRouter.dispatch', fake_router):
            response = self.api.post(
                GENERATE_URL,
                {'creativeMode': 'AI_ORIGINAL', 'campaignName': 'Launch', 'product': 'Beans'},
                format='json', **self.headers(),
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
