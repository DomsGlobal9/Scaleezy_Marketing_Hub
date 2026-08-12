from django.conf import settings
from typing import Dict, Any
from ..base import SocialPlatformAdapter

class InstagramAdapter(SocialPlatformAdapter):
    """
    Adapter for Instagram Graph API.
    """
    
    def get_authorization_url(self, workspace_id: str) -> str:
        client_id = settings.META_CLIENT_ID
        redirect_uri = settings.META_REDIRECT_URI
        scopes = "instagram_basic,instagram_content_publish"
        state = f"workspace_id={workspace_id}"
        
        return f"https://www.facebook.com/v19.0/dialog/oauth?client_id={client_id}&redirect_uri={redirect_uri}&state={state}&scope={scopes}"

    def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        if not settings.META_CLIENT_ID:
            raise Exception("NOT_CONFIGURED")
            
        return {
            "access_token": "mock_ig_access_token",
            "expires_in": 5183999
        }
        
    def get_account_info(self, access_token: str) -> Dict[str, Any]:
        if not settings.META_CLIENT_ID:
            raise Exception("NOT_CONFIGURED")
            
        return {
            "id": "mock_ig_id",
            "name": "Mock Instagram",
            "username": "mock_ig",
            "picture": {"data": {"url": "https://mock.url/ig.jpg"}}
        }
        
    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        return {"access_token": "mock_ig_access_token"}
        
    def validate_permissions(self, access_token: str) -> bool:
        return True
        
    def publish(self, access_token: str, content: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": "mock_ig_post_id"}
        
    def get_publish_status(self, access_token: str, post_id: str) -> Dict[str, Any]:
        return {"status": "PUBLISHED"}

    def disconnect(self, access_token: str) -> bool:
        return True
