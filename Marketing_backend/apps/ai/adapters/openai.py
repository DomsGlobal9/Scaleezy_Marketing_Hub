"""OpenAI adapter for the provider-neutral PR5 AI boundary.

Only this module knows OpenAI endpoint and payload shapes.  The router still
asks for capabilities and receives the same normalized dictionaries as every
other provider adapter.
"""
import base64
import binascii
import json
import math
from typing import Any, Dict, Mapping
from urllib.parse import urlsplit

import httpx
from django.conf import settings

from apps.ai.models import Capability

from .base import AIProviderAdapter, AIProviderError


class OpenAIAdapter(AIProviderAdapter):
    key = 'openai'
    display_name = 'OpenAI'
    capabilities = (
        Capability.TEXT,
        Capability.IMAGE,
        Capability.IMAGE_ANALYSIS,
        Capability.IMAGE_CAPTION,
        Capability.EMBEDDING,
        Capability.RESEARCH,
        Capability.ENGAGEMENT_RESPONSE,
    )
    default_model = 'gpt-4.1-mini'
    image_model = 'gpt-image-1'
    embedding_model = 'text-embedding-3-small'
    # Deliberately above Gemini's 0.02 default so installing this adapter does
    # not silently change the provider selected for a new tenant.
    unit_cost = 0.03

    _COPY_SCHEMA = {
        'type': 'object',
        'properties': {
            'headline': {'type': 'string'},
            'caption': {'type': 'string'},
            'hashtags': {'type': 'string'},
        },
        'required': ['headline', 'caption', 'hashtags'],
        'additionalProperties': False,
    }
    _ANALYSIS_SCHEMA = {
        'type': 'object',
        'properties': {
            'campaignName': {'type': 'string'},
            'product': {'type': 'string'},
            'occasion': {'type': 'string'},
            'brandTone': {'type': 'string'},
        },
        'required': ['campaignName', 'product', 'occasion', 'brandTone'],
        'additionalProperties': False,
    }
    _CAPTION_SCHEMA = {
        'type': 'object',
        'properties': {
            'postTitle': {'type': 'string'},
            'postDescription': {'type': 'string'},
            'postHashtags': {'type': 'string'},
        },
        'required': ['postTitle', 'postDescription', 'postHashtags'],
        'additionalProperties': False,
    }
    _RESEARCH_SCHEMA = {
        'type': 'object',
        'properties': {
            'findings': {
                'type': 'array',
                'maxItems': 16,
                'items': {
                    'type': 'object',
                    'properties': {
                        'title': {'type': 'string'},
                        'source_url': {'type': 'string'},
                        'preview_url': {'type': 'string'},
                        'source_name': {'type': 'string'},
                        'platform': {'type': 'string'},
                        'kind': {
                            'type': 'string',
                            'enum': [
                                'POSTER', 'SOCIAL_POST', 'VIDEO', 'CAMPAIGN',
                                'COMPETITOR', 'TREND', 'HOOK', 'OTHER',
                            ],
                        },
                        'excerpt': {'type': 'string'},
                        'observed_at': {'type': 'string'},
                    },
                    'required': [
                        'title', 'source_url', 'preview_url', 'source_name',
                        'platform', 'kind', 'excerpt', 'observed_at',
                    ],
                    'additionalProperties': False,
                },
            },
        },
        'required': ['findings'],
        'additionalProperties': False,
    }
    _ENGAGEMENT_SCHEMA = {
        'type': 'object',
        'properties': {
            'reply': {'type': 'string'},
            'sentiment': {
                'type': 'string',
                'enum': ['UNKNOWN', 'POSITIVE', 'NEUTRAL', 'NEGATIVE'],
            },
            'urgency': {
                'type': 'string',
                'enum': ['LOW', 'NORMAL', 'HIGH', 'CRITICAL'],
            },
            'risk_flags': {'type': 'array', 'items': {'type': 'string'}},
        },
        'required': ['reply', 'sentiment', 'urgency', 'risk_flags'],
        'additionalProperties': False,
    }

    def _api_key(self) -> str:
        """Workspace credential wins; the deployment key is only fallback."""
        return (
            self.credentials
            or getattr(settings, 'OPENAI_API_KEY', '')
            or ''
        ).strip()

    @staticmethod
    def _error_for_status(status_code: int) -> str:
        # Never include the upstream body: it can echo prompts, image URLs or
        # other tenant data.  These messages are enough for failover and the
        # admin health surface without exposing provider internals.
        if status_code in (401, 403):
            return 'OpenAI authentication failed.'
        if status_code == 429:
            return 'OpenAI request was rate limited.'
        if status_code in (400, 404, 409, 422):
            return 'OpenAI rejected the request.'
        if status_code >= 500:
            return 'OpenAI is temporarily unavailable.'
        return 'OpenAI request failed.'

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        api_key = self._api_key()
        if not api_key:
            raise AIProviderError('No OpenAI API key configured.')

        base_url = (
            getattr(settings, 'OPENAI_API_BASE_URL', 'https://api.openai.com/v1')
            or 'https://api.openai.com/v1'
        ).rstrip('/')
        timeout = float(getattr(settings, 'OPENAI_REQUEST_TIMEOUT', 60.0))

        try:
            response = httpx.post(
                f"{base_url}/{path.lstrip('/')}",
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json=payload,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise AIProviderError('OpenAI request timed out.') from exc
        except httpx.HTTPError as exc:
            raise AIProviderError('OpenAI could not be reached.') from exc

        if response.status_code >= 400:
            raise AIProviderError(self._error_for_status(response.status_code))

        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            raise AIProviderError('OpenAI returned an invalid response.') from exc
        if not isinstance(data, dict):
            raise AIProviderError('OpenAI returned an invalid response.')
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

    @staticmethod
    def _response_text(response: Mapping[str, Any]) -> str:
        # ``output_text`` is an SDK convenience but accepting it also keeps the
        # parser tolerant of compatible gateways.  Raw Responses API payloads
        # carry output_text parts under output[].content[].
        direct = response.get('output_text')
        if isinstance(direct, str) and direct.strip():
            return direct.strip()

        chunks = []
        output = response.get('output')
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, Mapping):
                    continue
                content = item.get('content')
                if not isinstance(content, list):
                    continue
                for part in content:
                    if (
                        isinstance(part, Mapping)
                        and part.get('type') == 'output_text'
                        and isinstance(part.get('text'), str)
                    ):
                        chunks.append(part['text'])
        text = '\n'.join(chunks).strip()
        if not text:
            raise AIProviderError('OpenAI returned no text.')
        return text

    @staticmethod
    def _decode_json(text: str) -> Dict[str, Any]:
        value = text.strip()
        if value.startswith('```') and value.endswith('```'):
            value = value[3:-3].strip()
            if value.casefold().startswith('json'):
                value = value[4:].strip()
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise AIProviderError('OpenAI returned invalid structured output.') from exc
        if not isinstance(parsed, dict):
            raise AIProviderError('OpenAI returned invalid structured output.')
        return parsed

    def _responses_json(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: Dict[str, Any],
        image_url: str = '',
        model: str = '',
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        content = [{'type': 'input_text', 'text': prompt}]
        if image_url:
            content.append({
                'type': 'input_image',
                'image_url': image_url,
                'detail': self.config.get('vision_detail', 'auto'),
            })

        response = self._post('responses', {
            'model': model or self.model,
            'instructions': (
                'Act only as a replaceable execution provider for Scaleezy. '
                'Respect the supplied brand facts and hard rules; do not invent '
                'business claims. Return the requested structured result only.'
            ),
            'input': [{'role': 'user', 'content': content}],
            'text': {
                'format': {
                    'type': 'json_schema',
                    'name': schema_name,
                    'strict': True,
                    'schema': schema,
                },
            },
            # Brand context must not become provider-side conversation state.
            'store': False,
        })
        return self._decode_json(self._response_text(response)), response

    @staticmethod
    def _required_string(data: Mapping[str, Any], field: str) -> str:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AIProviderError('OpenAI returned incomplete structured output.')
        return value.strip()

    def generate_text(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        if str(brief.get('task') or '').upper() == 'EXTRACT':
            schema = brief.get('response_schema')
            if not isinstance(schema, dict):
                raise AIProviderError('Structured extraction needs a response schema.')
            generated, response = self._responses_json(
                prompt=(
                    str(brief.get('instruction') or 'Extract only grounded facts.')
                    + '\nINPUT_JSON:\n'
                    + self._brief_json(brief.get('structured') or {})
                ),
                schema_name=str(brief.get('schema_name') or 'scaleezy_extraction')[:64],
                schema=schema,
            )
            return {
                'raw': generated,
                'metadata': {
                    'response_id': str(response.get('id') or ''),
                    'model': str(response.get('model') or self.model),
                },
            }

        generated, response = self._responses_json(
            prompt=(
                'Create one concise, brand-aligned social marketing post from '
                'this provider-neutral brief.\nBRIEF_JSON:\n'
                + self._brief_json(brief)
            ),
            schema_name='scaleezy_marketing_copy',
            schema=self._COPY_SCHEMA,
        )
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
        model = str(self.config.get('image_model') or self.image_model)
        output_format = str(self.config.get('image_output_format') or 'png').lower()
        if output_format not in {'png', 'jpeg', 'webp'}:
            output_format = 'png'

        response = self._post('images/generations', {
            'model': model,
            'prompt': (
                'Create one polished, brand-aligned marketing visual from this '
                'provider-neutral brief. Obey every hard rule. Do not add claims '
                'that are not in the brief.\nBRIEF_JSON:\n'
                + self._brief_json(brief)
            ),
            'n': 1,
            'size': self.config.get('image_size', '1024x1024'),
            'quality': self.config.get('image_quality', 'medium'),
            'output_format': output_format,
        })
        items = response.get('data')
        item = items[0] if isinstance(items, list) and items else None
        if not isinstance(item, Mapping):
            raise AIProviderError('OpenAI returned no image.')

        image_url = item.get('url')
        image_base64 = ''
        mime_type = ''
        if not isinstance(image_url, str) or not image_url.strip():
            encoded = item.get('b64_json')
            if not isinstance(encoded, str) or not encoded.strip():
                raise AIProviderError('OpenAI returned no image.')
            encoded = ''.join(encoded.split())
            try:
                base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise AIProviderError('OpenAI returned an invalid image.') from exc
            mime_subtype = 'jpeg' if output_format == 'jpeg' else output_format
            mime_type = f'image/{mime_subtype}'
            image_base64 = encoded
            image_url = f'data:{mime_type};base64,{encoded}'

        result = {
            'image_url': image_url.strip(),
            # Hosted provider URLs may expire. The provider-neutral generation
            # boundary copies them to Scaleezy storage before persistence.
            'image_url_ephemeral': not bool(image_base64),
            'raw': {
                'response_id': str(response.get('id') or ''),
                'model': str(response.get('model') or model),
                'revised_prompt': str(item.get('revised_prompt') or ''),
            },
        }
        if image_base64:
            # The provider-neutral generation boundary persists these bytes to
            # durable storage before a ContentItem is written.  image_url is
            # retained for immediate consumers of the existing PR5 contract.
            result.update({
                'image_base64': image_base64,
                'mime_type': mime_type,
            })
        return result

    @staticmethod
    def _validate_data_image(value: str) -> str:
        header, separator, encoded = value.partition(',')
        if (
            not separator
            or not header.casefold().startswith('data:image/')
            or ';base64' not in header.casefold()
        ):
            raise AIProviderError('Supplied image is invalid.')
        encoded = ''.join(encoded.split())
        try:
            base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AIProviderError('Supplied image is invalid.') from exc
        return f'{header},{encoded}'

    def _image_reference(self, brief: Mapping[str, Any]) -> str:
        url = (
            brief.get('reference_image_url')
            or brief.get('referenceImageUrl')
            or ''
        )
        if isinstance(url, str) and url.strip():
            url = url.strip()
            if url.casefold().startswith('data:image/'):
                return self._validate_data_image(url)
            if urlsplit(url).scheme.casefold() not in {'http', 'https'}:
                raise AIProviderError('Supplied image URL is invalid.')
            return url

        encoded = (
            brief.get('reference_image_base64')
            or brief.get('referenceImageBase64')
            or ''
        )
        if not isinstance(encoded, str) or not encoded.strip():
            raise AIProviderError('No image supplied for OpenAI image analysis.')
        encoded = encoded.strip()
        if encoded.casefold().startswith('data:image/'):
            return self._validate_data_image(encoded)

        mime_type = str(
            brief.get('reference_image_mime_type')
            or brief.get('referenceImageMimeType')
            or 'image/jpeg'
        ).casefold()
        if mime_type not in {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}:
            raise AIProviderError('Supplied image type is not supported.')
        return self._validate_data_image(f'data:{mime_type};base64,{encoded}')

    def analyze_image(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        if str(brief.get('task') or '').upper() == 'INSPIRATION_ANALYSIS':
            schema = brief.get('response_schema')
            if not isinstance(schema, dict):
                raise AIProviderError('Inspiration analysis needs a response schema.')
            analysis, response = self._responses_json(
                prompt=str(brief.get('instruction') or 'Analyze this creative reference.'),
                schema_name='scaleezy_inspiration_signals',
                schema=schema,
                image_url=self._image_reference(brief),
                model=str(self.config.get('vision_model') or self.model),
            )
            return {'analysis': analysis, 'raw': analysis, 'response_id': response.get('id')}

        analysis, _response = self._responses_json(
            prompt=(
                'Analyze the supplied marketing reference. Infer only visible '
                'information and return the campaign, product, occasion and '
                'visual brand tone. Additional context:\n'
                + self._brief_json({
                    key: value for key, value in brief.items()
                    if 'base64' not in key.casefold()
                })
            ),
            schema_name='scaleezy_image_analysis',
            schema=self._ANALYSIS_SCHEMA,
            image_url=self._image_reference(brief),
            model=str(self.config.get('vision_model') or self.model),
        )
        for field in self._ANALYSIS_SCHEMA['required']:
            self._required_string(analysis, field)
        return {'analysis': analysis}

    def generate_image_captions(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        captions, _response = self._responses_json(
            prompt=(
                'Write social copy for the supplied finished marketing image. '
                'Keep claims grounded in the image and this context:\n'
                + self._brief_json({
                    key: value for key, value in brief.items()
                    if 'base64' not in key.casefold()
                })
            ),
            schema_name='scaleezy_image_captions',
            schema=self._CAPTION_SCHEMA,
            image_url=self._image_reference(brief),
            model=str(self.config.get('vision_model') or self.model),
        )
        for field in self._CAPTION_SCHEMA['required']:
            self._required_string(captions, field)
        return {'captions': captions}

    def generate_embedding(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        text = brief.get('text')
        if not isinstance(text, str) or not text.strip():
            raise AIProviderError('No text supplied to embed.')

        model = str(self.config.get('embedding_model') or self.embedding_model)
        response = self._post('embeddings', {
            'model': model,
            'input': text.strip(),
            'encoding_format': 'float',
        })
        rows = response.get('data')
        row = rows[0] if isinstance(rows, list) and rows else None
        values = row.get('embedding') if isinstance(row, Mapping) else None
        if not isinstance(values, list) or not values:
            raise AIProviderError('OpenAI returned an empty embedding.')
        try:
            vector = [float(value) for value in values]
        except (TypeError, ValueError) as exc:
            raise AIProviderError('OpenAI returned an invalid embedding.') from exc
        if not all(math.isfinite(value) for value in vector):
            raise AIProviderError('OpenAI returned an invalid embedding.')
        return {
            'embedding': vector,
            'model': str(response.get('model') or model),
        }

    def research(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        response = self._post('responses', {
            'model': str(self.config.get('research_model') or self.model),
            'instructions': (
                'Research the live public web for creative references. Cite only '
                'real public HTTPS pages returned by web search. Return references, '
                'not copied assets; never claim or infer reuse rights. Empty strings '
                'are valid when a preview URL or observation date is unavailable.'
            ),
            'tools': [{
                'type': 'web_search',
                'search_context_size': str(
                    self.config.get('research_context_size') or 'medium'
                ),
            }],
            'tool_choice': 'auto',
            'input': 'RESEARCH_BRIEF_JSON:\n' + self._brief_json(brief),
            'text': {
                'format': {
                    'type': 'json_schema',
                    'name': 'scaleezy_creative_research',
                    'strict': True,
                    'schema': self._RESEARCH_SCHEMA,
                },
            },
            'store': False,
        })
        parsed = self._decode_json(self._response_text(response))
        findings = parsed.get('findings')
        if not isinstance(findings, list):
            raise AIProviderError('OpenAI returned no research findings list.')
        web_search_used = any(
            isinstance(item, Mapping) and item.get('type') == 'web_search_call'
            for item in (response.get('output') or [])
        )
        if not web_search_used:
            raise AIProviderError('OpenAI returned research without using live web search.')
        return {
            'findings': findings[:16],
            'raw': {
                'response_id': str(response.get('id') or ''),
                'model': str(response.get('model') or self.model),
                'web_search_used': True,
            },
        }

    def draft_engagement_response(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        generated, response = self._responses_json(
            prompt=(
                'Draft one concise social response from this provider-neutral brief. '
                'Do not invent facts, commitments, refunds, legal or medical outcomes. '
                'Flag risk explicitly; this is a draft for human approval only.\n'
                'ENGAGEMENT_BRIEF_JSON:\n' + self._brief_json(brief)
            ),
            schema_name='scaleezy_engagement_response',
            schema=self._ENGAGEMENT_SCHEMA,
        )
        return {
            'reply': self._required_string(generated, 'reply'),
            'sentiment': str(generated.get('sentiment') or 'UNKNOWN').upper(),
            'urgency': str(generated.get('urgency') or 'NORMAL').upper(),
            'risk_flags': generated.get('risk_flags') or [],
            'raw': {
                'response_id': str(response.get('id') or ''),
                'model': str(response.get('model') or self.model),
            },
        }

    def health_check(self) -> Dict[str, Any]:
        api_key = self._api_key()
        if not api_key:
            return {'ok': False, 'detail': 'No OpenAI API key configured.'}

        # Listing models is authenticated and read-only. It validates the key
        # without consuming generation tokens or creating provider-side state.
        try:
            base_url = str(
                getattr(settings, 'OPENAI_API_BASE_URL', 'https://api.openai.com/v1')
                or 'https://api.openai.com/v1'
            ).rstrip('/')
            timeout = float(getattr(settings, 'AI_PROVIDER_HEALTH_TIMEOUT', 10.0))
            response = httpx.get(
                f'{base_url}/models',
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=timeout,
            )
        except httpx.TimeoutException:
            return {'ok': False, 'detail': 'OpenAI health check timed out.'}
        except httpx.HTTPError:
            return {'ok': False, 'detail': 'OpenAI could not be reached.'}
        except (TypeError, ValueError):
            return {'ok': False, 'detail': 'OpenAI health check is misconfigured.'}

        if response.status_code >= 300:
            return {'ok': False, 'detail': self._error_for_status(response.status_code)}
        return {'ok': True, 'detail': f'Connected (model {self.model}).'}
