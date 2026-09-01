import uuid
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone
from django.core.cache import cache

from apps.workspaces.models import MarketingWorkspace
from apps.social_accounts.models import SocialConnection
from apps.social_accounts.integrations.youtube.youtube import YouTubeAdapter
from apps.social_accounts.integrations.youtube.exceptions import (
    YouTubeAuthenticationError,
    YouTubeConfigurationError,
    YouTubeOAuthError,
    YouTubePermissionError,
    YouTubeRateLimitError,
    YouTubeStateValidationError,
    YouTubePublishingError,
    YouTubeMediaUploadError,
)
from apps.social_accounts.utils.encryption import encrypt_token, decrypt_token


class YouTubeAdapterTests(TestCase):
    """Tests for the YouTube Data API integration."""

    def setUp(self):
        self.adapter = YouTubeAdapter()
        cache.clear()

    def tearDown(self):
        cache.clear()

    # ── 1. Configuration & URL generation ────────────────────────────────────

    @patch.object(YouTubeAdapter, '_ensure_configured')
    def test_authorization_url_generation(self, mock_configured):
        workspace_id = str(uuid.uuid4())
        url = self.adapter.get_authorization_url(workspace_id)

        self.assertIn("accounts.google.com/o/oauth2/v2/auth", url)
        self.assertIn("client_id=", url)
        self.assertIn("redirect_uri=", url)
        self.assertIn("state=", url)
        self.assertIn("scope=", url)
        self.assertIn("access_type=offline", url)
        self.assertIn("prompt=consent", url)

    def test_missing_configuration_raises_error(self):
        with patch('apps.social_accounts.integrations.youtube.youtube.settings') as mock_settings:
            mock_settings.YOUTUBE_CLIENT_ID = ''
            with self.assertRaises(YouTubeConfigurationError):
                self.adapter.get_authorization_url("test-ws")

    # ── 2. State Validation ──────────────────────────────────────────────────

    @patch.object(YouTubeAdapter, '_ensure_configured')
    def test_state_validation(self, mock_configured):
        workspace_id = "ws-123"
        url = self.adapter.get_authorization_url(workspace_id)
        
        import re
        state = re.search(r'state=([a-f0-9-]+)', url).group(1)
        
        self.assertEqual(self.adapter.validate_state(state), workspace_id)
        
        with self.assertRaises(YouTubeStateValidationError):
            self.adapter.validate_state(state)

    # ── 3. Token Exchange ────────────────────────────────────────────────────

    @patch('apps.social_accounts.integrations.youtube.youtube.requests.post')
    def test_token_exchange_success(self, mock_post):
        mock_res = MagicMock()
        mock_res.ok = True
        mock_res.json.return_value = {
            "access_token": "acc_123",
            "refresh_token": "ref_456",
            "expires_in": 3600
        }
        mock_post.return_value = mock_res
        
        with patch.object(YouTubeAdapter, '_ensure_configured'):
            result = self.adapter.exchange_code_for_token("auth_code")
            
        self.assertEqual(result["access_token"], "acc_123")
        self.assertEqual(result["refresh_token"], "ref_456")
        self.assertEqual(result["expires_in"], 3600)

    # ── 4. Account Discovery (Channel) ───────────────────────────────────────

    @patch('apps.social_accounts.integrations.youtube.youtube.requests.get')
    def test_get_account_info_success(self, mock_get):
        mock_res = MagicMock()
        mock_res.ok = True
        mock_res.json.return_value = {
            "items": [
                {
                    "id": "channel_123",
                    "snippet": {
                        "title": "My Awesome Channel",
                        "customUrl": "@mychannel",
                        "thumbnails": {
                            "high": {"url": "http://img.jpg"}
                        }
                    }
                }
            ]
        }
        mock_get.return_value = mock_res
        
        result = self.adapter.get_account_info("user_token")
        
        self.assertEqual(result["id"], "channel_123")
        self.assertEqual(result["name"], "My Awesome Channel")
        self.assertEqual(result["username"], "@mychannel")
        self.assertEqual(result["profile_image_url"], "http://img.jpg")

    def test_get_account_info_no_channel(self):
        with patch('apps.social_accounts.integrations.youtube.youtube.requests.get') as mock_get:
            mock_res = MagicMock()
            mock_res.ok = True
            mock_res.json.return_value = {"items": []}
            mock_get.return_value = mock_res
            
            with self.assertRaises(YouTubeConfigurationError):
                self.adapter.get_account_info("user_token")

    # ── 5. YouTube Publishing ────────────────────────────────────────────────

    def test_youtube_publish_text_fails(self):
        with self.assertRaises(YouTubePublishingError):
            self.adapter.publish_text("token", "channel_1", "Hello YT")

    def test_youtube_publish_image_fails(self):
        with self.assertRaises(YouTubeMediaUploadError):
            self.adapter.publish_image("token", "channel_1", "Look")

    @patch('apps.social_accounts.integrations.youtube.youtube.requests.post')
    def test_youtube_publish_video(self, mock_post):
        mock_res = MagicMock()
        mock_res.ok = True
        mock_res.json.return_value = {"id": "video_123"}
        mock_post.return_value = mock_res
        
        # Mock a file stream
        import io
        mock_stream = io.BytesIO(b"dummy video data")
        
        res = self.adapter.publish_video("token", "My Video", "Description", mock_stream, 16)
        
        self.assertEqual(res["id"], "video_123")
        mock_post.assert_called_once()
        self.assertIn("multipart/related", mock_post.call_args[1]["headers"]["Content-Type"])

    # ── 6. Error Handling ────────────────────────────────────────────────────

    def test_handle_api_errors_rate_limit(self):
        mock_res = MagicMock()
        mock_res.ok = False
        mock_res.json.return_value = {"error": {"code": 403, "message": "quota exceeded"}}
        
        with self.assertRaises(YouTubeRateLimitError):
            self.adapter._handle_api_errors(mock_res)

    def test_handle_api_errors_auth(self):
        mock_res = MagicMock()
        mock_res.ok = False
        mock_res.json.return_value = {"error": {"code": 401, "message": "Invalid Credentials"}}
        
        with self.assertRaises(YouTubeAuthenticationError):
            self.adapter._handle_api_errors(mock_res)

    @patch('apps.social_accounts.integrations.youtube.youtube.requests.get')
    def test_fetch_comments_normalizes_a_bounded_page(self, mock_get):
        mock_res = MagicMock(ok=True)
        mock_res.json.return_value = {
            'nextPageToken': 'next-page',
            'items': [{
                'id': 'thread-1',
                'snippet': {'topLevelComment': {
                    'id': 'comment-1',
                    'snippet': {
                        'textDisplay': 'Love this',
                        'authorDisplayName': 'Viewer',
                        'authorChannelUrl': 'https://youtube.com/@viewer',
                        'videoId': 'video-1',
                        'publishedAt': '2026-09-01T10:00:00Z',
                    },
                }},
            }],
        }
        mock_get.return_value = mock_res

        result = self.adapter.fetch_comments('token', 'channel-1', cursor='page-1')

        self.assertEqual(result['cursor'], 'next-page')
        self.assertEqual(result['items'][0]['external_id'], 'comment-1')
        self.assertEqual(result['items'][0]['kind'], 'COMMENT')
        self.assertEqual(mock_get.call_args.kwargs['timeout'], 15)
        self.assertEqual(mock_get.call_args.kwargs['params']['pageToken'], 'page-1')

    @patch('apps.social_accounts.integrations.youtube.youtube.requests.post')
    def test_reply_to_comment_returns_external_lineage(self, mock_post):
        mock_res = MagicMock(ok=True)
        mock_res.json.return_value = {'id': 'reply-1'}
        mock_post.return_value = mock_res

        result = self.adapter.reply_to_comment('token', 'comment-1', 'Thank you')

        self.assertEqual(result['id'], 'reply-1')
        self.assertEqual(
            mock_post.call_args.kwargs['json']['snippet']['parentId'],
            'comment-1',
        )
        self.assertEqual(mock_post.call_args.kwargs['timeout'], 15)
