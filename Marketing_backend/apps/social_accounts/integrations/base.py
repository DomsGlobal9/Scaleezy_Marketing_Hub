from abc import ABC, abstractmethod
from typing import Dict, Any, List


class SocialPlatformAdapter(ABC):
    """
    Base interface for all social platform adapters.

    Every platform (LinkedIn, X, Facebook, Instagram, …) implements this
    interface so the connect/publish/disconnect flow is platform-agnostic.
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

    # ── Extended methods (optional override) ─────────────────────────────────

    def get_publishable_destinations(self, access_token: str, account_id: str) -> List[Dict[str, Any]]:
        """
        Returns a list of publishing destinations for this account.
        Default implementation returns a single destination using the account_id.
        Platforms with multiple destinations (e.g., LinkedIn personal + org pages)
        should override this.
        """
        return [{"type": "default", "id": account_id, "name": "Default"}]

    def publish_text(self, access_token: str, author_urn: str, text: str) -> Dict[str, Any]:
        """
        Publish a text-only post.
        Default delegates to publish() — platforms can override for native support.
        """
        return self.publish(access_token, {"text": text, "author_urn": author_urn})

    def publish_image(self, access_token: str, author_urn: str, text: str,
                      image_data: bytes = None, filename: str = "image.jpg", image_url: str = None) -> Dict[str, Any]:
        """
        Publish an image post.
        Provides both raw image_data (bytes) and a public image_url (if available).
        Default delegates to publish() — platforms can override for native support.
        """
        return self.publish(access_token, {
            "text": text,
            "author_urn": author_urn,
            "image_data": image_data,
            "filename": filename,
            "image_url": image_url,
        })
