"""Text adapters for providers that expose the OpenAI chat-completions protocol.

Product code still requests ``Capability.TEXT`` from ``AIRouter``. This module
is the only place that knows the vendors, endpoints, authentication header and
wire response. Endpoints are code-owned constants: workspace administrators
cannot turn this adapter into an arbitrary-network request.
"""
import json
from typing import Any, Dict, Mapping

import httpx
from django.conf import settings

from apps.ai.models import Capability

from .base import AIProviderAdapter, AIProviderError


class OpenAICompatibleTextAdapter(AIProviderAdapter):
    """Shared, provider-neutral normalisation for chat-completions services."""

    key = ''
    capabilities = (Capability.TEXT,)
    base_url = ''
    unit_cost = 0.04

    def _api_key(self) -> str:
        return (self.credentials or '').strip()

    def _detail(self, message: str) -> str:
        return f'{self.display_name} {message}'

    def _error_for_status(self, status_code: int) -> str:
        if status_code in (401, 403):
            return self._detail('authentication failed.')
        if status_code == 429:
            return self._detail('request was rate limited.')
        if status_code in (400, 404, 409, 422):
            return self._detail('rejected the request.')
        if status_code >= 500:
            return self._detail('is temporarily unavailable.')
        return self._detail('request failed.')

    def _headers(self) -> Dict[str, str]:
        api_key = self._api_key()
        if not api_key:
            raise AIProviderError(self._detail('API key is not configured.'))
        return {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        timeout = float(getattr(settings, 'AI_PROVIDER_REQUEST_TIMEOUT', 60.0))
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
                headers=self._headers(),
                json=payload,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise AIProviderError(self._detail('request timed out.')) from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(self._detail('could not be reached.')) from exc

        if response.status_code >= 400:
            raise AIProviderError(self._error_for_status(response.status_code))
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            raise AIProviderError(self._detail('returned an invalid response.')) from exc
        if not isinstance(data, dict):
            raise AIProviderError(self._detail('returned an invalid response.'))
        return data

    @staticmethod
    def _brief_json(brief: Mapping[str, Any]) -> str:
        return json.dumps(
            brief,
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
            default=str,
        )

    def _response_text(self, response: Mapping[str, Any]) -> str:
        choices = response.get('choices')
        first = choices[0] if isinstance(choices, list) and choices else None
        message = first.get('message') if isinstance(first, Mapping) else None
        content = message.get('content') if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise AIProviderError(self._detail('returned no text.'))
        return content.strip()

    def _decode_json(self, text: str) -> Dict[str, Any]:
        value = text.strip()
        if value.startswith('```') and value.endswith('```'):
            value = value[3:-3].strip()
            if value.casefold().startswith('json'):
                value = value[4:].strip()
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise AIProviderError(self._detail('returned invalid structured output.')) from exc
        if not isinstance(parsed, dict):
            raise AIProviderError(self._detail('returned invalid structured output.'))
        return parsed

    def _required_string(self, data: Mapping[str, Any], field: str) -> str:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AIProviderError(self._detail('returned incomplete structured output.'))
        return value.strip()

    def generate_text(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        response = self._post('chat/completions', {
            'model': self.model,
            'messages': [
                {
                    'role': 'system',
                    'content': (
                        'Act only as a replaceable execution provider for Scaleezy. '
                        'Respect supplied brand facts and hard rules. Return one JSON '
                        'object with exactly headline, caption and hashtags strings.'
                    ),
                },
                {
                    'role': 'user',
                    'content': (
                        'Create one concise, brand-aligned social marketing post from '
                        'this provider-neutral brief.\nBRIEF_JSON:\n'
                        + self._brief_json(brief)
                    ),
                },
            ],
            'response_format': {'type': 'json_object'},
            'temperature': float(self.config.get('temperature', 0.7)),
            'max_tokens': int(self.config.get('max_tokens', 1200)),
        })
        generated = self._decode_json(self._response_text(response))
        headline = self._required_string(generated, 'headline')
        caption = self._required_string(generated, 'caption')
        hashtags = self._required_string(generated, 'hashtags')
        return {
            'headline': headline,
            'caption': caption,
            'hashtags': hashtags,
            'raw': {
                'postTitle': headline,
                'postDescription': caption,
                'postHashtags': hashtags,
                'metadata': {
                    'response_id': str(response.get('id') or ''),
                    'model': str(response.get('model') or self.model),
                },
            },
        }

    def health_check(self) -> Dict[str, Any]:
        if not self._api_key():
            return {'ok': False, 'detail': self._detail('API key is not configured.')}
        try:
            timeout = float(getattr(settings, 'AI_PROVIDER_HEALTH_TIMEOUT', 10.0))
            response = httpx.get(
                f"{self.base_url.rstrip('/')}/models",
                headers=self._headers(),
                timeout=timeout,
            )
        except httpx.TimeoutException:
            return {'ok': False, 'detail': self._detail('health check timed out.')}
        except httpx.HTTPError:
            return {'ok': False, 'detail': self._detail('could not be reached.')}
        except (TypeError, ValueError):
            return {'ok': False, 'detail': self._detail('health check is misconfigured.')}

        if response.status_code >= 300:
            return {'ok': False, 'detail': self._error_for_status(response.status_code)}
        return {'ok': True, 'detail': f'Connected (model {self.model}).'}


class GroqAdapter(OpenAICompatibleTextAdapter):
    key = 'groq'
    display_name = 'Groq'
    default_model = 'openai/gpt-oss-20b'
    base_url = 'https://api.groq.com/openai/v1'


class MistralAdapter(OpenAICompatibleTextAdapter):
    key = 'mistral'
    display_name = 'Mistral AI'
    default_model = 'mistral-small-latest'
    base_url = 'https://api.mistral.ai/v1'


class DeepSeekAdapter(OpenAICompatibleTextAdapter):
    key = 'deepseek'
    display_name = 'DeepSeek'
    default_model = 'deepseek-v4-flash'
    base_url = 'https://api.deepseek.com'


class OpenRouterAdapter(OpenAICompatibleTextAdapter):
    key = 'openrouter'
    display_name = 'OpenRouter'
    default_model = 'openai/gpt-oss-20b'
    base_url = 'https://openrouter.ai/api/v1'


class TogetherAdapter(OpenAICompatibleTextAdapter):
    key = 'together'
    display_name = 'Together AI'
    default_model = 'openai/gpt-oss-20b'
    base_url = 'https://api.together.ai/v1'

