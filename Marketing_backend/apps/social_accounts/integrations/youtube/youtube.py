import logging
import requests
import uuid
from typing import Dict, Any, List
from django.conf import settings
from django.core.cache import cache

from ..base import SocialPlatformAdapter
from .exceptions import (
    YouTubeAuthenticationError,
    YouTubeConfigurationError,
    YouTubeOAuthError,
    YouTubePermissionError,
    YouTubeRateLimitError,
    YouTubeStateValidationError,
    YouTubePublishingError,
    YouTubeMediaUploadError,
)

logger = logging.getLogger(__name__)


class YouTubeAdapter(SocialPlatformAdapter):
    """
    Adapter for Google/YouTube Data API v3.
    Handles OAuth, channel fetching, and video publishing.
    """

    def _ensure_configured(self):
        if not settings.YOUTUBE_CLIENT_ID or not settings.YOUTUBE_CLIENT_SECRET:
            raise YouTubeConfigurationError()

    def get_authorization_url(self, workspace_id: str) -> str:
        self._ensure_configured()
        
        state = str(uuid.uuid4())
        
        # Cache state for 15 minutes mapped to workspace
        cache.set(f"yt_state_{state}", state, timeout=900)
        cache.set(f"yt_ws_{state}", workspace_id, timeout=900)
        
        scopes = settings.YOUTUBE_SCOPES
        
        # Google OAuth URL
        url = (
            f"https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={settings.YOUTUBE_CLIENT_ID}"
            f"&redirect_uri={settings.YOUTUBE_REDIRECT_URI}"
            f"&response_type=code"
            f"&scope={scopes}"
            f"&access_type=offline"
            f"&prompt=consent"
            f"&state={state}"
        )
        return url

    def validate_state(self, state: str) -> str:
        """Validates the OAuth state and returns the workspace_id."""
        cached_state = cache.get(f"yt_state_{state}")
        workspace_id = cache.get(f"yt_ws_{state}")
        
        if not cached_state or not workspace_id:
            raise YouTubeStateValidationError()
            
        cache.delete(f"yt_state_{state}")
        cache.delete(f"yt_ws_{state}")
        
        return workspace_id

    def exchange_code_for_token(self, code: str, redirect_uri: str = None) -> Dict[str, Any]:
        self._ensure_configured()
        
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": settings.YOUTUBE_CLIENT_ID,
            "client_secret": settings.YOUTUBE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri or settings.YOUTUBE_REDIRECT_URI
        }
        
        response = requests.post(token_url, data=data, timeout=10)
        
        if not response.ok:
            error_data = response.json()
            logger.error(f"YouTube OAuth Error: {error_data}")
            raise YouTubeOAuthError(message=error_data.get("error_description", "Failed to exchange code for access token."))
            
        data = response.json()
        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in", 3599),
            "scopes": settings.YOUTUBE_SCOPES
        }

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        self._ensure_configured()
        
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": settings.YOUTUBE_CLIENT_ID,
            "client_secret": settings.YOUTUBE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        
        response = requests.post(token_url, data=data, timeout=10)
        
        if not response.ok:
            raise YouTubeAuthenticationError("Failed to refresh YouTube token.")
            
        data = response.json()
        return {
            "access_token": data.get("access_token"),
            "expires_in": data.get("expires_in", 3599)
        }

    def get_account_info(self, access_token: str) -> Dict[str, Any]:
        """
        Fetches the user's YouTube Channel details.
        Requires the youtube.readonly scope.
        """
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {
            "part": "snippet",
            "mine": "true"
        }
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        self._handle_api_errors(response)
        
        data = response.json()
        items = data.get("items", [])
        
        if not items:
            raise YouTubeConfigurationError("No YouTube channel found for this Google account.")
            
        channel = items[0]
        snippet = channel.get("snippet", {})
        thumbnails = snippet.get("thumbnails", {})
        profile_image = thumbnails.get("high", {}).get("url") or thumbnails.get("default", {}).get("url")
        
        return {
            "id": channel.get("id"),
            "name": snippet.get("title", "YouTube Channel"),
            "username": snippet.get("customUrl", ""),
            "profile_image_url": profile_image,
            "account_type": "organization"
        }

    def _handle_api_errors(self, response):
        """Maps Google/YouTube API errors to custom exceptions."""
        if response.ok:
            return
            
        try:
            data = response.json()
            error = data.get("error", {})
        except Exception:
            raise YouTubePublishingError("Received an invalid response from YouTube API.")

        code = error.get("code")
        message = error.get("message", "Unknown YouTube error")
        
        if code in (401, 403):
            # Differentiate between Auth and Quota/Permissions
            if "quota" in message.lower():
                raise YouTubeRateLimitError(message)
            elif "permission" in message.lower() or "auth" in message.lower():
                raise YouTubeAuthenticationError(message)
            else:
                raise YouTubePermissionError(message)
        elif code == 429:
            raise YouTubeRateLimitError(message)
        else:
            raise YouTubePublishingError(message)

    def validate_permissions(self, access_token: str) -> bool:
        # Check tokeninfo endpoint
        url = f"https://oauth2.googleapis.com/tokeninfo?access_token={access_token}"
        response = requests.get(url, timeout=10)
        if response.ok:
            data = response.json()
            scopes = data.get("scope", "")
            return "youtube.upload" in scopes
        return False

    def publish_text(self, access_token: str, author_urn: str, text: str) -> Dict[str, Any]:
        raise YouTubePublishingError("YouTube API only supports video uploads. Text-only posts are not allowed.")

    def publish_image(self, access_token: str, author_urn: str, text: str, image_data: bytes = None, filename: str = "video.mp4", image_url: str = None) -> Dict[str, Any]:
        """
        Publish media to YouTube.
        YouTube requires video format. The `image_url` parameter actually represents a media URL.
        """
        raise YouTubeMediaUploadError("The backend must stream video data to YouTube. Use publish() with video_stream.")

    def publish_video(self, access_token: str, title: str, description: str, video_stream, content_length: int = None) -> Dict[str, Any]:
        """
        Uploads a video to YouTube using a stream (e.g. from requests.get(url, stream=True).raw).
        """
        url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=media&part=snippet,status"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "video/*",
        }
        
        # Meta info is sent as part of the query params or we could do multipart.
        # But wait, Google's media upload needs metadata.
        # The easiest way using requests without google-api-python-client is multipart upload.
        
        # Multipart/related requires specific formatting.
        # Let's use the standard json metadata followed by video bytes.
        import json
        
        metadata = {
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": "22" # People & Blogs default
            },
            "status": {
                "privacyStatus": "public" # public, unlisted, or private
            }
        }
        
        boundary = "yt_upload_boundary"
        headers["Content-Type"] = f"multipart/related; boundary={boundary}"
        
        # We need to construct the generator to stream the body without loading it entirely in memory
        def generate_body():
            yield f"--{boundary}\r\n".encode("utf-8")
            yield "Content-Type: application/json; charset=UTF-8\r\n\r\n".encode("utf-8")
            yield (json.dumps(metadata) + "\r\n").encode("utf-8")
            yield f"--{boundary}\r\n".encode("utf-8")
            yield "Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
            
            # Read from stream in chunks
            while True:
                chunk = video_stream.read(8192)
                if not chunk:
                    break
                yield chunk
                
            yield f"\r\n--{boundary}--\r\n".encode("utf-8")

        response = requests.post(url, headers=headers, data=generate_body(), timeout=300) # 5 min timeout for video upload
        
        self._handle_api_errors(response)
        
        resp_data = response.json()
        return {"id": resp_data.get("id")}


    def publish(self, access_token: str, content: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def get_publish_status(self, access_token: str, post_id: str) -> Dict[str, Any]:
        return {"status": "PUBLISHED"}

    def disconnect(self, access_token: str) -> bool:
        url = "https://oauth2.googleapis.com/revoke"
        requests.post(url, params={"token": access_token}, timeout=10)
        return True
