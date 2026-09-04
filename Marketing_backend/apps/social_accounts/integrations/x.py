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

        response = requests.post(self.TOKEN_URL, data=data, auth=auth, headers=headers, timeout=15)
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

        response = requests.post(self.TOKEN_URL, data=data, auth=auth, headers=headers, timeout=15)
        if not response.ok:
            raise Exception("REAUTHORIZATION_REQUIRED")
            
        return response.json()

    def get_account_info(self, access_token: str):
        from .exceptions import SocialPlatformError
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"user.fields": "profile_image_url,name,username"}
        response = requests.get(f"{self.API_BASE}/users/me", headers=headers, params=params, timeout=15)
        
        if not response.ok:
            code = 'X_AUTH_FAILED' if response.status_code == 401 else 'X_PERMISSION_DENIED' if response.status_code == 403 else 'X_API_ERROR'
            raise SocialPlatformError(
                f'X account lookup returned HTTP {response.status_code}',
                safe_message='X could not verify this account. Check access or retry later.',
                error_code=code,
            )
            
        data = response.json().get("data", {})
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "username": data.get("username"),
            "profile_image_url": data.get("profile_image_url")
        }

    def upload_media(self, access_token: str, media_url: str):
        # Preserve the current URL-in-text fallback. No media bytes are uploaded
        # by this path, so fetching this URL would be both unused work and SSRF.
        return f"url:{media_url}"

    def publish_post(self, access_token: str, text: str, media_id: str = None):
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {"text": text}
        if media_id:
            if media_id.startswith("url:"):
                # Append the image URL to the tweet text
                url = media_id.split("url:")[1]
                payload["text"] = f"{text}\n\n{url}"
            else:
                payload["media"] = {"media_ids": [media_id]}
            
        response = requests.post(f"{self.API_BASE}/tweets", headers=headers, json=payload, timeout=15)
        
        if not response.ok:
            raise Exception(f"Publish failed: {response.text}")
            
        data = response.json().get("data", {})
        post_id = data.get("id")
        # Construct the URL manually since v2 doesn't always return it
        return {
            "id": post_id,
            "url": f"https://twitter.com/user/status/{post_id}"
        }

    def fetch_mentions(self, access_token: str, user_id: str, *, cursor: str = ''):
        """Return a bounded, normalized mention page for the engagement inbox."""
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {
            'max_results': 50,
            'tweet.fields': 'author_id,created_at,conversation_id,text',
            'expansions': 'author_id',
            'user.fields': 'name,username',
        }
        if cursor:
            params['pagination_token'] = cursor
        response = requests.get(
            f"{self.API_BASE}/users/{user_id}/mentions",
            headers=headers,
            params=params,
            timeout=15,
        )
        if not response.ok:
            raise Exception(f"Could not sync X mentions ({response.status_code}).")
        payload = response.json()
        users = {
            str(row.get('id')): row
            for row in payload.get('includes', {}).get('users', [])
            if isinstance(row, dict)
        }
        items = []
        for row in payload.get('data', []):
            if not isinstance(row, dict) or not row.get('id') or not row.get('text'):
                continue
            author = users.get(str(row.get('author_id')), {})
            username = str(author.get('username') or '')
            items.append({
                'external_id': str(row['id']),
                'thread_id': str(row.get('conversation_id') or row['id']),
                'kind': 'MENTION',
                'author_name': str(author.get('name') or username),
                'author_handle': username,
                'body': str(row['text']),
                'source_url': f"https://x.com/{username or 'i'}/status/{row['id']}",
                'occurred_at': row.get('created_at'),
                'source_payload': {'author_id': row.get('author_id')},
            })
        return {
            'items': items,
            'cursor': str(payload.get('meta', {}).get('next_token') or ''),
        }

    def reply_to_post(self, access_token: str, external_id: str, text: str):
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            f"{self.API_BASE}/tweets",
            headers=headers,
            json={'text': text, 'reply': {'in_reply_to_tweet_id': external_id}},
            timeout=15,
        )
        if not response.ok:
            raise Exception(f"X reply failed ({response.status_code}).")
        row = response.json().get('data', {})
        reply_id = str(row.get('id') or '')
        if not reply_id:
            raise Exception('X did not confirm the reply.')
        return {'id': reply_id, 'url': f'https://x.com/i/status/{reply_id}'}

    def fetch_post_metrics(self, access_token: str, post_ids):
        """Fetch public metrics for at most 100 posts in one X API request."""
        ids = [str(value) for value in post_ids if value][:100]
        if not ids:
            return []
        response = requests.get(
            f"{self.API_BASE}/tweets",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"ids": ",".join(ids), "tweet.fields": "public_metrics,created_at"},
            timeout=15,
        )
        if not response.ok:
            raise Exception(f"Could not sync X post metrics ({response.status_code}).")
        rows = []
        for post in response.json().get('data', []):
            metrics = post.get('public_metrics') or {}
            rows.append({
                'external_post_id': str(post.get('id') or ''),
                'impressions': int(metrics.get('impression_count') or 0),
                'reach': int(metrics.get('impression_count') or 0),
                'engagement': sum(int(metrics.get(key) or 0) for key in (
                    'like_count', 'reply_count', 'retweet_count', 'quote_count',
                    'bookmark_count',
                )),
                'clicks': 0,
                'conversions': 0,
                'observed_at': post.get('created_at'),
                'source_payload': {'public_metrics': metrics},
            })
        return rows
