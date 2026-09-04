from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.ai.models import AIProvider, AIUsageLog, WorkspaceAIProvider, WorkspaceAIRoute
from apps.ai.tests import FakeAdapter
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember


class AdminClosureTests(APITestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(customer_id='closure', workspace_name='Closure')
        self.other = MarketingWorkspace.objects.create(customer_id='closure-other', workspace_name='Other')
        self.admin = get_user_model().objects.create_user(username='closure-admin')
        self.viewer = get_user_model().objects.create_user(username='closure-viewer')
        for user, role in ((self.admin, 'ADMIN'), (self.viewer, 'VIEWER')):
            WorkspaceMember.objects.create(workspace=self.workspace, user=user, role=role)
        self.provider = AIProvider.objects.create(key='closure-provider', display_name='Closure provider', capabilities=['TEXT', 'IMAGE'])
        self.configured = WorkspaceAIProvider.objects.create(workspace=self.workspace, provider=self.provider, enabled=True, capabilities=['TEXT', 'IMAGE'], model_override='model-a')
        self.url = f'/api/marketing/ai/providers/{self.configured.pk}/'
        self.client.force_authenticate(self.admin)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str(self.workspace.pk))
        self.adapter = patch('apps.ai.registry.get_adapter_class', return_value=FakeAdapter)
        self.adapter.start()
        self.addCleanup(self.adapter.stop)

    def mark_checked(self):
        checked_at = timezone.now()
        WorkspaceAIProvider.objects.filter(pk=self.configured.pk).update(last_health_ok=True, last_health_check_at=checked_at, last_error='old')
        return checked_at

    def test_changed_connection_configuration_invalidates_historical_health(self):
        for payload in ({'credentials': ''}, {'model_override': 'model-b'}, {'config': {'region': 'eu'}}, {'capabilities': ['TEXT']}):
            with self.subTest(payload=payload):
                self.mark_checked()
                response = self.client.patch(self.url, payload, format='json')
                self.assertEqual(response.status_code, 200, response.data)
                self.configured.refresh_from_db()
                self.assertIsNone(self.configured.last_health_ok)
                self.assertIsNone(self.configured.last_health_check_at)
                self.assertEqual(self.configured.last_error, '')

    def test_identical_configuration_and_spend_limit_do_not_reset_health(self):
        checked_at = self.mark_checked()
        response = self.client.patch(self.url, {'model_override': 'model-a', 'max_cost_per_generation': '2.00'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.configured.refresh_from_db()
        self.assertTrue(self.configured.last_health_ok)
        self.assertEqual(self.configured.last_health_check_at, checked_at)

    def test_reenable_preserves_inactive_routes_until_explicit_route_save(self):
        route = WorkspaceAIRoute.objects.create(workspace=self.workspace, provider=self.provider, capability='TEXT', enabled=True)
        for enabled in (False, True):
            self.assertEqual(self.client.patch(self.url, {'enabled': enabled}, format='json').status_code, 200)
        route.refresh_from_db()
        self.assertFalse(route.enabled)
        response = self.client.get('/api/marketing/ai/routes/')
        self.assertFalse(response.data[0]['enabled'])
        response = self.client.post('/api/marketing/ai/routes/replace-set/', {'capability': 'TEXT', 'routes': [{'provider': str(self.provider.pk), 'priority': 10}]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        route.refresh_from_db()
        self.assertTrue(route.enabled)
        self.assertEqual(route.strategy, 'ROUND_ROBIN')

    def test_viewer_cannot_change_or_read_provider_configuration(self):
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get('/api/marketing/ai/providers/').status_code, 403)
        self.assertEqual(self.client.patch(self.url, {'enabled': False}, format='json').status_code, 403)
        self.assertEqual(self.client.post(f'{self.url}test/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.post('/api/marketing/ai/routes/replace-set/', {'capability': 'TEXT', 'routes': []}, format='json').status_code, 403)
        self.configured.refresh_from_db()
        self.assertTrue(self.configured.enabled)

    def test_recent_usage_is_bounded_and_workspace_scoped(self):
        AIUsageLog.objects.bulk_create([AIUsageLog(workspace=self.workspace, provider=self.provider, capability='TEXT') for _ in range(30)])
        other = AIUsageLog.objects.create(workspace=self.other, provider=self.provider, capability='TEXT')
        response = self.client.get('/api/marketing/ai/usage/?page_size=25')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 30)
        self.assertEqual(len(response.data['results']), 25)
        self.assertNotIn(str(other.pk), {row['id'] for row in response.data['results']})
