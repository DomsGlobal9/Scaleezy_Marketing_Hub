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
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"user.fields": "profile_image_url,name,username"}
        response = requests.get(f"{self.API_BASE}/users/me", headers=headers, params=params, timeout=15)
        
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
        
        if media_url.startswith("https://mock-storage.url"):
            # Tiny 1x1 valid JPEG for mock fallback
            img_content = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xdb\x00C\x01\t\t\t\x0c\x0b\x0c\x18\r\r\x182!\x1c!22222222222222222222222222222222222222222222222222\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01"\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xc4\x00\x1f\x01\x00\x03\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x11\x00\x02\x01\x02\x04\x04\x03\x04\x07\x05\x04\x04\x00\x01\x02\x77\x00\x01\x02\x03\x11\x04\x05!1\x06\x12AQ\x07aq\x13"2\x81\x08\x14B\x91\xa1\xb1\xc1\t#3R\xf0\x15br\xd1\n\x16$4\xe1%\xf1\x17\x18\x19\x1a&\'()*56789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xfd\xfc\xa2\x8a(\x00\x3f\xff\xd9'
        else:
            img_response = requests.get(media_url)
            if not img_response.ok:
                raise Exception("Failed to fetch media from URL")
            img_content = img_response.content

        # X API v1.1 media upload DOES NOT support OAuth 2.0 User Context (Bearer tokens)
        # It only supports OAuth 1.0a. Since we use OAuth 2.0, media upload will fail with 401.
        # As a workaround, we return the URL itself, and we will append it to the tweet text.
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
