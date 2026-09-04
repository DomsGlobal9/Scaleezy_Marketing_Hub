"""
LinkedIn API adapter — production implementation.

Uses the LinkedIn REST API (versioned) for OAuth, profile retrieval,
and content publishing (text + image posts).

All API version strings and headers are centralised in this module.
"""

import logging
import uuid

import requests
from django.conf import settings
from django.core.cache import cache
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode

from .base import SocialPlatformAdapter
from .exceptions import (
    LinkedInAPIError,
    LinkedInAuthenticationError,
    LinkedInConfigurationError,
    LinkedInMediaUploadError,
    LinkedInOAuthError,
    LinkedInPermissionError,
    LinkedInPublishingError,
    LinkedInRateLimitError,
    LinkedInStateValidationError,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

OAUTH_AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
OAUTH_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
REST_API_BASE = "https://api.linkedin.com/rest"

# Cache key prefixes — same pattern as XAdapter
_STATE_PREFIX = "linkedin_state_"
_WORKSPACE_PREFIX = "linkedin_ws_"
_STATE_TTL = 600  # 10 minutes


class LinkedInAdapter(SocialPlatformAdapter):
    """
    Production adapter for LinkedIn's REST API.

    Supports:
    - OAuth 2.0 Authorization Code flow
    - Member profile retrieval (OpenID Connect userinfo)
    - Text post publishing
    - Image post publishing (initialize upload → PUT bytes → create post)
    """

    def __init__(self):
        self.client_id = getattr(settings, 'LINKEDIN_CLIENT_ID', '') or ''
        self.client_secret = getattr(settings, 'LINKEDIN_CLIENT_SECRET', '') or ''
        self.redirect_uri = getattr(settings, 'LINKEDIN_REDIRECT_URI', '') or ''
        self.api_version = getattr(settings, 'LINKEDIN_API_VERSION', '202408')
        self.scopes = getattr(settings, 'LINKEDIN_SCOPES', 'openid profile email w_member_social')

    def _ensure_configured(self):
        if not self.client_id or not self.client_secret:
            raise LinkedInConfigurationError()

    def _rest_headers(self, access_token: str) -> Dict[str, str]:
        """Standard headers for LinkedIn REST API calls."""
        if not (access_token or '').strip():
            raise LinkedInAuthenticationError(
                "A LinkedIn access token is required before publishing or reading account data."
            )
        return {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": self.api_version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    def _handle_api_error(self, response: requests.Response, context: str = "API call"):
        """Convert LinkedIn HTTP errors to typed exceptions."""
        status = response.status_code
        try:
            body = response.json()
            msg = body.get("message", body.get("error_description", response.text[:200]))
        except Exception:
            msg = response.text[:200]

        log_msg = f"LinkedIn {context} failed — HTTP {status}: {msg}"

        if status == 401:
            logger.warning(log_msg)
            raise LinkedInAuthenticationError(log_msg)
        elif status == 403:
            logger.warning(log_msg)
            raise LinkedInPermissionError(log_msg)
        elif status == 429:
            logger.warning(log_msg)
            raise LinkedInRateLimitError(log_msg)
        else:
            logger.error(log_msg)
            raise LinkedInAPIError(log_msg, status_code=status)

    # ── OAuth ────────────────────────────────────────────────────────────────

    def get_authorization_url(self, workspace_id: str) -> str:
        """Build the LinkedIn OAuth authorization URL with a secure random state."""
        self._ensure_configured()

        state = str(uuid.uuid4())

        # Store state → workspace_id mapping in Django cache
        cache.set(f"{_STATE_PREFIX}{state}", state, timeout=_STATE_TTL)
        cache.set(f"{_WORKSPACE_PREFIX}{state}", workspace_id, timeout=_STATE_TTL)

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
            "state": state,
        }

        url = f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
        logger.info("LinkedIn OAuth started for workspace (state generated)")
        return url

    def validate_state(self, state: str) -> str:
        """
        Validate the OAuth state and return the workspace_id.
        Deletes the cached values after validation (one-time use).
        """
        cached_state = cache.get(f"{_STATE_PREFIX}{state}")
        workspace_id = cache.get(f"{_WORKSPACE_PREFIX}{state}")

        if not cached_state or cached_state != state:
            logger.warning("LinkedIn OAuth state validation failed")
            raise LinkedInStateValidationError()

        # Clean up — one-time use
        cache.delete(f"{_STATE_PREFIX}{state}")
        cache.delete(f"{_WORKSPACE_PREFIX}{state}")

        return workspace_id

    def exchange_code_for_token(self, code: str, redirect_uri: str = None) -> Dict[str, Any]:
        """Exchange an authorization code for an access token."""
        self._ensure_configured()

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri or self.redirect_uri,
        }

        logger.info("LinkedIn token exchange started")

        try:
            response = requests.post(
                OAUTH_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
        except requests.RequestException as e:
            logger.error(f"LinkedIn token exchange network error: {type(e).__name__}")
            raise LinkedInAPIError(
                f"Network error during token exchange: {e}",
                safe_message="Could not connect to LinkedIn. Please try again.",
            )

        if not response.ok:
            try:
                err_body = response.json()
                err_desc = err_body.get("error_description", "Unknown error")
                err_code = err_body.get("error", "")
            except Exception:
                err_desc = response.text[:200]
                err_code = ""

            logger.error(f"LinkedIn token exchange failed — HTTP {response.status_code}: {err_desc}")
            raise LinkedInOAuthError(
                f"Token exchange failed: {err_desc}",
                oauth_error=err_code,
            )

        token_data = response.json()
        logger.info("LinkedIn token exchange succeeded")

        return {
            "access_token": token_data.get("access_token"),
            "expires_in": token_data.get("expires_in"),  # seconds — typically 5184000 (60 days)
            "refresh_token": token_data.get("refresh_token"),
            "refresh_token_expires_in": token_data.get("refresh_token_expires_in"),
            "scopes": token_data.get("scope", self.scopes),
        }

    # ── Account Info ─────────────────────────────────────────────────────────

    def get_account_info(self, access_token: str) -> Dict[str, Any]:
        """
        Retrieve the authenticated member's profile using OpenID Connect userinfo.
        Returns normalised {id, name, username, email, profile_image_url}.
        """
        try:
            response = requests.get(
                USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
        except requests.RequestException as e:
            logger.error(f"LinkedIn userinfo network error: {type(e).__name__}")
            raise LinkedInAPIError(
                f"Network error fetching LinkedIn profile: {e}",
                safe_message="Could not retrieve your LinkedIn profile. Please try again.",
            )

        if not response.ok:
            self._handle_api_error(response, "userinfo")

        data = response.json()
        logger.info("LinkedIn account info retrieved successfully")

        # The `sub` field is the member identifier — e.g. "abc123XYZ"
        member_sub = data.get("sub", "")

        return {
            "id": member_sub,
            "name": data.get("name", "LinkedIn User"),
            "email": data.get("email"),
            "username": data.get("email", ""),
            "profile_image_url": data.get("picture"),
        }

    # ── Publishing Destinations ──────────────────────────────────────────────

    def get_publishable_destinations(self, access_token: str, member_sub: str) -> List[Dict[str, Any]]:
        """
        Return a list of destinations the user can publish to.
        Always includes the member's personal profile.
        Organization pages are included if the user has admin access and the
        required scopes are granted.
        """
        destinations = []

        # Personal profile is always available with w_member_social
        destinations.append({
            "type": "member",
            "urn": f"urn:li:person:{member_sub}",
            "name": "Personal Profile",
            "id": member_sub,
        })

        # Attempt to fetch organization pages (requires Community Management API product)
        try:
            org_destinations = self._get_organization_destinations(access_token)
            destinations.extend(org_destinations)
        except (LinkedInPermissionError, LinkedInAuthenticationError):
            # Organization scopes not granted — personal profile only
            logger.info("Organization scopes not available — personal profile publishing only")
        except LinkedInAPIError:
            logger.info("Could not fetch organization pages — personal profile publishing only")

        return destinations

    def _get_organization_destinations(self, access_token: str) -> List[Dict[str, Any]]:
        """Fetch organizations the authenticated user can post to."""
        headers = self._rest_headers(access_token)

        try:
            response = requests.get(
                f"{REST_API_BASE}/organizationAcls",
                headers=headers,
                params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
                timeout=15,
            )
        except requests.RequestException as e:
            raise LinkedInAPIError(f"Network error fetching organizations: {e}")

        if not response.ok:
            self._handle_api_error(response, "organizationAcls")

        data = response.json()
        elements = data.get("elements", [])
        destinations = []

        for acl in elements:
            org_urn = acl.get("organization")
            if org_urn:
                # Extract org ID from URN
                org_id = org_urn.split(":")[-1]
                # Fetch organization details
                try:
                    org_info = self._get_organization_info(access_token, org_id)
                    destinations.append({
                        "type": "organization",
                        "urn": f"urn:li:organization:{org_id}",
                        "name": org_info.get("name", f"Organization {org_id}"),
                        "id": org_id,
                        "logo_url": org_info.get("logo_url"),
                    })
                except LinkedInAPIError:
                    logger.warning(f"Could not fetch organization details for {org_id}")

        return destinations

    def _get_organization_info(self, access_token: str, org_id: str) -> Dict[str, Any]:
        """Fetch basic organization info."""
        headers = self._rest_headers(access_token)

        response = requests.get(
            f"{REST_API_BASE}/organizations/{org_id}",
            headers=headers,
            timeout=15,
        )

        if not response.ok:
            self._handle_api_error(response, "organization info")

        data = response.json()
        return {
            "name": data.get("localizedName", f"Organization {org_id}"),
            "logo_url": data.get("logoV2", {}).get("original~", {}).get("elements", [{}])[0].get("identifiers", [{}])[0].get("identifier"),
        }

    # ── Publishing ───────────────────────────────────────────────────────────

    def publish_text(self, access_token: str, author_urn: str, text: str) -> Dict[str, Any]:
        """Publish a text-only post to LinkedIn."""
        headers = self._rest_headers(access_token)

        payload = {
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
        }

        logger.info(f"LinkedIn text post publishing started for author {author_urn}")

        try:
            response = requests.post(
                f"{REST_API_BASE}/posts",
                headers=headers,
                json=payload,
                timeout=30,
            )
        except requests.RequestException as e:
            logger.error(f"LinkedIn publish network error: {type(e).__name__}")
            raise LinkedInPublishingError(f"Network error during publishing: {e}")

        if not response.ok:
            self._handle_api_error(response, "text post publish")

        # LinkedIn returns the post URN in the x-restli-id header
        post_urn = response.headers.get("x-restli-id", "")
        post_id = post_urn.split(":")[-1] if ":" in post_urn else post_urn

        logger.info(f"LinkedIn text post published successfully: {post_urn}")

        return {
            "id": post_urn or post_id,
            "url": f"https://www.linkedin.com/feed/update/{post_urn}" if post_urn else None,
        }

    def publish_image(self, access_token: str, author_urn: str, text: str,
                      image_data: bytes, filename: str = "poster.jpg") -> Dict[str, Any]:
        """
        Publish an image post to LinkedIn.

        LinkedIn's image posting flow:
        1. Initialize upload → get upload URL + image URN
        2. PUT raw bytes to the upload URL
        3. Create post referencing the image URN
        """
        # Step 1: Initialize upload
        image_urn, upload_url = self._initialize_image_upload(access_token, author_urn)

        # Step 2: Upload the image bytes
        self._upload_image_bytes(upload_url, image_data, access_token)

        # Step 3: Create the post with the image
        return self._create_image_post(access_token, author_urn, text, image_urn)

    def _initialize_image_upload(self, access_token: str, owner_urn: str) -> tuple:
        """Step 1: Register an image upload with LinkedIn."""
        headers = self._rest_headers(access_token)

        payload = {
            "initializeUploadRequest": {
                "owner": owner_urn,
            }
        }

        logger.info("LinkedIn image upload initialization started")

        try:
            response = requests.post(
                f"{REST_API_BASE}/images?action=initializeUpload",
                headers=headers,
                json=payload,
                timeout=30,
            )
        except requests.RequestException as e:
            logger.error(f"LinkedIn image init network error: {type(e).__name__}")
            raise LinkedInMediaUploadError(f"Network error initializing image upload: {e}")

        if not response.ok:
            self._handle_api_error(response, "image upload initialization")

        data = response.json()
        value = data.get("value", {})
        upload_url = value.get("uploadUrl")
        image_urn = value.get("image")

        if not upload_url or not image_urn:
            raise LinkedInMediaUploadError(
                "LinkedIn returned incomplete upload initialization response"
            )

        logger.info(f"LinkedIn image upload initialized: {image_urn}")
        return image_urn, upload_url

    def _upload_image_bytes(self, upload_url: str, image_data: bytes, access_token: str):
        """Step 2: Upload raw image bytes to LinkedIn's upload URL."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/octet-stream",
        }

        logger.info("LinkedIn image bytes upload started")

        try:
            response = requests.put(
                upload_url,
                data=image_data,
                headers=headers,
                timeout=120,  # Large images can take time
            )
        except requests.RequestException as e:
            logger.error(f"LinkedIn image upload network error: {type(e).__name__}")
            raise LinkedInMediaUploadError(f"Network error uploading image: {e}")

        if not response.ok:
            logger.error(f"LinkedIn image upload failed — HTTP {response.status_code}")
            raise LinkedInMediaUploadError(
                f"Image upload failed with status {response.status_code}"
            )

        logger.info("LinkedIn image bytes uploaded successfully")

    def _create_image_post(self, access_token: str, author_urn: str,
                           text: str, image_urn: str) -> Dict[str, Any]:
        """Step 3: Create a post with the uploaded image."""
        headers = self._rest_headers(access_token)

        payload = {
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "content": {
                "media": {
                    "title": "Marketing Content",
                    "id": image_urn,
                }
            },
            "lifecycleState": "PUBLISHED",
        }

        logger.info(f"LinkedIn image post creation started for {author_urn}")

        try:
            response = requests.post(
                f"{REST_API_BASE}/posts",
                headers=headers,
                json=payload,
                timeout=30,
            )
        except requests.RequestException as e:
            logger.error(f"LinkedIn image post network error: {type(e).__name__}")
            raise LinkedInPublishingError(f"Network error creating image post: {e}")

        if not response.ok:
            self._handle_api_error(response, "image post creation")

        post_urn = response.headers.get("x-restli-id", "")
        post_id = post_urn.split(":")[-1] if ":" in post_urn else post_urn

        logger.info(f"LinkedIn image post published successfully: {post_urn}")

        return {
            "id": post_urn or post_id,
            "url": f"https://www.linkedin.com/feed/update/{post_urn}" if post_urn else None,
        }

    # ── Generic adapter interface methods ────────────────────────────────────

    def publish(self, access_token: str, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generic publish method (required by base class).
        Delegates to publish_text or publish_image based on content.
        """
        author_urn = content.get("author_urn", "")
        text = content.get("text", "")
        image_data = content.get("image_data")

        if image_data:
            return self.publish_image(access_token, author_urn, text, image_data)
        else:
            return self.publish_text(access_token, author_urn, text)

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh an expired LinkedIn access token."""
        self._ensure_configured()

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        try:
            response = requests.post(
                OAUTH_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
        except requests.RequestException as e:
            raise LinkedInAuthenticationError(f"Network error refreshing token: {e}")

        if not response.ok:
            raise LinkedInAuthenticationError("LinkedIn token refresh failed")

        token_data = response.json()
        logger.info("LinkedIn token refreshed successfully")

        return {
            "access_token": token_data.get("access_token"),
            "expires_in": token_data.get("expires_in"),
            "refresh_token": token_data.get("refresh_token"),
        }

    def validate_permissions(self, access_token: str) -> bool:
        """Validate the token by attempting to fetch userinfo."""
        try:
            self.get_account_info(access_token)
            return True
        except LinkedInAPIError:
            return False

    def get_publish_status(self, access_token: str, post_id: str) -> Dict[str, Any]:
        """Get the status of a published post."""
        headers = self._rest_headers(access_token)

        try:
            response = requests.get(
                f"{REST_API_BASE}/posts/{post_id}",
                headers=headers,
                timeout=15,
            )
        except requests.RequestException:
            return {"status": "UNKNOWN"}

        if not response.ok:
            return {"status": "UNKNOWN"}

        data = response.json()
        return {
            "status": data.get("lifecycleState", "UNKNOWN"),
            "id": post_id,
        }

    def disconnect(self, access_token: str) -> bool:
        """
        Disconnect / revoke the LinkedIn token.
        LinkedIn does not provide a standard token revocation endpoint,
        so remote revocation cannot be confirmed. The caller still clears local credentials.
        """
        logger.info("LinkedIn disconnect — credentials will be cleared from database")
        return False
