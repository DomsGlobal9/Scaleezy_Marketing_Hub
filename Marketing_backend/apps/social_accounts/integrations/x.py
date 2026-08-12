import os
import base64
import hashlib
import requests
from django.conf import settings
from django.core.cache import cache
from urllib.parse import urlencode, quote
import uuid

class XAdapter:
    OAUTH_URL = "https://twitter.com/i/oauth2/authorize"
    TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
    API_BASE = "https://api.twitter.com/2"
    UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"

    def __init__(self):
        self.client_id = os.environ.get('X_CLIENT_ID')
        self.client_secret = os.environ.get('X_CLIENT_SECRET')
        self.redirect_uri = os.environ.get('X_OAUTH_REDIRECT_URI')
        # Hardcoding the scopes per the plan
        self.scopes = "tweet.read tweet.write users.read offline.access"
    
    def _generate_pkce(self):
        code_verifier = base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8').rstrip('=')
        m = hashlib.sha256()
        m.update(code_verifier.encode('utf-8'))
        code_challenge = base64.urlsafe_b64encode(m.digest()).decode('utf-8').rstrip('=')
        return code_verifier, code_challenge

    def get_authorization_url(self, workspace_id: str):
        if not self.client_id:
            raise Exception("NOT_CONFIGURED")
            
        code_verifier, code_challenge = self._generate_pkce()
        state = str(uuid.uuid4())
        
        # Cache the verifier with the state as the key for 10 minutes
        cache.set(f"x_pkce_{state}", code_verifier, timeout=600)
        cache.set(f"x_workspace_{state}", workspace_id, timeout=600)

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256"
        }
        
        return f"{self.OAUTH_URL}?{urlencode(params, quote_via=quote)}"

    def exchange_code_for_token(self, code: str, state: str):
        code_verifier = cache.get(f"x_pkce_{state}")
        workspace_id = cache.get(f"x_workspace_{state}")
        
        if not code_verifier:
            raise Exception("Invalid or expired OAuth state")

        # Clean up cache
        cache.delete(f"x_pkce_{state}")
        cache.delete(f"x_workspace_{state}")

        data = {
            "code": code,
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
        }
        
        # X OAuth2 requires Basic Auth with Client ID and Secret
        auth = (self.client_id, self.client_secret)
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        response = requests.post(self.TOKEN_URL, data=data, auth=auth, headers=headers)
        if not response.ok:
            raise Exception(f"Failed to exchange token: {response.text}")
            
        token_data = response.json()
        return {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "expires_in": token_data.get("expires_in"),
            "workspace_id": workspace_id,
            "scopes": token_data.get("scope")
        }

    def refresh_token(self, refresh_token: str):
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
        }
        auth = (self.client_id, self.client_secret)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = requests.post(self.TOKEN_URL, data=data, auth=auth, headers=headers)
        if not response.ok:
            raise Exception("REAUTHORIZATION_REQUIRED")
            
        return response.json()

    def get_account_info(self, access_token: str):
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"user.fields": "profile_image_url,name,username"}
        response = requests.get(f"{self.API_BASE}/users/me", headers=headers, params=params)
        
        if not response.ok:
            raise Exception(f"Failed to get user info: {response.text}")
            
        data = response.json().get("data", {})
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "username": data.get("username"),
            "profile_image_url": data.get("profile_image_url")
        }

    def upload_media(self, access_token: str, media_url: str):
        # We need to download the image from the URL first, then upload it to X
        import tempfile
        
        # Download image
        img_response = requests.get(media_url)
        if not img_response.ok:
            raise Exception("Failed to fetch media from URL")

        # X media upload v1.1 requires OAuth 1.0a OR OAuth 2.0 User Context?
        # Actually, X allows OAuth 2.0 for media upload on v1.1 endpoint now.
        headers = {"Authorization": f"Bearer {access_token}"}
        
        files = {
            'media': ('poster.jpg', img_response.content, 'image/jpeg')
        }
        
        response = requests.post(self.UPLOAD_URL, headers=headers, files=files)
        if not response.ok:
            raise Exception(f"Media upload failed: {response.text}")
            
        return response.json().get("media_id_string")

    def publish_post(self, access_token: str, text: str, media_id: str = None):
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {"text": text}
        if media_id:
            payload["media"] = {"media_ids": [media_id]}
            
        response = requests.post(f"{self.API_BASE}/tweets", headers=headers, json=payload)
        
        if not response.ok:
            raise Exception(f"Publish failed: {response.text}")
            
        data = response.json().get("data", {})
        post_id = data.get("id")
        # Construct the URL manually since v2 doesn't always return it
        return {
            "id": post_id,
            "url": f"https://twitter.com/user/status/{post_id}"
        }
