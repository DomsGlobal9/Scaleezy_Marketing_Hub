"""OAuth authority, replay, health and disconnect failure boundaries."""
import uuid
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember
from .integrations.exceptions import LinkedInAuthenticationError, LinkedInPermissionError
from .models import SocialConnection, SocialAccountAuditLog
from .oauth_authority import bind_authority
from .utils.encryption import encrypt_token


class SocialAuthorityRecoveryTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Social recovery', 'social-recovery')
        self.user, self.client = self.authenticate_as(self.workspace, WorkspaceMember.Role.ADMIN, 'social-admin')
        self.headers = workspace_header(self.workspace)
        self.public = APIClient()
        self.connection = SocialConnection.objects.create(workspace=self.workspace, platform='X', external_account_id='account', account_name='Account', status='CONNECTED', access_token_encrypted=encrypt_token('test-token'))
        self.url = f'/api/marketing/social-accounts/{self.connection.pk}/'

    def state(self, platform='X'):
        value = str(uuid.uuid4())
        bind_authority(authorization_url=f'https://example.test/oauth?state={value}', workspace=self.workspace, user=self.user, platform=platform)
        return value

    def callback(self, state, platform='X'):
        return self.public.post('/api/marketing/social-accounts/oauth_callback/', {'code': 'one-use-code', 'platform': platform, 'state': state}, format='json')

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_callback_is_actor_bound_and_replay_safe(self, adapters):
        adapter = adapters.return_value
        adapter.exchange_code_for_token.return_value = {'access_token': 'new-token', 'workspace_id': str(self.workspace.pk), 'expires_in': 3600}
        adapter.get_account_info.return_value = {'id': 'account', 'name': 'Reconnected'}
        self.connection.status = 'TOKEN_EXPIRED'
        self.connection.reauthorization_required = True
        self.connection.last_error = 'old error'
        self.connection.save()
        state = self.state()
        self.assertEqual(self.callback(state).status_code, 200)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, 'CONNECTED')
        self.assertFalse(self.connection.reauthorization_required)
        self.assertIsNone(self.connection.last_error)
        self.assertEqual(self.connection.connected_by_id, self.user.pk)
        self.assertIsNotNone(self.connection.token_expires_at)
        self.assertEqual(self.callback(state).status_code, 400)
        adapter.exchange_code_for_token.assert_called_once()

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_downgraded_actor_cannot_exchange_token(self, adapters):
        state = self.state()
        WorkspaceMember.objects.filter(user=self.user).update(role='VIEWER')
        self.assertEqual(self.callback(state).status_code, 400)
        adapters.return_value.exchange_code_for_token.assert_not_called()

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_suspended_workspace_cannot_exchange_token(self, adapters):
        state = self.state()
        MarketingWorkspace.objects.filter(pk=self.workspace.pk).update(status=MarketingWorkspace.Status.SUSPENDED)
        self.assertEqual(self.callback(state).status_code, 400)
        adapters.return_value.exchange_code_for_token.assert_not_called()

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_authority_is_checked_again_after_provider_response(self, adapters):
        adapter = adapters.return_value
        adapter.exchange_code_for_token.return_value = {'access_token': 'new-token', 'workspace_id': str(self.workspace.pk)}
        def account_info(_token):
            WorkspaceMember.objects.filter(user=self.user).update(role='VIEWER')
            return {'id': 'new-account'}
        adapter.get_account_info.side_effect = account_info
        self.assertEqual(self.callback(self.state()).status_code, 400)
        self.assertFalse(SocialConnection.objects.filter(external_account_id='new-account').exists())

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_state_cannot_be_transferred_to_another_platform(self, adapters):
        self.assertEqual(self.callback(self.state(), platform='YOUTUBE').status_code, 400)
        adapters.return_value.exchange_code_for_token.assert_not_called()

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_meta_does_not_report_empty_or_tokenless_accounts_connected(self, adapters):
        adapter = adapters.return_value
        adapter.validate_state.return_value = str(self.workspace.pk)
        adapter.exchange_code_for_token.return_value = {'access_token': 'meta-user-token'}
        for accounts in ([], [{'id': 'page', 'platform': 'FACEBOOK'}]):
            adapter.get_account_info.return_value = {'accounts': accounts}
            self.assertEqual(self.callback(self.state('FACEBOOK'), 'FACEBOOK').status_code, 400)
        self.assertFalse(SocialConnection.objects.filter(platform='FACEBOOK').exists())

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_transient_verify_failure_preserves_credentials_and_reports_unknown(self, adapters):
        adapters.return_value.get_account_info.side_effect = TimeoutError('private internal detail')
        response = self.client.post(self.url + 'verify/', **self.headers)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('private internal detail', str(response.data))
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, 'CONNECTED')
        self.assertFalse(self.connection.reauthorization_required)
        self.assertIsNotNone(self.connection.access_token_encrypted)
        self.assertIsNone(self.connection.last_verified_at)

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_auth_and_permission_failures_are_distinct(self, adapters):
        for error, expected in ((LinkedInAuthenticationError(), 'TOKEN_EXPIRED'), (LinkedInPermissionError(), 'PERMISSION_MISSING')):
            adapters.return_value.get_account_info.side_effect = error
            self.assertEqual(self.client.post(self.url + 'verify/', **self.headers).status_code, 400)
            self.connection.refresh_from_db()
            self.assertEqual(self.connection.status, expected)
            self.assertTrue(self.connection.reauthorization_required)

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_disconnected_account_is_not_verified(self, adapters):
        self.connection.status = 'DISCONNECTED'
        self.connection.save()
        self.assertEqual(self.client.post(self.url + 'verify/', **self.headers).status_code, 400)
        adapters.assert_not_called()

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_local_disconnect_does_not_claim_remote_revocation(self, adapters):
        adapters.return_value.disconnect.return_value = False
        response = self.client.post(self.url + 'disconnect/', **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['data']['remote_revocation_confirmed'])
        self.connection.refresh_from_db()
        self.assertIsNone(self.connection.access_token_encrypted)
        self.assertEqual(self.connection.status, 'DISCONNECTED')

    def test_publishing_configuration_is_audited(self):
        self.assertEqual(self.client.patch(self.url, {'publishing_enabled': False}, format='json', **self.headers).status_code, 200)
        self.assertTrue(SocialAccountAuditLog.objects.filter(social_connection=self.connection, user=self.user, action='PUBLISHING_DISABLED').exists())

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_instagram_connect_uses_the_shared_meta_callback(self, adapters):
        adapter = adapters.return_value
        adapter.validate_state.return_value = str(self.workspace.pk)
        adapter.exchange_code_for_token.return_value = {'access_token': 'meta-token'}
        adapter.get_account_info.return_value = {'accounts': [{'id': 'ig-id', 'platform': 'INSTAGRAM', 'access_token': 'page-token'}]}
        response = self.callback(self.state('INSTAGRAM'), 'FACEBOOK')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(SocialConnection.objects.filter(platform='INSTAGRAM', external_account_id='ig-id', connected_by=self.user).exists())

    @patch('apps.social_accounts.integrations.x.requests.get')
    def test_real_x_adapter_reports_auth_permission_and_transient_failures(self, get):
        get.return_value.ok = False
        for http_status, expected_code, expected_state in ((401, 400, 'TOKEN_EXPIRED'), (403, 400, 'PERMISSION_MISSING'), (429, 502, 'CONNECTED'), (503, 502, 'CONNECTED')):
            SocialConnection.objects.filter(pk=self.connection.pk).update(status='CONNECTED', reauthorization_required=False)
            get.return_value.status_code = http_status
            response = self.client.post(self.url + 'verify/', **self.headers)
            self.assertEqual(response.status_code, expected_code)
            self.connection.refresh_from_db()
            self.assertEqual(self.connection.status, expected_state)
