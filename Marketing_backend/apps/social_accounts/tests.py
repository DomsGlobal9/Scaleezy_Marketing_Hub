"""
Comprehensive tests for LinkedIn integration.

Covers: OAuth flow, state validation, token exchange, connection creation,
workspace isolation, disconnect, publishing, and adapter error handling.

All external HTTP calls are mocked — no real LinkedIn API calls are made.
"""

import uuid
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.marketing.models import MarketingAsset
from apps.publishing.models import PublishingJob, PublishingJobItem
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember
from apps.social_accounts.models import SocialConnection, SocialAccountAuditLog
from apps.social_accounts.serializers import SocialConnectionSerializer
from apps.social_accounts.integrations.linkedin import LinkedInAdapter
from apps.social_accounts.integrations.exceptions import (
    LinkedInAuthenticationError,
    LinkedInConfigurationError,
    LinkedInMediaUploadError,
    LinkedInOAuthError,
    LinkedInPermissionError,
    LinkedInPublishingError,
    LinkedInRateLimitError,
    LinkedInStateValidationError,
)
from apps.social_accounts.utils.encryption import encrypt_token, decrypt_token

User = get_user_model()


class LinkedInAdapterTests(TestCase):
    """Tests for the LinkedInAdapter class."""

    def setUp(self):
        self.adapter = LinkedInAdapter()
        # OAuth unit tests must not depend on whichever credentials happen to
        # exist in the developer or CI environment.
        self.adapter.client_id = 'linkedin-test-client'
        self.adapter.client_secret = 'linkedin-test-secret'
        self.adapter.redirect_uri = 'https://example.test/linkedin/callback'
        # Clear cache between tests
        cache.clear()

    def tearDown(self):
        cache.clear()

    # ── 1. Authorization URL generation ──────────────────────────────────────

    @patch.object(LinkedInAdapter, '_ensure_configured')
    def test_authorization_url_contains_required_params(self, mock_configured):
        """Test that the authorization URL contains all required OAuth parameters."""
        workspace_id = str(uuid.uuid4())
        url = self.adapter.get_authorization_url(workspace_id)

        self.assertIn("response_type=code", url)
        self.assertIn("client_id=", url)
        self.assertIn("redirect_uri=", url)
        self.assertIn("scope=", url)
        self.assertIn("state=", url)
        self.assertIn("linkedin.com/oauth/v2/authorization", url)

    @patch.object(LinkedInAdapter, '_ensure_configured')
    def test_authorization_url_stores_state_in_cache(self, mock_configured):
        """Test that the state is stored in cache for later validation."""
        workspace_id = str(uuid.uuid4())
        url = self.adapter.get_authorization_url(workspace_id)

        # Extract state from URL
        import re
        state_match = re.search(r'state=([a-f0-9-]+)', url)
        self.assertIsNotNone(state_match)
        state = state_match.group(1)

        # Verify cache entries
        self.assertEqual(cache.get(f"linkedin_state_{state}"), state)
        self.assertEqual(cache.get(f"linkedin_ws_{state}"), workspace_id)

    def test_authorization_url_raises_if_not_configured(self):
        """Test that NOT_CONFIGURED is raised when client_id is empty."""
        self.adapter.client_id = ''
        self.adapter.client_secret = ''
        with self.assertRaises(LinkedInConfigurationError):
            self.adapter.get_authorization_url("test-workspace")

    # ── 2. OAuth state validation ────────────────────────────────────────────

    @patch.object(LinkedInAdapter, '_ensure_configured')
    def test_state_validation_returns_workspace_id(self, mock_configured):
        """Test that valid state returns the correct workspace_id."""
        workspace_id = str(uuid.uuid4())
        url = self.adapter.get_authorization_url(workspace_id)

        import re
        state = re.search(r'state=([a-f0-9-]+)', url).group(1)

        result = self.adapter.validate_state(state)
        self.assertEqual(result, workspace_id)

    # ── 3. Invalid state ─────────────────────────────────────────────────────

    def test_invalid_state_raises_error(self):
        """Test that an invalid/unknown state raises LinkedInStateValidationError."""
        with self.assertRaises(LinkedInStateValidationError):
            self.adapter.validate_state("invalid-state-value")

    def test_state_cannot_be_reused(self):
        """Test that state is one-time use — second validation fails."""
        workspace_id = str(uuid.uuid4())

        with patch.object(LinkedInAdapter, '_ensure_configured'):
            url = self.adapter.get_authorization_url(workspace_id)

        import re
        state = re.search(r'state=([a-f0-9-]+)', url).group(1)

        # First use succeeds
        self.adapter.validate_state(state)

        # Second use fails
        with self.assertRaises(LinkedInStateValidationError):
            self.adapter.validate_state(state)

    # ── 4. OAuth callback failure ────────────────────────────────────────────

    @patch('apps.social_accounts.integrations.linkedin.requests.post')
    def test_token_exchange_failure(self, mock_post):
        """Test that token exchange failure raises LinkedInOAuthError."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Authorization code expired"
        }
        mock_post.return_value = mock_response

        with self.assertRaises(LinkedInOAuthError):
            self.adapter.exchange_code_for_token("invalid-code")

    # ── 5. Successful token exchange ─────────────────────────────────────────

    @patch('apps.social_accounts.integrations.linkedin.requests.post')
    def test_successful_token_exchange(self, mock_post):
        """Test that a successful token exchange returns access_token."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "access_token": "real_token_abc123",
            "expires_in": 5184000,
            "scope": "openid profile email w_member_social",
        }
        mock_post.return_value = mock_response

        result = self.adapter.exchange_code_for_token("valid-code")

        self.assertEqual(result["access_token"], "real_token_abc123")
        self.assertEqual(result["expires_in"], 5184000)
        self.assertIn("w_member_social", result["scopes"])

    # ── 6. Account info retrieval ────────────────────────────────────────────

    @patch('apps.social_accounts.integrations.linkedin.requests.get')
    def test_get_account_info_success(self, mock_get):
        """Test successful account info retrieval."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "sub": "member123",
            "name": "Test User",
            "email": "test@example.com",
            "picture": "https://media.licdn.com/photo.jpg",
        }
        mock_get.return_value = mock_response

        result = self.adapter.get_account_info("valid_token")

        self.assertEqual(result["id"], "member123")
        self.assertEqual(result["name"], "Test User")
        self.assertEqual(result["email"], "test@example.com")

    @patch('apps.social_accounts.integrations.linkedin.requests.get')
    def test_get_account_info_auth_failure(self, mock_get):
        """Test that 401 on userinfo raises LinkedInAuthenticationError."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.json.return_value = {"message": "Unauthorized"}
        mock_get.return_value = mock_response

        with self.assertRaises(LinkedInAuthenticationError):
            self.adapter.get_account_info("expired_token")


