"""Provider-neutral analysis that writes reviewable AI signals only."""
import base64
import json
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ai.models import Capability
from apps.ai.router import AIRouter
from apps.universal.enrichment import registrable_host, safe_fetch

from .models import BrandInspiration, InspirationSignal, SignalCategory
from .services import record_ai_signal

MAX_MEDIA_BYTES = 15 * 1024 * 1024
MAX_SIGNALS = 16
CATEGORIES = [value for value, _label in SignalCategory.choices]
SENTIMENTS = [value for value, _label in InspirationSignal.Sentiment.choices]
SIGNAL_SCHEMA = {
    'type': 'object',
    'properties': {
        'signals': {
            'type': 'array',
            'maxItems': MAX_SIGNALS,
            'items': {
                'type': 'object',
                'properties': {
                    'category': {'type': 'string', 'enum': CATEGORIES},
                    'attribute': {'type': 'string'},
                    'value': {'type': 'string'},
                    'sentiment': {'type': 'string', 'enum': SENTIMENTS},
                    'weight': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                },
                'required': ['category', 'attribute', 'value', 'sentiment', 'weight', 'confidence'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['signals'],
    'additionalProperties': False,
}
INSTRUCTION = (
    'Analyze this creative reference and return JSON with a signals array using '
    'exactly the supplied schema. Describe visible or explicit creative traits only. '
    'Do not invent facts about the business. Treat the user annotation and focus areas '
    'as guidance. All results are suggestions pending human review.'
)


class InspirationAnalysisError(Exception):
    pass


def _stored_media_data(inspiration):
    url = str(inspiration.file_url or '')
    configured = urlsplit(
        str(getattr(settings, 'SUPABASE_URL', '')).replace('/rest/v1/', '')
    ).hostname
    if not url or not configured or urlsplit(url).hostname != configured:
        raise InspirationAnalysisError('The inspiration file is not on configured storage.')
    try:
        with httpx.stream('GET', url, follow_redirects=False, timeout=30) as response:
            if response.status_code >= 300:
                raise InspirationAnalysisError(
                    f'Could not read the inspiration file ({response.status_code}).'
                )
            chunks, received = [], 0
            for chunk in response.iter_bytes():
                received += len(chunk)
                if received > MAX_MEDIA_BYTES:
                    raise InspirationAnalysisError('The inspiration file is too large to analyze.')
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise InspirationAnalysisError('Could not reach file storage.') from exc
    mime = inspiration.mime_type or 'image/jpeg'
    return f"data:{mime};base64,{base64.b64encode(b''.join(chunks)).decode('ascii')}"


def _dispatch(inspiration):
    common = {
        'task': 'INSPIRATION_ANALYSIS',
        'instruction': INSTRUCTION,
        'response_schema': SIGNAL_SCHEMA,
        'annotation': inspiration.annotation,
        'focus_areas': inspiration.focus_areas,
        'usage_scope': inspiration.usage_scope,
    }
    mime = (inspiration.mime_type or '').casefold()
    kind = inspiration.inspiration_type
    if mime.startswith('video/') or kind in (
        BrandInspiration.InspirationType.VIDEO,
        BrandInspiration.InspirationType.REEL,
    ):
        return AIRouter(inspiration.workspace).dispatch(
            Capability.VIDEO_ANALYSIS,
            {**common, 'video_url': inspiration.file_url or inspiration.reference_url},
        )
    if mime.startswith('image/') or inspiration.file_url:
        return AIRouter(inspiration.workspace).dispatch(
            Capability.IMAGE_ANALYSIS,
            {**common, 'reference_image_base64': _stored_media_data(inspiration)},
        )

    text = inspiration.annotation or inspiration.title
    if inspiration.reference_url:
        host = registrable_host(inspiration.reference_url)
        if not host:
            raise InspirationAnalysisError('The inspiration URL is invalid.')
        try:
            fetched, _digest = safe_fetch(inspiration.reference_url, allowed_host=host)
            text = f'{text}\n{fetched}'
        except Exception as exc:
            raise InspirationAnalysisError(f'Could not read the inspiration URL: {exc}') from exc
    return AIRouter(inspiration.workspace).dispatch(
        Capability.TEXT,
        {
            **common,
            'task': 'EXTRACT',
            'schema_name': 'scaleezy_inspiration_signals',
            'structured': {'reference_text': text[:120000]},
        },
    )


def _rows(payload):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    rows = payload.get('signals') if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    out, seen = [], set()
    for row in rows[:MAX_SIGNALS]:
        if not isinstance(row, dict):
            continue
        category = str(row.get('category') or '').upper()
        sentiment = str(row.get('sentiment') or '').upper()
        attribute = ' '.join(str(row.get('attribute') or '').split())[:255]
        value = ' '.join(str(row.get('value') or '').split())[:2000]
        if category not in CATEGORIES or sentiment not in SENTIMENTS or not attribute or not value:
            continue
        identity = (category, attribute.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        try:
            weight = min(1.0, max(0.0, float(row.get('weight', 0.5))))
            confidence = min(1.0, max(0.0, float(row.get('confidence', 0))))
        except (TypeError, ValueError):
            continue
        out.append({
            'category': category,
            'attribute': attribute,
            'value': value,
            'sentiment': sentiment,
            'weight': weight,
            'confidence': confidence,
        })
    return out


def _metadata(inspiration, **analysis):
    value = dict(inspiration.metadata or {})
    value['analysis'] = {**dict(value.get('analysis') or {}), **analysis}
    return value


def analyze_inspiration(inspiration_id: str):
    inspiration = BrandInspiration.objects.select_related('workspace', 'brand').get(
        pk=inspiration_id
    )
    if inspiration.lifecycle_status == BrandInspiration.LifecycleStatus.ARCHIVED:
        return {'inspiration': str(inspiration.pk), 'skipped': 'ARCHIVED'}
    try:
        inspiration.analysis_status = BrandInspiration.AnalysisStatus.PROCESSING
        inspiration.metadata = _metadata(
            inspiration, started_at=timezone.now().isoformat(), error=''
        )
        inspiration.save(update_fields=['analysis_status', 'metadata', 'updated_at'])
        result = _dispatch(inspiration)
        payload = result.get('analysis') or result.get('raw') or result
        rows = _rows(payload)
        provider = str(result.get('provider') or '')[:100]
        with transaction.atomic():
            locked = BrandInspiration.objects.select_for_update().get(pk=inspiration.pk)
            if locked.lifecycle_status == BrandInspiration.LifecycleStatus.ARCHIVED:
                return {'inspiration': str(locked.pk), 'skipped': 'ARCHIVED'}
            ids = [
                str(record_ai_signal(inspiration=locked, provider=provider, **row).pk)
                for row in rows
            ]
            locked.analysis_status = (
                BrandInspiration.AnalysisStatus.NEEDS_REVIEW
                if ids else BrandInspiration.AnalysisStatus.READY
            )
            locked.metadata = _metadata(
                locked,
                provider=provider,
                signal_ids=ids,
                completed_at=timezone.now().isoformat(),
                error='',
            )
            locked.save(update_fields=['analysis_status', 'metadata', 'updated_at'])
        return {'inspiration': str(inspiration.pk), 'signals': len(ids), 'provider': provider}
    except Exception as exc:
        BrandInspiration.objects.filter(pk=inspiration.pk).exclude(
            lifecycle_status=BrandInspiration.LifecycleStatus.ARCHIVED
        ).update(
            analysis_status=BrandInspiration.AnalysisStatus.FAILED,
            metadata=_metadata(inspiration, failed_at=timezone.now().isoformat(), error=str(exc)[:500]),
        )
        raise
