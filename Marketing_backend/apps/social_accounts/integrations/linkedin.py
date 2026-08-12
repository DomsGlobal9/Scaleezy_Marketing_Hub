from django.conf import settings
from typing import Dict, Any
from .base import SocialPlatformAdapter

class LinkedInAdapter(SocialPlatformAdapter):
    """
    Adapter for LinkedIn API.
    """
    
    def get_authorization_url(self, workspace_id: str) -> str:
        client_id = settings.LINKEDIN_CLIENT_ID
        redirect_uri = settings.LINKEDIN_REDIRECT_URI
        scopes = "w_organization_social,r_organization_social,rw_organization_admin"
        state = f"workspace_id={workspace_id}"
        
        return f"https://www.linkedin.com/oauth/v2/authorization?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}&state={state}&scope={scopes}"

    def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        if not settings.LINKEDIN_CLIENT_ID:
            raise Exception("NOT_CONFIGURED")
            
        return {
            "access_token": "mock_linkedin_access_token",
            "expires_in": 5183999
        }
        
    def get_account_info(self, access_token: str) -> Dict[str, Any]:
        if not settings.LINKEDIN_CLIENT_ID:
            raise Exception("NOT_CONFIGURED")
            
        return {
            "id": "urn:li:organization:12345",
            "name": "Mock LinkedIn Page",
            "picture": {"data": {"url": "https://mock.url/linkedin.jpg"}}
        }
        
    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        return {"access_token": "mock_linkedin_access_token"}
        
    def validate_permissions(self, access_token: str) -> bool:
        return True
        
    def publish(self, access_token: str, content: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": "urn:li:share:12345"}
        
    def get_publish_status(self, access_token: str, post_id: str) -> Dict[str, Any]:
        return {"status": "PUBLISHED"}

    def disconnect(self, access_token: str) -> bool:
        return True
