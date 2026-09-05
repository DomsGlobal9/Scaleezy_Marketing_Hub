"""
Gemini adapter.

Wraps the existing GeminiGeneratorService rather than reimplementing it, so
the working generation path is untouched and the router simply becomes another
way to reach it.
"""
import json
import logging
from typing import Any, Dict

import httpx
from django.conf import settings

from apps.ai.models import Capability

from .base import AIProviderAdapter, AIProviderError

logger = logging.getLogger(__name__)


class GeminiAdapter(AIProviderAdapter):
    key = 'gemini'
    display_name = 'Google Gemini'
    # generate_marketing_content returns copy and the poster from one call.
    yields_poster_with_text = True
    capabilities = (
        Capability.TEXT,
        Capability.IMAGE,
        Capability.IMAGE_ANALYSIS,
        Capability.IMAGE_CAPTION,
        Capability.VIDEO_ANALYSIS,
        Capability.EMBEDDING,
        Capability.ENGAGEMENT_RESPONSE,
    )
    default_model = 'gemini-2.5-flash'
    unit_cost = 0.02

    #: analyze_image briefs whose response_schema must be honoured via the
    #: structured JSON path. Every other task keeps the legacy
    #: analyze_reference_image behaviour, unchanged.
    STRUCTURED_IMAGE_TASKS = ('INSPIRATION_ANALYSIS', 'SUBJECT_FOCUS', 'IMAGE_TEXT_AUDIT')

    @staticmethod
    def _structured_config(brief):
        schema = brief.get('response_schema')
        if not isinstance(schema, dict):
            return None
        from google.genai import types

        return types.GenerateContentConfig(
            response_mime_type='application/json',
            response_json_schema=schema,
        )

    @staticmethod
    def _validate_structured_output(value, brief):
        schema = brief.get('response_schema')
        if not isinstance(schema, dict):
            return
        properties = schema.get('properties') or {}
        for field in schema.get('required') or []:
            if field not in value:
                raise AIProviderError('Gemini returned incomplete structured output.')
            definition = properties.get(field) or {}
            if definition.get('type') == 'array':
                rows = value.get(field)
                minimum = int(definition.get('minItems') or 0)
                if not isinstance(rows, list) or len(rows) < minimum:
                    raise AIProviderError('Gemini returned incomplete structured output.')

    def _service(self):
        from apps.gemini.services.generator import GeminiGeneratorService

        return GeminiGeneratorService

    def generate_text(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        if str(brief.get('task') or '').upper() == 'EXTRACT':
            prompt = (
                str(brief.get('instruction') or 'Extract only grounded facts.')
                + '\nReturn one valid JSON object only.\nINPUT_JSON:\n'
                + json.dumps(
                    brief.get('structured') or {}, ensure_ascii=False,
                    sort_keys=True, default=str,
                )
            )
            try:
                # The client is process-cached (GeminiGeneratorService) so it
                # cannot be garbage-collected mid-flight. If its transport was
                # still closed underneath it (seen in production as "Cannot
                # send a request, as the client has been closed", deterministic
                # until a worker restart), discard the cache and retry once
                # with a fresh client before failing.
                service = self._service()
                kwargs = {
                    'model': self.model or service.TEXT_MODEL,
                    'contents': [prompt],
                }
                config = self._structured_config(brief)
                if config is not None:
                    kwargs['config'] = config
                # The local binding stays load-bearing even with the cache:
                # google.genai.Client closes its transport in __del__, so the
                # client must be referenced for the whole request, never
                # chained from a temporary.
                client = service._get_client(self.credentials)
                try:
                    response = client.models.generate_content(**kwargs)
                except Exception as exc:
                    if 'client has been closed' not in str(exc).lower():
                        raise
                    service._discard_client(self.credentials)
                    client = service._get_client(self.credentials)
                    response = client.models.generate_content(**kwargs)
                value = (response.text or '').strip()
                if value.startswith('```') and value.endswith('```'):
                    value = value[3:-3].strip()
                    if value.casefold().startswith('json'):
                        value = value[4:].strip()
                parsed = json.loads(value)
            except Exception as exc:
                raise AIProviderError(f'Gemini structured extraction failed: {exc}') from exc
            if not isinstance(parsed, dict):
                raise AIProviderError('Gemini returned invalid structured extraction output.')
            self._validate_structured_output(parsed, brief)
            return {'raw': parsed}

        # self.credentials is this workspace's own key when it saved one, and
        # empty otherwise; the service falls back to the server key and raises
        # if there is neither.
        result = self._service().generate_marketing_content(brief, api_key=self.credentials)
        return {
            'headline': result.get('postTitle', ''),
            'caption': result.get('postDescription', ''),
            'hashtags': result.get('postHashtags', ''),
            'raw': result,
        }

    def generate_image(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        # Gemini returns copy and imagery from one call, so image generation
        # reuses it and picks out the poster.
        result = self._service().generate_marketing_content(brief, api_key=self.credentials)
        url = result.get('posterImageUrl', '')
        if not url:
            raise AIProviderError("Gemini returned no image.")
        return {'image_url': url, 'raw': result}

    def analyze_image(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        b64 = brief.get('reference_image_base64') or brief.get('referenceImageBase64', '')
        if not b64:
            raise AIProviderError("No image supplied for analysis.")
        if str(brief.get('task') or '').upper() in self.STRUCTURED_IMAGE_TASKS:
            mime_type, img_bytes = self._service()._parse_base64_image(b64)
            if not mime_type or not img_bytes:
                raise AIProviderError('The inspiration image could not be decoded.')
            try:
                from google.genai import types

                client = self._service()._get_client(self.credentials)
                kwargs = {
                    'model': self.model or self._service().TEXT_MODEL,
                    'contents': [
                        str(brief.get('instruction') or 'Analyze this creative reference as JSON.'),
                        types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
                    ],
                }
                config = self._structured_config(brief)
                if config is not None:
                    kwargs['config'] = config
                response = client.models.generate_content(**kwargs)
                value = (response.text or '').strip()
                if value.startswith('```') and value.endswith('```'):
                    value = value[3:-3].strip()
                    if value.casefold().startswith('json'):
                        value = value[4:].strip()
                parsed = json.loads(value)
            except Exception as exc:
                raise AIProviderError(f'Gemini inspiration analysis failed: {exc}') from exc
            if not isinstance(parsed, dict):
                raise AIProviderError('Gemini returned invalid inspiration analysis output.')
            self._validate_structured_output(parsed, brief)
            return {'analysis': parsed, 'raw': parsed}
        return {'analysis': self._service().analyze_reference_image(
            b64, api_key=self.credentials)}

    def generate_image_captions(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        b64 = brief.get('reference_image_base64') or brief.get('referenceImageBase64', '')
        if not b64:
            raise AIProviderError("No image supplied for caption generation.")
        return {'captions': self._service().generate_captions_only(
            b64, api_key=self.credentials
        )}

    def analyze_video(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        asset_id = brief.get('asset_id')
        if not asset_id:
            raise AIProviderError("No asset supplied for video analysis.")
        return {'analysis': self._service().analyze_video(
            asset_id, api_key=self.credentials
        )}

    #: Embedding model, separate from the generation model.
    embedding_model = 'text-embedding-004'

    def generate_embedding(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        text = (brief.get('text') or '').strip()
        if not text:
            raise AIProviderError("No text supplied to embed.")

        model = self.config.get('embedding_model') or self.embedding_model
        try:
            client = self._service()._get_client(self.credentials)
            response = client.models.embed_content(
                model=model, contents=text
            )
            vector = list(response.embeddings[0].values)
        except AIProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as provider failure
            raise AIProviderError(f"Gemini embedding failed: {exc}") from exc

        if not vector:
            raise AIProviderError("Gemini returned an empty embedding.")
        return {'embedding': vector, 'model': model}

    def draft_engagement_response(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        prompt = (
            'Draft one concise social response using only the supplied brand context '
            'and message. Never promise refunds, legal or medical outcomes, or facts '
            'not in the brief. Return one JSON object with reply, sentiment '
            '(UNKNOWN/POSITIVE/NEUTRAL/NEGATIVE), urgency '
            '(LOW/NORMAL/HIGH/CRITICAL), and risk_flags. This is a human-review '
            'draft only.\nENGAGEMENT_BRIEF_JSON:\n'
            + json.dumps(brief, ensure_ascii=False, sort_keys=True, default=str)
        )
        try:
            client = self._service()._get_client(self.credentials)
            response = client.models.generate_content(
                model=self.model or self._service().TEXT_MODEL,
                contents=[prompt],
            )
            value = (response.text or '').strip()
            if value.startswith('```') and value.endswith('```'):
                value = value[3:-3].strip()
                if value.casefold().startswith('json'):
                    value = value[4:].strip()
            parsed = json.loads(value)
        except Exception as exc:
            raise AIProviderError(f'Gemini engagement drafting failed: {exc}') from exc
        if not isinstance(parsed, dict) or not str(parsed.get('reply') or '').strip():
            raise AIProviderError('Gemini returned an invalid engagement draft.')
        return {
            'reply': str(parsed['reply']).strip(),
            'sentiment': str(parsed.get('sentiment') or 'UNKNOWN').upper(),
            'urgency': str(parsed.get('urgency') or 'NORMAL').upper(),
            'risk_flags': (
                parsed.get('risk_flags') if isinstance(parsed.get('risk_flags'), list) else []
            ),
        }

    def health_check(self) -> Dict[str, Any]:
        key = self.credentials or getattr(settings, 'GEMINI_API_KEY', '')
        if not key:
            return {'ok': False, 'detail': 'No Gemini API key configured.'}

        # Exact-model discovery is an authenticated, read-only request. Unlike
        # a prompt it consumes no generation tokens, and it catches a retired
        # or mistyped model before the first real generation fails.
        try:
            base_url = str(
                getattr(
                    settings,
                    'GEMINI_API_BASE_URL',
                    'https://generativelanguage.googleapis.com/v1beta',
                )
                or 'https://generativelanguage.googleapis.com/v1beta'
            ).rstrip('/')
            timeout = float(getattr(settings, 'AI_PROVIDER_HEALTH_TIMEOUT', 10.0))
            model = str(self.model or self.default_model).strip()
            model_path = model if model.startswith('models/') else f'models/{model}'
            response = httpx.get(
                f'{base_url}/{model_path}',
                headers={'x-goog-api-key': key},
                timeout=timeout,
            )
        except httpx.TimeoutException:
            return {'ok': False, 'detail': 'Gemini health check timed out.'}
        except httpx.HTTPError:
            return {'ok': False, 'detail': 'Gemini could not be reached.'}
        except (TypeError, ValueError):
            return {'ok': False, 'detail': 'Gemini health check is misconfigured.'}

        if response.status_code in (400, 401, 403):
            return {'ok': False, 'detail': 'Gemini authentication failed.'}
        if response.status_code == 404:
            return {'ok': False, 'detail': f'Gemini model {model} is not available.'}
        if response.status_code == 429:
            return {'ok': False, 'detail': 'Gemini health check was rate limited.'}
        if response.status_code >= 500:
            return {'ok': False, 'detail': 'Gemini is temporarily unavailable.'}
        if response.status_code >= 300:
            return {'ok': False, 'detail': 'Gemini health check failed.'}
        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = {}
        methods = payload.get('supportedGenerationMethods') if isinstance(payload, dict) else None
        if isinstance(methods, list) and 'generateContent' not in methods:
            return {
                'ok': False,
                'detail': f'Gemini model {model} cannot generate content.',
            }
        return {'ok': True, 'detail': f'Connected (model {model}).'}
