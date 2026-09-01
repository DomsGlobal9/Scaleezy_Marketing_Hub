"""Adapters for provider-neutral, administrator-supplied HTTP APIs.

Product code still requests ``Capability.TEXT`` from ``AIRouter``. This module
is the only place that knows the vendors, endpoints, authentication header and
wire response. Endpoints are code-owned constants: workspace administrators
cannot turn this adapter into an arbitrary-network request.
"""
import json
from typing import Any, Dict, Mapping

import httpx
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.ai.endpoint_security import validate_public_https_endpoint
from apps.ai.models import Capability

from .base import AIProviderAdapter, AIProviderError


class OpenAICompatibleTextAdapter(AIProviderAdapter):
    """Common OpenAI-compatible text, image, vision and embedding protocol."""

    key = ''
    # Installed subclasses in this module intentionally remain TEXT-only.
    # The manually configured subclass below exposes the wider standard
    # protocol only when an administrator explicitly selects those functions.
    capabilities = (
        Capability.TEXT,
        Capability.ENGAGEMENT_RESPONSE,
    )
    base_url = ''
    unit_cost = 0.04
    enforce_public_endpoint = False
    allow_anonymous = False

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
        if not api_key and not self.allow_anonymous:
            raise AIProviderError(self._detail('API key is not configured.'))
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        return headers

    def _request_base_url(self) -> str:
        if not self.enforce_public_endpoint:
            return self.base_url.rstrip('/')
        try:
            return validate_public_https_endpoint(self.base_url).rstrip('/')
        except DjangoValidationError as exc:
            raise AIProviderError(
                self._detail('endpoint is not a public HTTPS destination.')
            ) from exc

    def _post_url(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        timeout = float(getattr(settings, 'AI_PROVIDER_REQUEST_TIMEOUT', 60.0))
        try:
            response = httpx.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=timeout,
                follow_redirects=False,
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

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._post_url(
            f"{self._request_base_url()}/{path.lstrip('/')}",
            payload,
        )

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
        if str(brief.get('task') or '').upper() == 'EXTRACT':
            response = self._post('chat/completions', {
                'model': self.model,
                'messages': [
                    {
                        'role': 'system',
                        'content': (
                            'Act only as a replaceable structured extraction provider for '
                            'Scaleezy. Return one JSON object and invent nothing.'
                        ),
                    },
                    {
                        'role': 'user',
                        'content': (
                            str(brief.get('instruction') or 'Extract grounded facts.')
                            + '\nINPUT_JSON:\n'
                            + self._brief_json(brief.get('structured') or {})
                        ),
                    },
                ],
                'response_format': {'type': 'json_object'},
                'temperature': 0,
                'max_tokens': int(self.config.get('max_tokens', 2000)),
            })
            return {
                'raw': self._decode_json(self._response_text(response)),
                'metadata': {
                    'response_id': str(response.get('id') or ''),
                    'model': str(response.get('model') or self.model),
                },
            }

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

    def generate_image(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        response = self._post('images/generations', {
            'model': self.model,
            'prompt': (
                'Create one polished, brand-aligned marketing visual. '
                'Do not invent business claims. The image must contain no '
                'text, lettering, numbers, logos or watermarks - typography '
                'is composed onto it separately.\nBRIEF_JSON:\n'
                + self._brief_json(brief)
            ),
            'n': 1,
            'size': self.config.get('image_size', '1024x1024'),
        })
        rows = response.get('data')
        first = rows[0] if isinstance(rows, list) and rows else None
        if not isinstance(first, Mapping):
            raise AIProviderError(self._detail('returned no image.'))
        image_url = first.get('url')
        encoded = first.get('b64_json')
        if isinstance(encoded, str) and encoded.strip():
            image_url = f"data:image/png;base64,{encoded.strip()}"
        if not isinstance(image_url, str) or not image_url.strip():
            raise AIProviderError(self._detail('returned no image.'))
        return {
            'image_url': image_url.strip(),
            'image_url_ephemeral': not bool(encoded),
            'raw': response,
        }

    @staticmethod
    def _image_reference(brief: Mapping[str, Any]) -> str:
        direct = brief.get('reference_image_url') or brief.get('image_url')
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        encoded = brief.get('reference_image_base64')
        if isinstance(encoded, str) and encoded.strip():
            value = encoded.strip()
            return value if value.startswith('data:') else f'data:image/jpeg;base64,{value}'
        return ''

    def _vision_json(self, brief: Mapping[str, Any], instruction: str) -> Dict[str, Any]:
        image_url = self._image_reference(brief)
        if not image_url:
            raise AIProviderError(self._detail('requires an image.'))
        response = self._post('chat/completions', {
            'model': self.model,
            'messages': [{
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': instruction},
                    {'type': 'image_url', 'image_url': {'url': image_url}},
                ],
            }],
            'response_format': {'type': 'json_object'},
            'temperature': 0,
        })
        return self._decode_json(self._response_text(response))

    def analyze_image(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        analysis = self._vision_json(
            brief,
            str(brief.get('instruction') or 'Analyze this marketing image. Return one useful JSON object only.'),
        )
        return {'analysis': analysis, 'raw': analysis}

    def generate_image_captions(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        captions = self._vision_json(
            brief,
            'Return one JSON object with postTitle, postDescription and postHashtags strings.',
        )
        return {'captions': captions, 'raw': captions}

    def generate_embedding(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        text = str(brief.get('text') or '').strip()
        if not text:
            raise AIProviderError(self._detail('requires text to embed.'))
        response = self._post('embeddings', {'model': self.model, 'input': text})
        rows = response.get('data')
        first = rows[0] if isinstance(rows, list) and rows else None
        vector = first.get('embedding') if isinstance(first, Mapping) else None
        if not isinstance(vector, list) or not vector:
            raise AIProviderError(self._detail('returned no embedding.'))
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise AIProviderError(self._detail('returned an invalid embedding.')) from exc
        return {'embedding': values, 'model': str(response.get('model') or self.model)}

    def research(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        # Chat Completions is not, by itself, proof that a model can access the
        # live web. Treating citations invented from model memory as research
        # would make the source-verification layer look safer than it is. A
        # real web-capable adapter (OpenAI Responses below, or SCALEEZY_JSON)
        # must own this capability explicitly.
        raise AIProviderError(
            self._detail('does not expose verified live-web research through this protocol.')
        )

    def draft_engagement_response(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        response = self._post('chat/completions', {
            'model': self.model,
            'messages': [
                {
                    'role': 'system',
                    'content': (
                        'Draft one concise social response using only the supplied '
                        'brand context and message. Never promise refunds, legal '
                        'outcomes, medical outcomes or facts not in the brief. Return '
                        'JSON with reply, sentiment, urgency and risk_flags. This is '
                        'a draft for human approval, never a sent response.'
                    ),
                },
                {
                    'role': 'user',
                    'content': 'ENGAGEMENT_BRIEF_JSON:\n' + self._brief_json(brief),
                },
            ],
            'response_format': {'type': 'json_object'},
            'temperature': float(self.config.get('engagement_temperature', 0.4)),
            'max_tokens': int(self.config.get('engagement_max_tokens', 900)),
        })
        parsed = self._decode_json(self._response_text(response))
        reply = self._required_string(parsed, 'reply')
        return {
            'reply': reply,
            'sentiment': str(parsed.get('sentiment') or 'UNKNOWN').upper(),
            'urgency': str(parsed.get('urgency') or 'NORMAL').upper(),
            'risk_flags': parsed.get('risk_flags') if isinstance(parsed.get('risk_flags'), list) else [],
            'raw': {
                'response_id': str(response.get('id') or ''),
                'model': str(response.get('model') or self.model),
            },
        }

    def health_check(self) -> Dict[str, Any]:
        if not self._api_key() and not self.allow_anonymous:
            return {'ok': False, 'detail': self._detail('API key is not configured.')}
        try:
            timeout = float(getattr(settings, 'AI_PROVIDER_HEALTH_TIMEOUT', 10.0))
            response = httpx.get(
                f"{self._request_base_url()}/models",
                headers=self._headers(),
                timeout=timeout,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            return {'ok': False, 'detail': self._detail('health check timed out.')}
        except httpx.HTTPError:
            return {'ok': False, 'detail': self._detail('could not be reached.')}
        except (TypeError, ValueError, AIProviderError) as exc:
            if isinstance(exc, AIProviderError):
                return {'ok': False, 'detail': str(exc)}
            return {'ok': False, 'detail': self._detail('health check is misconfigured.')}

        if response.status_code >= 300:
            return {'ok': False, 'detail': self._error_for_status(response.status_code)}
        return {'ok': True, 'detail': f'Connected (model {self.model}).'}


class CustomOpenAICompatibleAdapter(OpenAICompatibleTextAdapter):
    """Manually configured OpenAI-compatible endpoint capabilities."""

    capabilities = (
        Capability.TEXT,
        Capability.IMAGE,
        Capability.IMAGE_ANALYSIS,
        Capability.IMAGE_CAPTION,
        Capability.EMBEDDING,
        Capability.ENGAGEMENT_RESPONSE,
    )


class ScaleezyJSONAdapter(OpenAICompatibleTextAdapter):
    """Universal capability contract for a customer-owned gateway/webhook.

    The endpoint receives ``capability``, ``model`` and a provider-neutral
    ``brief`` and returns either the normalized result object or
    ``{"result": {...}}``. This keeps arbitrary vendor payloads outside the
    product while allowing every capability to be routed through one stable
    contract.
    """

    capabilities = tuple(Capability.values)

    def run(self, capability: str, brief: Dict[str, Any]) -> Dict[str, Any]:
        response = self._post_url(self._request_base_url(), {
            'capability': capability,
            'model': self.model,
            'brief': brief,
        })
        result = response.get('result', response)
        if not isinstance(result, dict) or not result:
            raise AIProviderError(self._detail('returned no structured result.'))
        if capability == Capability.IMAGE and not result.get('image_url') and result.get('url'):
            result = {**result, 'image_url': result['url']}
        if capability == Capability.VIDEO and not result.get('video_url') and result.get('url'):
            result = {**result, 'video_url': result['url']}
        return result

    def health_check(self) -> Dict[str, Any]:
        try:
            response = self._post_url(self._request_base_url(), {
                'capability': 'HEALTH',
                'model': self.model,
                'brief': {},
            })
        except AIProviderError as exc:
            return {'ok': False, 'detail': str(exc)}
        if response.get('ok') is False:
            return {'ok': False, 'detail': self._detail('health check failed.')}
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
