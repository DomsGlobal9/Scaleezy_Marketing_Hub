"""
Gemini adapter.

Wraps the existing GeminiGeneratorService rather than reimplementing it, so
the working generation path is untouched and the router simply becomes another
way to reach it.
"""
import logging
from typing import Any, Dict

from django.conf import settings

from apps.ai.models import Capability

from .base import AIProviderAdapter, AIProviderError

logger = logging.getLogger(__name__)


class GeminiAdapter(AIProviderAdapter):
    key = 'gemini'
    display_name = 'Google Gemini'
    capabilities = (Capability.TEXT, Capability.IMAGE, Capability.IMAGE_ANALYSIS)
    default_model = 'gemini-1.5-pro'
    unit_cost = 0.02

    def _service(self):
        from apps.gemini.services.generator import GeminiGeneratorService

        return GeminiGeneratorService

    def generate_text(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        result = self._service().generate_marketing_content(brief)
        return {
            'headline': result.get('postTitle', ''),
            'caption': result.get('postDescription', ''),
            'hashtags': result.get('postHashtags', ''),
            'raw': result,
        }

    def generate_image(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        # Gemini returns copy and imagery from one call, so image generation
        # reuses it and picks out the poster.
        result = self._service().generate_marketing_content(brief)
        url = result.get('posterImageUrl', '')
        if not url:
            raise AIProviderError("Gemini returned no image.")
        return {'image_url': url, 'raw': result}

    def analyze_image(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        b64 = brief.get('reference_image_base64') or brief.get('referenceImageBase64', '')
        if not b64:
            raise AIProviderError("No image supplied for analysis.")
        return {'analysis': self._service().analyze_reference_image(b64)}

    def health_check(self) -> Dict[str, Any]:
        # The key is read from settings today; a per-workspace credential
        # overrides it once supplied.
        key = self.credentials or getattr(settings, 'GEMINI_API_KEY', '')
        if not key:
            return {'ok': False, 'detail': 'No Gemini API key configured.'}
        return {'ok': True, 'detail': f'Configured (model {self.model}).'}
