"""
Generation must fail closed when there is no credential.

The defect this locks down: with no key, `generate_marketing_content` returned
canned copy, the router logged it as a successful Gemini call, and the API
persisted it as a real DRAFT ContentItem. A reviewer could approve and publish
fabricated marketing copy, and calibration would teach the brand from three
identical mock directions.

Nothing here calls Gemini. The two "a key is present" tests patch the two
methods that would reach the network and assert only which key arrived.
"""
from unittest.mock import Mock, patch

import httpx
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.ai.models import AIProvider, AIUsageLog, Capability, WorkspaceAIProvider, WorkspaceAIRoute
from apps.brands.models import Brand
from apps.content.models import ContentItem
from apps.gemini.services.generator import GeminiGeneratorService, GeminiNotConfigured
from apps.learning.models import LearningEvent, PreferenceEvidence
from apps.onboarding.models import CalibrationDirection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()

BRIEF = {'campaign_name': 'Diwali'}


class ServiceCredentialTests(TestCase):
    """Credential resolution: workspace key, else server key, else refuse."""

    @override_settings(GEMINI_API_KEY='', GEMINI_MOCK_MODE=False)
    def test_no_key_anywhere_raises_rather_than_fabricating(self):
        with self.assertRaises(GeminiNotConfigured):
            GeminiGeneratorService.generate_marketing_content(BRIEF)

    @override_settings(GEMINI_API_KEY='', GEMINI_MOCK_MODE=False)
    def test_workspace_credential_is_used_when_the_server_has_none(self):
        seen = {}

        def capture(request_data, api_key=''):
            seen['key'] = api_key
            return {'postTitle': 'Real', 'postDescription': 'Real copy', 'imagePrompt': ''}

        with patch.object(GeminiGeneratorService, 'generate_text_and_image_prompt', capture):
            result = GeminiGeneratorService.generate_marketing_content(
                BRIEF, api_key='workspace-key'
            )

        self.assertEqual(seen['key'], 'workspace-key')
        self.assertEqual(result['postTitle'], 'Real')
        self.assertFalse(result['metadata']['mocked'])

    @override_settings(GEMINI_API_KEY='server-key', GEMINI_MOCK_MODE=False)
    def test_server_key_is_used_when_the_workspace_has_none(self):
        seen = {}

        def capture(request_data, api_key=''):
            seen['key'] = api_key
            return {'postTitle': 'Real', 'postDescription': 'Real copy', 'imagePrompt': ''}

        with patch.object(GeminiGeneratorService, 'generate_text_and_image_prompt', capture):
            GeminiGeneratorService.generate_marketing_content(BRIEF)

        self.assertEqual(seen['key'], 'server-key')

    @override_settings(GEMINI_API_KEY='server-key', GEMINI_MOCK_MODE=False)
    def test_the_workspace_credential_wins_over_the_server_one(self):
        seen = {}

        def capture(request_data, api_key=''):
            seen['key'] = api_key
            return {'postTitle': 'Real', 'postDescription': '', 'imagePrompt': ''}

        with patch.object(GeminiGeneratorService, 'generate_text_and_image_prompt', capture):
            GeminiGeneratorService.generate_marketing_content(BRIEF, api_key='workspace-key')

        self.assertEqual(seen['key'], 'workspace-key')

    @override_settings(GEMINI_API_KEY='', GEMINI_MOCK_MODE=False)
    def test_client_construction_refuses_without_a_key(self):
        with self.assertRaises(GeminiNotConfigured):
            GeminiGeneratorService._get_client()

    @override_settings(GEMINI_API_KEY='', GEMINI_MOCK_MODE=True)
    def test_mock_mode_produces_placeholder_copy_only_when_switched_on(self):
        result = GeminiGeneratorService.generate_marketing_content(BRIEF)
        self.assertTrue(result['metadata']['mocked'])
        self.assertIn('Diwali', result['postTitle'])

    @override_settings(GEMINI_API_KEY='', GEMINI_MOCK_MODE=False)
    def test_the_same_call_refuses_once_mock_mode_is_off(self):
        with self.assertRaises(GeminiNotConfigured):
            GeminiGeneratorService.generate_marketing_content(BRIEF)


