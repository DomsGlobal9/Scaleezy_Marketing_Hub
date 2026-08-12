from django.conf import settings
from typing import Dict, Any
from ..base import SocialPlatformAdapter

class FacebookAdapter(SocialPlatformAdapter):
    """
    Adapter for Facebook Pages API.
    """
    
    def get_authorization_url(self, workspace_id: str) -> str:
        # Generate OAuth URL for Facebook
        client_id = settings.META_CLIENT_ID
        redirect_uri = settings.META_REDIRECT_URI
        scopes = "pages_manage_posts,pages_read_engagement,pages_show_list"
        state = f"workspace_id={workspace_id}"
        
        return f"https://www.facebook.com/v19.0/dialog/oauth?client_id={client_id}&redirect_uri={redirect_uri}&state={state}&scope={scopes}"

    def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        # Implementation would call Meta Graph API
        # Returning mock for now as requested when API is not fully configured
        if not settings.META_CLIENT_ID:
            raise Exception("NOT_CONFIGURED")
            
        return {
            "access_token": "mock_fb_access_token",
            "expires_in": 5183999
        }
        
    def get_account_info(self, access_token: str) -> Dict[str, Any]:
        if not settings.META_CLIENT_ID:
            raise Exception("NOT_CONFIGURED")
            
        return {
            "id": "mock_page_id",
            "name": "Mock Facebook Page",
            "picture": {"data": {"url": "https://mock.url/picture.jpg"}}
        }
        
    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        return {"access_token": "mock_fb_access_token"}
        
    def validate_permissions(self, access_token: str) -> bool:
        return True
        
    def publish(self, access_token: str, content: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": "mock_post_id"}
        
    def get_publish_status(self, access_token: str, post_id: str) -> Dict[str, Any]:
        return {"status": "PUBLISHED"}

    def disconnect(self, access_token: str) -> bool:
        return True