class LinkedInConnectionTests(TestCase):
    """Tests for LinkedIn connection creation and workspace isolation."""

    def setUp(self):
        self.workspace_a = MarketingWorkspace.objects.create(
            customer_id="customer_a",
            workspace_name="Workspace A",
        )
        self.workspace_b = MarketingWorkspace.objects.create(
            customer_id="customer_b",
            workspace_name="Workspace B",
        )

    # ── 7. Connection creation ───────────────────────────────────────────────

    def test_linkedin_connection_created(self):
        """Test that a LinkedIn SocialConnection can be created."""
        connection = SocialConnection.objects.create(
            workspace=self.workspace_a,
            platform=SocialConnection.Platform.LINKEDIN,
            external_account_id="member123",
            account_name="Test User",
            username="test@example.com",
            status=SocialConnection.Status.CONNECTED,
            access_token_encrypted=encrypt_token("test_token"),
            scopes="openid profile email w_member_social",
        )

        self.assertEqual(connection.platform, "LINKEDIN")
        self.assertEqual(connection.status, "CONNECTED")
        self.assertEqual(connection.external_account_id, "member123")

    # ── 8. Workspace isolation ───────────────────────────────────────────────

    def test_workspace_isolation(self):
        """Test that connections are scoped to their workspace."""
        SocialConnection.objects.create(
            workspace=self.workspace_a,
            platform=SocialConnection.Platform.LINKEDIN,
            external_account_id="member_a",
            account_name="User A",
            status=SocialConnection.Status.CONNECTED,
        )
        SocialConnection.objects.create(
            workspace=self.workspace_b,
            platform=SocialConnection.Platform.LINKEDIN,
            external_account_id="member_b",
            account_name="User B",
            status=SocialConnection.Status.CONNECTED,
        )

        ws_a_connections = SocialConnection.objects.filter(workspace=self.workspace_a)
        ws_b_connections = SocialConnection.objects.filter(workspace=self.workspace_b)

        self.assertEqual(ws_a_connections.count(), 1)
        self.assertEqual(ws_a_connections.first().account_name, "User A")
        self.assertEqual(ws_b_connections.count(), 1)
        self.assertEqual(ws_b_connections.first().account_name, "User B")

    def test_unique_constraint_prevents_duplicate(self):
        """Test that the same LinkedIn account can't be connected twice to one workspace."""
        SocialConnection.objects.create(
            workspace=self.workspace_a,
            platform=SocialConnection.Platform.LINKEDIN,
            external_account_id="member123",
            account_name="User A",
        )

        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            SocialConnection.objects.create(
                workspace=self.workspace_a,
                platform=SocialConnection.Platform.LINKEDIN,
                external_account_id="member123",
                account_name="User A duplicate",
            )

    # ── 9. Disconnect ────────────────────────────────────────────────────────

    def test_disconnect_clears_credentials(self):
        """Test that disconnect clears tokens and marks as disconnected."""
        connection = SocialConnection.objects.create(
            workspace=self.workspace_a,
            platform=SocialConnection.Platform.LINKEDIN,
            external_account_id="member123",
            account_name="Test User",
            status=SocialConnection.Status.CONNECTED,
            access_token_encrypted=encrypt_token("secret_token"),
            refresh_token_encrypted=encrypt_token("secret_refresh"),
            publishing_enabled=True,
        )

        # Simulate disconnect
        connection.status = SocialConnection.Status.DISCONNECTED
        connection.disconnected_at = timezone.now()
        connection.access_token_encrypted = None
        connection.refresh_token_encrypted = None
        connection.publishing_enabled = False
        connection.save()

        connection.refresh_from_db()
        self.assertEqual(connection.status, "DISCONNECTED")
        self.assertIsNone(connection.access_token_encrypted)
        self.assertIsNone(connection.refresh_token_encrypted)
        self.assertFalse(connection.publishing_enabled)