class AdapterCredentialTests(TestCase):
    """The adapter must hand its workspace credential to the service."""

    @override_settings(GEMINI_API_KEY='', GEMINI_MOCK_MODE=False)
    def test_adapter_passes_its_credential_through(self):
        from apps.ai.adapters.gemini import GeminiAdapter

        seen = {}

        def capture(request_data, api_key=''):
            seen['key'] = api_key
            return {'postTitle': 'Real', 'postDescription': '', 'imagePrompt': ''}

        adapter = GeminiAdapter(credentials='tenant-key', model='m', config={})
        with patch.object(GeminiGeneratorService, 'generate_text_and_image_prompt', capture):
            adapter.generate_text(BRIEF)

        self.assertEqual(seen['key'], 'tenant-key')

    @override_settings(GEMINI_API_KEY='', GEMINI_MOCK_MODE=False)
    def test_adapter_with_no_credential_and_no_server_key_fails(self):
        from apps.ai.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(credentials='', model='m', config={})
        with self.assertRaises(GeminiNotConfigured):
            adapter.generate_text(BRIEF)

    @override_settings(
        GEMINI_API_KEY='',
        GEMINI_API_BASE_URL='https://gemini.test/v1beta',
        AI_PROVIDER_HEALTH_TIMEOUT=4.0,
    )
    @patch('apps.ai.adapters.gemini.httpx.get')
    def test_health_check_authenticates_without_generation(self, get):
        from apps.ai.adapters.gemini import GeminiAdapter

        get.return_value = Mock(status_code=200)
        result = GeminiAdapter(credentials='tenant-key').health_check()

        self.assertTrue(result['ok'])
        url, kwargs = get.call_args
        self.assertEqual(url[0], 'https://gemini.test/v1beta/models')
        self.assertEqual(kwargs['headers']['x-goog-api-key'], 'tenant-key')
        self.assertEqual(kwargs['timeout'], 4.0)
        self.assertNotIn('tenant-key', str(result))

    @override_settings(GEMINI_API_KEY='')
    @patch('apps.ai.adapters.gemini.httpx.get')
    def test_health_check_sanitizes_invalid_credentials(self, get):
        from apps.ai.adapters.gemini import GeminiAdapter

        get.return_value = Mock(status_code=403, text='private upstream detail')
        result = GeminiAdapter(credentials='bad-key').health_check()

        self.assertEqual(result, {'ok': False, 'detail': 'Gemini authentication failed.'})
        self.assertNotIn('bad-key', str(result))
        self.assertNotIn('private upstream detail', str(result))

    @override_settings(GEMINI_API_KEY='')
    @patch('apps.ai.adapters.gemini.httpx.get')
    def test_health_check_reports_timeout_without_raising(self, get):
        from apps.ai.adapters.gemini import GeminiAdapter

        get.side_effect = httpx.TimeoutException('private timeout detail')
        result = GeminiAdapter(credentials='tenant-key').health_check()

        self.assertEqual(result, {'ok': False, 'detail': 'Gemini health check timed out.'})


@override_settings(GEMINI_API_KEY='', GEMINI_MOCK_MODE=False)
class NothingIsPersistedFromAMissingKeyTests(TestCase):
    """End to end: a refused generation must leave no trace that says it worked."""

    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='c1', workspace_name='One')
        self.user = User.objects.create_user(username='u1', password='p')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.user, role=WorkspaceMember.Role.ADMIN
        )
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Acme', industry='Retail', tagline='Made well',
        )
        # Routing IS configured, so the router genuinely selects Gemini and the
        # attempt fails at the provider - which is what must be recorded.
        provider, _ = AIProvider.objects.get_or_create(
            key='gemini',
            defaults={'display_name': 'Google Gemini',
                      'capabilities': ['TEXT', 'IMAGE', 'IMAGE_ANALYSIS', 'EMBEDDING']},
        )
        WorkspaceAIProvider.objects.create(workspace=self.ws, provider=provider, enabled=True)
        for capability in (Capability.TEXT, Capability.IMAGE):
            WorkspaceAIRoute.objects.create(
                workspace=self.ws, capability=capability, provider=provider,
                priority=100, enabled=True,
            )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.hdr = {'HTTP_X_WORKSPACE_ID': str(self.ws.pk)}

    def test_create_is_refused_and_persists_no_content_item(self):
        response = self.client.post(
            '/api/marketing/gemini/generate/',
            {'campaignName': 'Diwali', 'contentType': 'poster'},
            format='json', **self.hdr,
        )

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()['success'])
        self.assertEqual(response.json()['error']['code'], 'NO_PROVIDER')
        self.assertFalse(ContentItem.objects.exists())

    def test_the_usage_log_records_a_failure_not_a_success(self):
        self.client.post(
            '/api/marketing/gemini/generate/',
            {'campaignName': 'Diwali', 'contentType': 'poster'},
            format='json', **self.hdr,
        )

        self.assertTrue(AIUsageLog.objects.exists(), "the attempt should be recorded")
        self.assertFalse(
            AIUsageLog.objects.filter(success=True).exists(),
            "a call that never reached Gemini must not be logged as successful",
        )

    def test_calibration_is_refused_and_persists_no_directions(self):
        response = self.client.post(
            f'/api/marketing/onboarding/{self.brand.pk}/calibrate/', {},
            format='json', **self.hdr,
        )

        self.assertEqual(response.status_code, 503)
        self.assertFalse(CalibrationDirection.objects.exists())

    def test_calibration_produces_no_learning_from_content_that_never_existed(self):
        self.client.post(
            f'/api/marketing/onboarding/{self.brand.pk}/calibrate/', {},
            format='json', **self.hdr,
        )

        self.assertFalse(LearningEvent.objects.exists())
        self.assertFalse(PreferenceEvidence.objects.exists())

    def test_the_brand_brain_is_not_credited_with_a_generation(self):
        """A refused generation must not look like a compile-worthy event."""
        self.client.post(
            '/api/marketing/gemini/generate/', {'campaignName': 'Diwali'},
            format='json', **self.hdr,
        )
        self.brand.refresh_from_db()
        self.assertFalse(ContentItem.objects.filter(brand=self.brand).exists())


@override_settings(GEMINI_API_KEY='', GEMINI_MOCK_MODE=False)
class ProductionCannotEnableMockModeTests(TestCase):
    def test_the_flag_cannot_be_turned_on_by_environment_alone_in_production(self):
        """settings.py folds DEBUG/test-runner into the value, so a stray
        GEMINI_MOCK_MODE=True in a production environment stays off."""
        import importlib

        from django.conf import settings as live

        source = importlib.import_module('scaleezy_backend.settings')
        self.assertIn('DEBUG or _RUNNING_TESTS', open(source.__file__, encoding='utf-8').read())
        # And the shipped default is off.
        self.assertFalse(getattr(live, 'GEMINI_MOCK_MODE', True) is True and not live.DEBUG)
