import logging
import requests
import time
from typing import Dict, Any
from django.conf import settings

from .facebook import FacebookAdapter
from .exceptions import MetaMediaUploadError, MetaPublishingError

logger = logging.getLogger(__name__)


class InstagramAdapter(FacebookAdapter):
    """
    Adapter for Instagram Professional Accounts.
    Inherits unified OAuth and account fetching logic from FacebookAdapter.
    Overrides publishing to use Instagram Graph API's 2-step media container flow.
    """

    def publish_text(self, access_token: str, author_urn: str, text: str) -> Dict[str, Any]:
        """Instagram Graph API does not support text-only posts."""
        raise MetaPublishingError("Instagram does not support text-only posts. An image or video is required.")

    def publish_image(self, access_token: str, author_urn: str, text: str, image_data: bytes = None, filename: str = "image.jpg", image_url: str = None) -> Dict[str, Any]:
        """
        Publish image post to Instagram.
        Uses a 2-step process:
        1. Create a media container using a public image_url.
        2. Publish the container.
        """
        if not image_url:
            # Instagram Graph API requires a public URL. Raw bytes upload is not supported.
            raise MetaMediaUploadError("Instagram requires a public image URL for publishing. Local bytes upload is not supported.")

        # Step 1: Create Media Container
        container_url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{author_urn}/media"
        container_data = {
            "image_url": image_url,
            "caption": text,
            "access_token": access_token
        }
        
        container_res = requests.post(container_url, data=container_data, timeout=15)
        self._handle_api_errors(container_res)
        
        creation_id = container_res.json().get("id")
        if not creation_id:
            raise MetaMediaUploadError("Failed to retrieve creation_id from Instagram media container.")

        # Wait briefly for Meta to process the container before publishing
        time.sleep(2)

        # Step 2: Publish Media Container
        publish_url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{author_urn}/media_publish"
        publish_data = {
            "creation_id": creation_id,
            "access_token": access_token
        }
        
        publish_res = requests.post(publish_url, data=publish_data, timeout=15)
        self._handle_api_errors(publish_res)
        
        return {"id": publish_res.json().get("id")}
