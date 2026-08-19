import logging
import requests
import uuid
from typing import Dict, Any, List
from django.conf import settings
from django.core.cache import cache

from ..base import SocialPlatformAdapter
from .exceptions import (
    MetaAuthenticationError,
    MetaConfigurationError,
    MetaOAuthError,
    MetaPermissionError,
    MetaRateLimitError,
    MetaStateValidationError,
    MetaPublishingError,
)

logger = logging.getLogger(__name__)


class FacebookAdapter(SocialPlatformAdapter):
    """
    Unified adapter for Meta (Facebook Pages & Instagram Professional).
    Handles OAuth, account fetching, and Facebook Page publishing.
    """

    def _ensure_configured(self):
        if not settings.META_CLIENT_ID or not settings.META_CLIENT_SECRET:
            raise MetaConfigurationError()

    def get_authorization_url(self, workspace_id: str) -> str:
        self._ensure_configured()
        
        # Generate secure state
        state = str(uuid.uuid4())
        
        # Cache state for 15 minutes mapped to workspace
        cache.set(f"meta_state_{state}", state, timeout=900)
        cache.set(f"meta_ws_{state}", workspace_id, timeout=900)
        
        scopes = settings.META_SCOPES
        
        url = (
            f"https://www.facebook.com/{settings.META_API_VERSION}/dialog/oauth"
            f"?client_id={settings.META_CLIENT_ID}"
            f"&redirect_uri={settings.META_REDIRECT_URI}"
            f"&state={state}"
            f"&scope={scopes}"
        )
        return url

    def validate_state(self, state: str) -> str:
        """Validates the OAuth state and returns the workspace_id."""
        cached_state = cache.get(f"meta_state_{state}")
        workspace_id = cache.get(f"meta_ws_{state}")
        
        if not cached_state or not workspace_id:
            raise MetaStateValidationError()
            
        # One-time use
        cache.delete(f"meta_state_{state}")
        cache.delete(f"meta_ws_{state}")
        
        return workspace_id

    def exchange_code_for_token(self, code: str, redirect_uri: str = None) -> Dict[str, Any]:
        self._ensure_configured()
        
        # 1. Exchange code for short-lived token
        token_url = f"https://graph.facebook.com/{settings.META_API_VERSION}/oauth/access_token"
        params = {
            "client_id": settings.META_CLIENT_ID,
            "redirect_uri": settings.META_REDIRECT_URI,
            "client_secret": settings.META_CLIENT_SECRET,
            "code": code
        }
        
        response = requests.get(token_url, params=params, timeout=10)
        
        if not response.ok:
            error_data = response.json().get("error", {})
            logger.error(f"Meta OAuth Error: {error_data}")
            raise MetaOAuthError(message=error_data.get("message", "Failed to exchange code for access token."))
            
        data = response.json()
        short_lived_token = data.get("access_token")
        
        # 2. Exchange short-lived token for long-lived User Access Token
        long_lived_params = {
            "grant_type": "fb_exchange_token",
            "client_id": settings.META_CLIENT_ID,
            "client_secret": settings.META_CLIENT_SECRET,
            "fb_exchange_token": short_lived_token
        }
        
        ll_response = requests.get(token_url, params=long_lived_params, timeout=10)
        if not ll_response.ok:
            logger.warning("Failed to exchange for long-lived Meta token. Falling back to short-lived token.")
            return {
                "access_token": short_lived_token,
                "expires_in": data.get("expires_in", 3600),
                "scopes": settings.META_SCOPES
            }
            
        ll_data = ll_response.json()
        return {
            "access_token": ll_data.get("access_token"),
            "expires_in": ll_data.get("expires_in", 5184000), # ~60 days
            "scopes": settings.META_SCOPES
        }

    def get_account_info(self, access_token: str) -> Dict[str, Any]:
        """
        Fetches all Facebook Pages the user manages, and their linked Instagram accounts.
        Returns a dictionary containing a list under the 'accounts' key.
        """
        url = f"https://graph.facebook.com/{settings.META_API_VERSION}/me/accounts"
        params = {
            "access_token": access_token,
            "fields": "id,name,access_token,picture,instagram_business_account"
        }
        
        response = requests.get(url, params=params, timeout=10)
        self._handle_api_errors(response)
        
        data = response.json()
        pages = data.get("data", [])
        
        accounts = []
        
        for page in pages:
            page_id = page.get("id")
            page_token = page.get("access_token")
            
            # 1. Add the Facebook Page
            accounts.append({
                "platform": "FACEBOOK",
                "id": page_id,
                "name": page.get("name"),
                "access_token": page_token, # Page Access Token
                "picture": page.get("picture", {}).get("data", {}).get("url"),
                "account_type": "organization"
            })
            
            # 2. Check for linked Instagram Professional account
            ig_account = page.get("instagram_business_account")
            if ig_account:
                ig_id = ig_account.get("id")
                # Fetch detailed IG account info
                ig_url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{ig_id}"
                ig_params = {
                    "access_token": page_token, # We query the IG node using the linked Page Access Token
                    "fields": "id,username,name,profile_picture_url"
                }
                ig_response = requests.get(ig_url, params=ig_params, timeout=10)
                if ig_response.ok:
                    ig_data = ig_response.json()
                    accounts.append({
                        "platform": "INSTAGRAM",
                        "id": ig_id,
                        "name": ig_data.get("name") or ig_data.get("username"),
                        "username": ig_data.get("username"),
                        "access_token": page_token, # IG uses the linked Page Access Token for publishing
                        "picture": ig_data.get("profile_picture_url"),
                        "account_type": "organization"
                    })
                    
        return {"accounts": accounts}

    def _handle_api_errors(self, response):
        """Maps Meta Graph API errors to custom exceptions."""
        if response.ok:
            return
            
        try:
            data = response.json()
            error = data.get("error", {})
        except Exception:
            raise MetaPublishingError("Received an invalid response from Meta Graph API.")

        code = error.get("code")
        message = error.get("message", "Unknown Meta error")
        
        # Map common Graph API error codes
        if code in (190, 102):
            raise MetaAuthenticationError(message)
        elif code in (10, 200):
            raise MetaPermissionError(message)
        elif code == 4 or code == 17:
            raise MetaRateLimitError(message)
        else:
            raise MetaPublishingError(message)

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        return {} # Meta long-lived tokens are refreshed implicitly or via client SDKs

    def validate_permissions(self, access_token: str) -> bool:
        url = f"https://graph.facebook.com/{settings.META_API_VERSION}/me/permissions"
        response = requests.get(url, params={"access_token": access_token}, timeout=10)
        return response.ok

    # --- Publishing Methods for Facebook Pages ---

    def publish_text(self, access_token: str, author_urn: str, text: str) -> Dict[str, Any]:
        """Publish text-only post to Facebook Page feed."""
        url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{author_urn}/feed"
        data = {
            "message": text,
            "access_token": access_token
        }
        response = requests.post(url, data=data, timeout=15)
        self._handle_api_errors(response)
        
        return {"id": response.json().get("id")}

    def publish_image(self, access_token: str, author_urn: str, text: str, image_data: bytes = None, filename: str = "image.jpg", image_url: str = None) -> Dict[str, Any]:
        """
        Publish image post to Facebook Page.
        Can upload via public image_url (preferred by Meta) or raw multipart bytes.
        """
        url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{author_urn}/photos"
        data = {
            "message": text,
            "access_token": access_token
        }
        
        if image_url:
            data["url"] = image_url
            response = requests.post(url, data=data, timeout=15)
        elif image_data:
            files = {"source": (filename, image_data, "image/jpeg")}
            response = requests.post(url, data=data, files=files, timeout=30)
        else:
            raise MetaPublishingError("Either image_url or image_data must be provided.")
            
        self._handle_api_errors(response)
        
        resp_data = response.json()
        return {"id": resp_data.get("post_id") or resp_data.get("id")}

    def publish(self, access_token: str, content: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def get_publish_status(self, access_token: str, post_id: str) -> Dict[str, Any]:
        return {"status": "PUBLISHED"}

    def disconnect(self, access_token: str) -> bool:
        url = f"https://graph.facebook.com/{settings.META_API_VERSION}/me/permissions"
        requests.delete(url, params={"access_token": access_token}, timeout=10)
        return True