class DisconnectRoleGateTests(TestCase):
    """Role gates and closed raw mutation paths for social accounts.

    Disconnecting clears tokens and halts scheduled publishing until someone
    re-runs OAuth — account configuration, gated at ADMIN. Lower roles must
    get a 403 and the connection must be left untouched.
    """

    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id="customer_gate",
            workspace_name="Gate Workspace",
        )

    def _client_with_role(self, role):
        user = User.objects.create_user(username=f"gate_{role.lower()}", password="pw")
        WorkspaceMember.objects.create(workspace=self.workspace, user=user, role=role)
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _connection(self):
        # No stored token, so the best-effort platform-side revoke is skipped
        # and no network call is ever attempted from the test.
        return SocialConnection.objects.create(
            workspace=self.workspace,
            platform=SocialConnection.Platform.LINKEDIN,
            external_account_id=f"member-{uuid.uuid4().hex[:8]}",
            account_name="Gated User",
            status=SocialConnection.Status.CONNECTED,
            publishing_enabled=True,
        )

    def _disconnect(self, client, connection):
        return client.post(
            f"/api/marketing/social-accounts/{connection.id}/disconnect/",
            {},
            format="json",
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

    def test_roles_below_admin_get_403(self):
        for role in (
            WorkspaceMember.Role.VIEWER,
            WorkspaceMember.Role.EDITOR,
            WorkspaceMember.Role.MANAGER,
        ):
            client = self._client_with_role(role)
            connection = self._connection()
            response = self._disconnect(client, connection)
            self.assertEqual(response.status_code, 403, role)
            connection.refresh_from_db()
            self.assertEqual(connection.status, SocialConnection.Status.CONNECTED, role)
            self.assertTrue(connection.publishing_enabled, role)

    def test_admin_and_owner_can_disconnect(self):
        for role in (WorkspaceMember.Role.ADMIN, WorkspaceMember.Role.OWNER):
            client = self._client_with_role(role)
            connection = self._connection()
            response = self._disconnect(client, connection)
            self.assertEqual(response.status_code, 200, role)
            connection.refresh_from_db()
            self.assertEqual(connection.status, SocialConnection.Status.DISCONNECTED, role)
            self.assertFalse(connection.publishing_enabled, role)
            self.assertTrue(
                SocialAccountAuditLog.objects.filter(
                    social_connection=connection,
                    action=SocialAccountAuditLog.Action.ACCOUNT_DISCONNECTION,
                ).exists(),
                role,
            )

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_lower_roles_cannot_connect_patch_or_verify(self, get_adapter):
        for role in (
            WorkspaceMember.Role.VIEWER,
            WorkspaceMember.Role.EDITOR,
            WorkspaceMember.Role.MANAGER,
        ):
            client = self._client_with_role(role)
            connection = self._connection()
            headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.id)}
            requests = (
                (
                    'post', '/api/marketing/social-accounts/connect/',
                    {'workspace_id': str(self.workspace.id), 'platform': 'LINKEDIN'},
                ),
                (
                    'patch', f'/api/marketing/social-accounts/{connection.id}/',
                    {'publishing_enabled': False, 'is_default_account': True},
                ),
                (
                    'post', f'/api/marketing/social-accounts/{connection.id}/verify/', {},
                ),
            )
            for method, url, payload in requests:
                with self.subTest(role=role, method=method, url=url):
                    response = getattr(client, method)(url, payload, format='json', **headers)
                    self.assertEqual(response.status_code, 403)
            connection.refresh_from_db()
            self.assertTrue(connection.publishing_enabled)
            self.assertFalse(connection.is_default_account)
            self.assertEqual(connection.status, SocialConnection.Status.CONNECTED)
            self.assertIsNone(connection.last_verified_at)
        get_adapter.assert_not_called()
        self.assertFalse(SocialAccountAuditLog.objects.exists())

    def test_every_member_role_can_list_and_retrieve(self):
        connection = self._connection()
        for role in WorkspaceMember.Role.values:
            client = self._client_with_role(role)
            headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.id)}
            with self.subTest(role=role):
                response = client.get('/api/marketing/social-accounts/', **headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual([str(row['id']) for row in response.data], [str(connection.id)])
                response = client.get(
                    f'/api/marketing/social-accounts/{connection.id}/', **headers
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(str(response.data['id']), str(connection.id))

    def test_raw_create_put_delete_are_refused_and_publishing_history_survives(self):
        connection = self._connection()
        asset = MarketingAsset.objects.create(
            workspace=self.workspace, file_name='history.jpg', source='MANUAL_UPLOAD'
        )
        job = PublishingJob.objects.create(
            workspace=self.workspace, asset=asset, status=PublishingJob.Status.PUBLISHED
        )
        item = PublishingJobItem.objects.create(
            publishing_job=job,
            social_connection=connection,
            status=PublishingJobItem.Status.PUBLISHED,
            external_post_id='confirmed-post',
            external_post_url='https://example.test/confirmed-post',
            published_at=timezone.now(),
        )
        for role in WorkspaceMember.Role.values:
            client = self._client_with_role(role)
            expected = 405 if role in (
                WorkspaceMember.Role.ADMIN, WorkspaceMember.Role.OWNER
            ) else 403
            requests = (
                ('post', '/api/marketing/social-accounts/'),
                ('put', f'/api/marketing/social-accounts/{connection.id}/'),
                ('delete', f'/api/marketing/social-accounts/{connection.id}/'),
            )
            for method, url in requests:
                with self.subTest(role=role, method=method):
                    response = getattr(client, method)(
                        url,
                        {'platform': 'X', 'external_account_id': 'forged', 'account_name': 'Forged'},
                        format='json',
                        HTTP_X_WORKSPACE_ID=str(self.workspace.id),
                    )
                    self.assertEqual(response.status_code, expected)
                    self.assertTrue(SocialConnection.objects.filter(pk=connection.pk).exists())
                    self.assertTrue(PublishingJob.objects.filter(pk=job.pk).exists())
                    item.refresh_from_db()
                    self.assertEqual(item.status, PublishingJobItem.Status.PUBLISHED)
                    self.assertEqual(item.external_post_id, 'confirmed-post')
        self.assertEqual(SocialConnection.objects.count(), 1)
        self.assertFalse(SocialAccountAuditLog.objects.exists())

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_admin_can_start_connect_or_reconnect(self, get_adapter):
        client = self._client_with_role(WorkspaceMember.Role.ADMIN)
        self._connection()
        get_adapter.return_value.get_authorization_url.return_value = 'https://example.test/oauth'
        response = client.post(
            '/api/marketing/social-accounts/connect/',
            {'workspace_id': str(self.workspace.id), 'platform': 'LINKEDIN'},
            format='json',
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['authorization_url'], 'https://example.test/oauth')
        get_adapter.return_value.get_authorization_url.assert_called_once_with(
            workspace_id=str(self.workspace.id)
        )

    @patch('apps.social_accounts.views.decrypt_token', return_value='access-token')
    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_admin_can_verify(self, get_adapter, decrypt):
        client = self._client_with_role(WorkspaceMember.Role.ADMIN)
        connection = self._connection()
        get_adapter.return_value.get_account_info.return_value = {'id': connection.external_account_id}
        response = client.post(
            f'/api/marketing/social-accounts/{connection.id}/verify/',
            {},
            format='json',
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )
        self.assertEqual(response.status_code, 200)
        get_adapter.return_value.get_account_info.assert_called_once_with('access-token')
        connection.refresh_from_db()
        self.assertEqual(connection.status, SocialConnection.Status.CONNECTED)
        self.assertIsNotNone(connection.last_verified_at)

    def test_admin_patch_only_changes_explicit_configuration_fields(self):
        writable = {
            name for name, field in SocialConnectionSerializer().fields.items()
            if not field.read_only
        }
        self.assertEqual(writable, {'publishing_enabled', 'is_default_account'})
        client = self._client_with_role(WorkspaceMember.Role.ADMIN)
        connection = self._connection()
        other = MarketingWorkspace.objects.create(customer_id='other', workspace_name='Other')
        before = SocialConnection.objects.values().get(pk=connection.pk)
        forged_time = (timezone.now() + timedelta(days=30)).isoformat()
        response = client.patch(
            f'/api/marketing/social-accounts/{connection.id}/',
            {
                'publishing_enabled': False,
                'is_default_account': True,
                'id': str(uuid.uuid4()),
                'workspace': str(other.id),
                'platform': 'YOUTUBE',
                'account_type': 'organization',
                'external_account_id': 'forged-id',
                'account_name': 'Forged account',
                'username': 'forged-user',
                'profile_url': 'https://example.test/forged',
                'profile_image_url': 'https://example.test/forged.png',
                'status': SocialConnection.Status.DISCONNECTED,
                'last_verified_at': forged_time,
                'last_published_at': forged_time,
                'last_error': 'Forged error',
                'connected_at': forged_time,
                'reauthorization_required': True,
            },
            format='json',
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )
        self.assertEqual(response.status_code, 200)
        after = SocialConnection.objects.values().get(pk=connection.pk)
        self.assertFalse(after['publishing_enabled'])
        self.assertTrue(after['is_default_account'])
        for field, value in before.items():
            if field not in {'publishing_enabled', 'is_default_account', 'updated_at'}:
                with self.subTest(field=field):
                    self.assertEqual(after[field], value)
        self.assertNotIn('access_token_encrypted', response.data)
        self.assertNotIn('refresh_token_encrypted', response.data)


class LinkedInPublishingTests(TestCase):
    """Tests for LinkedIn publishing."""

    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id="customer_pub",
            workspace_name="Publishing Workspace",
        )
        self.adapter = LinkedInAdapter()

    # ── 10. Publishing without connection ────────────────────────────────────

    def test_publish_without_token_raises_error(self):
        """Test that publishing without an access token fails."""
        with self.assertRaises(LinkedInAuthenticationError):
            self.adapter.publish_text("", "urn:li:person:123", "Test post")

    # ── 11. Text publishing ──────────────────────────────────────────────────

    @patch('apps.social_accounts.integrations.linkedin.requests.post')
    def test_publish_text_success(self, mock_post):
        """Test successful text post publishing."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.headers = {"x-restli-id": "urn:li:share:123456"}
        mock_post.return_value = mock_response

        result = self.adapter.publish_text(
            "valid_token", "urn:li:person:abc", "Hello LinkedIn!"
        )

        self.assertEqual(result["id"], "urn:li:share:123456")
        self.assertIn("linkedin.com/feed/update/", result["url"])

    # ── 12. LinkedIn API authentication failure ──────────────────────────────

    @patch('apps.social_accounts.integrations.linkedin.requests.post')
    def test_publish_auth_failure(self, mock_post):
        """Test that 401 during publishing raises LinkedInAuthenticationError."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.json.return_value = {"message": "Invalid access token"}
        mock_post.return_value = mock_response

        with self.assertRaises(LinkedInAuthenticationError):
            self.adapter.publish_text(
                "expired_token", "urn:li:person:abc", "Test"
            )

    # ── 13. LinkedIn permission failure ──────────────────────────────────────

    @patch('apps.social_accounts.integrations.linkedin.requests.post')
    def test_publish_permission_failure(self, mock_post):
        """Test that 403 during publishing raises LinkedInPermissionError."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 403
        mock_response.json.return_value = {"message": "Insufficient permissions"}
        mock_post.return_value = mock_response

        with self.assertRaises(LinkedInPermissionError):
            self.adapter.publish_text(
                "valid_token", "urn:li:person:abc", "Test"
            )

    # ── 14. LinkedIn image upload failure ────────────────────────────────────

    @patch('apps.social_accounts.integrations.linkedin.requests.post')
    def test_image_upload_init_failure(self, mock_post):
        """Test that image upload initialization failure raises LinkedInMediaUploadError."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.json.return_value = {"message": "Upload service unavailable"}
        mock_post.return_value = mock_response

        with self.assertRaises(Exception):
            self.adapter._initialize_image_upload("valid_token", "urn:li:person:abc")

    # ── 15. Successful image publishing ──────────────────────────────────────

    @patch('apps.social_accounts.integrations.linkedin.requests.post')
    @patch('apps.social_accounts.integrations.linkedin.requests.put')
    def test_publish_image_success(self, mock_put, mock_post):
        """Test the complete image publishing flow (init → upload → create post)."""
        # Step 1: Initialize upload
        init_response = MagicMock()
        init_response.ok = True
        init_response.json.return_value = {
            "value": {
                "uploadUrl": "https://api.linkedin.com/upload/123",
                "image": "urn:li:image:abc",
            }
        }

        # Step 3: Create post (called second time)
        post_response = MagicMock()
        post_response.ok = True
        post_response.headers = {"x-restli-id": "urn:li:share:789"}

        mock_post.side_effect = [init_response, post_response]

        # Step 2: Upload bytes
        upload_response = MagicMock()
        upload_response.ok = True
        mock_put.return_value = upload_response

        result = self.adapter.publish_image(
            "valid_token",
            "urn:li:person:abc",
            "Check out this poster!",
            b"fake_image_bytes",
        )

        self.assertEqual(result["id"], "urn:li:share:789")
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_put.call_count, 1)

    # ── Rate limiting ────────────────────────────────────────────────────────

    @patch('apps.social_accounts.integrations.linkedin.requests.post')
    def test_rate_limiting(self, mock_post):
        """Test that 429 raises LinkedInRateLimitError."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 429
        mock_response.json.return_value = {"message": "Rate limit exceeded"}
        mock_post.return_value = mock_response

        with self.assertRaises(LinkedInRateLimitError):
            self.adapter.publish_text(
                "valid_token", "urn:li:person:abc", "Test"
            )


class LinkedInTokenEncryptionTests(TestCase):
    """Verify that tokens are properly encrypted/decrypted."""

    def test_token_roundtrip(self):
        """Test that a token can be encrypted and decrypted correctly."""
        original_token = "test_access_token_12345"
        encrypted = encrypt_token(original_token)

        # Encrypted should not be the plaintext
        self.assertNotEqual(encrypted, original_token)

        # Decrypted should match original
        decrypted = decrypt_token(encrypted)
        self.assertEqual(decrypted, original_token)

    def test_none_token_passthrough(self):
        """Test that None/empty tokens pass through without error."""
        self.assertIsNone(encrypt_token(None))
        self.assertIsNone(decrypt_token(None))
        self.assertEqual(encrypt_token(""), "")
        self.assertEqual(decrypt_token(""), "")


class LinkedInExceptionTests(TestCase):
    """Verify that custom exceptions carry safe user-facing messages."""

    def test_auth_error_has_safe_message(self):
        e = LinkedInAuthenticationError()
        self.assertIn("reconnect", e.safe_message.lower())
        self.assertEqual(e.error_code, "LINKEDIN_AUTH_FAILED")

    def test_permission_error_has_safe_message(self):
        e = LinkedInPermissionError()
        self.assertIn("permission", e.safe_message.lower())

    def test_rate_limit_error_has_safe_message(self):
        e = LinkedInRateLimitError()
        self.assertIn("rate limit", e.safe_message.lower())

    def test_oauth_cancel_has_friendly_message(self):
        e = LinkedInOAuthError(oauth_error="user_cancelled_authorize")
        self.assertIn("cancelled", e.safe_message.lower())

    def test_state_validation_error(self):
        e = LinkedInStateValidationError()
        self.assertIn("expired", e.safe_message.lower())
