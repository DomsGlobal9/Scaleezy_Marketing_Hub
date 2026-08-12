from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple

class SocialPlatformAdapter(ABC):
    """
    Base interface for all social platform adapters.
    """
    
    @abstractmethod
    def get_authorization_url(self, workspace_id: str) -> str:
        """Returns the OAuth authorization URL for the platform."""
        pass

    @abstractmethod
    def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchanges an authorization code for an access token."""
        pass
        
    @abstractmethod
    def get_account_info(self, access_token: str) -> Dict[str, Any]:
        """Fetches account details using the access token."""
        pass
        
    @abstractmethod
    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refreshes the access token."""
        pass
        
    @abstractmethod
    def validate_permissions(self, access_token: str) -> bool:
        """Validates if the token still has the required permissions."""
        pass
        
    @abstractmethod
    def publish(self, access_token: str, content: Dict[str, Any]) -> Dict[str, Any]:
        """Publishes content to the platform."""
        pass
        
    @abstractmethod
    def get_publish_status(self, access_token: str, post_id: str) -> Dict[str, Any]:
        """Gets the status of a published post."""
        pass

    @abstractmethod
    def disconnect(self, access_token: str) -> bool:
        """Disconnects or revokes the token from the platform."""
        pass
