import uuid
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone
from django.core.cache import cache

from apps.workspaces.models import MarketingWorkspace
from apps.social_accounts.models import SocialConnection
from apps.social_accounts.integrations.meta.facebook import FacebookAdapter
from apps.social_accounts.integrations.meta.instagram import InstagramAdapter
from apps.social_accounts.integrations.meta.exceptions import (
    MetaAuthenticationError,
    MetaConfigurationError,
    MetaOAuthError,
    MetaPermissionError,
    MetaRateLimitError,
    MetaStateValidationError,
    MetaPublishingError,
    MetaMediaUploadError,
)
from apps.social_accounts.utils.encryption import encrypt_token, decrypt_token


class MetaAdapterTests(TestCase):
    """Tests for the unified Meta (Facebook/Instagram) Adapters."""

    def setUp(self):
        self.fb_adapter = FacebookAdapter()
        self.ig_adapter = InstagramAdapter()
        cache.clear()

    def tearDown(self):
        cache.clear()

    # ── 1. Configuration & URL generation ────────────────────────────────────

    @patch.object(FacebookAdapter, '_ensure_configured')
    def test_authorization_url_generation(self, mock_configured):
        workspace_id = str(uuid.uuid4())
        url = self.fb_adapter.get_authorization_url(workspace_id)

        self.assertIn("dialog/oauth", url)
        self.assertIn("client_id=", url)
        self.assertIn("redirect_uri=", url)
        self.assertIn("state=", url)
        self.assertIn("scope=", url)

    @override_settings(META_CLIENT_ID='')
    def test_missing_configuration_raises_error(self):
        with self.assertRaises(MetaConfigurationError):
            self.fb_adapter.get_authorization_url("test-ws")

    # ── 2. State Validation ──────────────────────────────────────────────────

    @patch.object(FacebookAdapter, '_ensure_configured')
    def test_state_validation(self, mock_configured):
        workspace_id = "ws-123"
        url = self.fb_adapter.get_authorization_url(workspace_id)
        
        import re
        state = re.search(r'state=([a-f0-9-]+)', url).group(1)
        
        self.assertEqual(self.fb_adapter.validate_state(state), workspace_id)
        
        with self.assertRaises(MetaStateValidationError):
            self.fb_adapter.validate_state(state)

    # ── 3. Token Exchange ────────────────────────────────────────────────────

    @patch('apps.social_accounts.integrations.meta.facebook.requests.get')
    def test_token_exchange_success(self, mock_get):
        # First call: short-lived token
        mock_short_lived = MagicMock()
        mock_short_lived.ok = True
        mock_short_lived.json.return_value = {"access_token": "short_lived_123"}
        
        # Second call: long-lived token
        mock_long_lived = MagicMock()
        mock_long_lived.ok = True
        mock_long_lived.json.return_value = {"access_token": "long_lived_456", "expires_in": 5184000}
        
        mock_get.side_effect = [mock_short_lived, mock_long_lived]
        
        with patch.object(FacebookAdapter, '_ensure_configured'):
            result = self.fb_adapter.exchange_code_for_token("auth_code")
            
        self.assertEqual(result["access_token"], "long_lived_456")
        self.assertEqual(result["expires_in"], 5184000)

    # ── 4. Account Discovery (Pages + IG) ────────────────────────────────────

    @patch('apps.social_accounts.integrations.meta.facebook.requests.get')
    def test_get_account_info_discovers_fb_and_ig(self, mock_get):
        # /me/accounts mock
        mock_pages = MagicMock()
        mock_pages.ok = True
        mock_pages.json.return_value = {
            "data": [
                {
                    "id": "page_1",
                    "name": "My Page",
                    "access_token": "page_token_1",
                    "instagram_business_account": {"id": "ig_1"}
                }
            ]
        }
        
        # /ig_id mock
        mock_ig = MagicMock()
        mock_ig.ok = True
        mock_ig.json.return_value = {
            "id": "ig_1",
            "username": "my_ig",
            "name": "My IG Account"
        }
        
        mock_get.side_effect = [mock_pages, mock_ig]
        
        result = self.fb_adapter.get_account_info("user_token")
        accounts = result["accounts"]
        
        self.assertEqual(len(accounts), 2)
        
        fb = next(a for a in accounts if a["platform"] == "FACEBOOK")
        self.assertEqual(fb["id"], "page_1")
        self.assertEqual(fb["access_token"], "page_token_1")
        
        ig = next(a for a in accounts if a["platform"] == "INSTAGRAM")
        self.assertEqual(ig["id"], "ig_1")
        self.assertEqual(ig["username"], "my_ig")
        self.assertEqual(ig["access_token"], "page_token_1") # IG uses page token

    # ── 5. Facebook Publishing ───────────────────────────────────────────────

    @patch('apps.social_accounts.integrations.meta.facebook.requests.post')
    def test_facebook_publish_text(self, mock_post):
        mock_res = MagicMock()
        mock_res.ok = True
        mock_res.json.return_value = {"id": "post_123"}
        mock_post.return_value = mock_res
        
        res = self.fb_adapter.publish_text("token", "page_1", "Hello FB")
        self.assertEqual(res["id"], "post_123")

    @patch('apps.social_accounts.integrations.meta.facebook.requests.post')
    def test_facebook_publish_image_via_url(self, mock_post):
        mock_res = MagicMock()
        mock_res.ok = True
        mock_res.json.return_value = {"post_id": "post_456"}
        mock_post.return_value = mock_res
        
        res = self.fb_adapter.publish_image("token", "page_1", "Look", image_url="http://img.jpg")
        self.assertEqual(res["id"], "post_456")
        mock_post.assert_called_once()
        self.assertIn("url", mock_post.call_args[1]["data"])

    # ── 6. Instagram Publishing ──────────────────────────────────────────────

    def test_instagram_publish_text_fails(self):
        with self.assertRaises(MetaPublishingError):
            self.ig_adapter.publish_text("token", "ig_1", "Hello IG")

    @patch('apps.social_accounts.integrations.meta.instagram.requests.post')
    @patch('apps.social_accounts.integrations.meta.instagram.time.sleep')
    def test_instagram_publish_image(self, mock_sleep, mock_post):
        # Step 1: Media container
        mock_container = MagicMock()
        mock_container.ok = True
        mock_container.json.return_value = {"id": "container_123"}
        
        # Step 2: Publish container
        mock_publish = MagicMock()
        mock_publish.ok = True
        mock_publish.json.return_value = {"id": "ig_post_123"}
        
        mock_post.side_effect = [mock_container, mock_publish]
        
        res = self.ig_adapter.publish_image("token", "ig_1", "Cool pic", image_url="http://img.jpg")
        
        self.assertEqual(res["id"], "ig_post_123")
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once()

    # ── 7. Meta Error Handling ───────────────────────────────────────────────

    @patch('apps.social_accounts.integrations.meta.facebook.requests.get')
    def test_meta_auth_error(self, mock_get):
        mock_res = MagicMock()
        mock_res.ok = False
        mock_res.json.return_value = {"error": {"code": 190, "message": "Invalid token"}}
        mock_get.return_value = mock_res
        
        with self.assertRaises(MetaAuthenticationError):
            self.fb_adapter.get_account_info("bad_token")

    @patch('apps.social_accounts.integrations.meta.facebook.requests.get')
    def test_meta_permission_error(self, mock_get):
        mock_res = MagicMock()
        mock_res.ok = False
        mock_res.json.return_value = {"error": {"code": 200, "message": "Permission denied"}}
        mock_get.return_value = mock_res
        
        with self.assertRaises(MetaPermissionError):
            self.fb_adapter.get_account_info("token")

    @patch('apps.social_accounts.integrations.meta.facebook.requests.get')
    def test_meta_rate_limit_error(self, mock_get):
        mock_res = MagicMock()
        mock_res.ok = False
        mock_res.json.return_value = {"error": {"code": 4, "message": "Too many requests"}}
        mock_get.return_value = mock_res
        
        with self.assertRaises(MetaRateLimitError):
            self.fb_adapter.get_account_info("token")
