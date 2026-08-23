"""Provider-neutral, provenance-preserving Knowledge extraction."""
import hashlib
import io
import json
import re
import zipfile
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ai.models import Capability
from apps.ai.router import AIRouter
from apps.universal.enrichment import registrable_host, safe_fetch

from .models import BrandMemory, BrandSource

MAX_SOURCE_CHARS = 120_000
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_MEMORIES = 24

MEMORY_TYPES = [value for value, _label in BrandMemory.MemoryType.choices]
EXTRACTION_SCHEMA = {
    'type': 'object',
    'properties': {
        'memories': {
            'type': 'array',
            'maxItems': MAX_MEMORIES,
            'items': {
                'type': 'object',
                'properties': {
                    'memory_type': {'type': 'string', 'enum': MEMORY_TYPES},
                    'content': {'type': 'string'},
                    'normalized_key': {'type': 'string'},
                    'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'quote': {'type': 'string'},
                },
                'required': ['memory_type', 'content', 'normalized_key', 'confidence', 'quote'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['memories'],
    'additionalProperties': False,
}
EXTRACTION_INSTRUCTION = (
    'Extract only explicit brand/business facts from the supplied source. '
    'Return memories using the supplied schema. Every quote must be an exact '
    'substring of source_text. Do not infer, embellish or create a hard rule. '
    'Use normalized_key for a stable snake_case fact key when possible.'
)


class KnowledgeProcessingError(Exception):
    pass


def _download_storage(source: BrandSource) -> bytes:
    url = str(source.file_url or '')
    configured = urlsplit(
        str(getattr(settings, 'SUPABASE_URL', '')).replace('/rest/v1/', '')
    ).hostname
    if not url or not configured or urlsplit(url).hostname != configured:
        raise KnowledgeProcessingError('The uploaded file is not on configured storage.')
    try:
        with httpx.stream('GET', url, follow_redirects=False, timeout=30) as response:
            if response.status_code >= 300:
                raise KnowledgeProcessingError(
                    f'Could not read the uploaded file ({response.status_code}).'
                )
            chunks, received = [], 0
            for chunk in response.iter_bytes():
                received += len(chunk)
                if received > MAX_FILE_BYTES:
                    raise KnowledgeProcessingError('The uploaded document is too large to process.')
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise KnowledgeProcessingError('Could not reach file storage.') from exc
    return b''.join(chunks)


def _xml_text(payload: bytes, prefix: str) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = sorted(name for name in archive.namelist() if name.startswith(prefix))
        parts = []
        for name in names:
            raw = archive.read(name).decode('utf-8', errors='replace')
            parts.extend(re.findall(r'<(?:w:t|a:t)[^>]*>(.*?)</(?:w:t|a:t)>', raw, re.S))
    return ' '.join(re.sub(r'<[^>]+>', '', part) for part in parts)


def _file_text(source: BrandSource) -> str:
    payload = _download_storage(source)
    mime = (source.mime_type or '').casefold()
    name = (source.file_name or '').casefold()
    if mime.startswith('text/') or name.endswith(('.txt', '.md', '.csv', '.json')):
        return payload.decode('utf-8', errors='replace')
    if 'wordprocessingml' in mime or name.endswith('.docx'):
        return _xml_text(payload, 'word/')
    if 'presentationml' in mime or name.endswith('.pptx'):
        return _xml_text(payload, 'ppt/slides/')
    if mime == 'application/pdf' or name.endswith('.pdf'):
        try:
            from pypdf import PdfReader
            return '\n'.join((page.extract_text() or '') for page in PdfReader(io.BytesIO(payload)).pages)
        except ImportError as exc:
            raise KnowledgeProcessingError('PDF processing is not installed.') from exc
        except Exception as exc:
            raise KnowledgeProcessingError('The PDF could not be read.') from exc
    raise KnowledgeProcessingError(f'Unsupported document type: {source.mime_type or source.file_name}.')


def source_text(source: BrandSource) -> str:
    text = (source.raw_text or '').strip()
    if not text and source.source_url:
        host = registrable_host(source.source_url)
        if not host:
            raise KnowledgeProcessingError('The source URL is invalid.')
        try:
            text, _digest = safe_fetch(source.source_url, allowed_host=host)
        except Exception as exc:
            raise KnowledgeProcessingError(f'Could not read the source URL: {exc}') from exc
    if not text and source.file_url:
        text = _file_text(source)
    text = ' '.join(str(text).split())[:MAX_SOURCE_CHARS]
    if not text:
        raise KnowledgeProcessingError('This source contains no readable text.')
    return text


def _candidates(payload, text):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    rows = payload.get('memories') if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    haystack = text.casefold()
    out, seen = [], set()
    for row in rows[:MAX_MEMORIES]:
        if not isinstance(row, dict):
            continue
        quote = ' '.join(str(row.get('quote') or '').split())
        content = ' '.join(str(row.get('content') or '').split())
        memory_type = str(row.get('memory_type') or '').upper()
        key = re.sub(r'[^a-z0-9_]+', '_', str(row.get('normalized_key') or '').casefold()).strip('_')[:255]
        if not quote or quote.casefold() not in haystack or not content or memory_type not in MEMORY_TYPES:
            continue
        identity = (key, content.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        try:
            confidence = min(1.0, max(0.0, float(row.get('confidence', 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        out.append({
            'memory_type': memory_type,
            'content': content[:4000],
            'normalized_key': key or None,
            'confidence': confidence,
        })
    return out


def _metadata(source, **processing):
    value = dict(source.metadata or {})
    value['processing'] = {**dict(value.get('processing') or {}), **processing}
    return value


def process_source(source_id: str):
    source = BrandSource.objects.select_related('workspace', 'brand').get(pk=source_id)
    if source.status == BrandSource.SourceStatus.ARCHIVED:
        return {'source': str(source.pk), 'skipped': 'ARCHIVED'}
    try:
        text = source_text(source)
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        previous = dict((source.metadata or {}).get('processing') or {})
        if previous.get('content_hash') == digest and source.status in (
            BrandSource.SourceStatus.NEEDS_REVIEW, BrandSource.SourceStatus.READY
        ):
            return {'source': str(source.pk), 'skipped': 'UNCHANGED'}
        source.status = BrandSource.SourceStatus.PROCESSING
        source.metadata = _metadata(source, started_at=timezone.now().isoformat(), error='')
        source.save(update_fields=['status', 'metadata', 'updated_at'])
        result = AIRouter(source.workspace).dispatch(
            Capability.TEXT,
            {
                'task': 'EXTRACT',
                'schema_name': 'scaleezy_brand_memories',
                'instruction': EXTRACTION_INSTRUCTION,
                'response_schema': EXTRACTION_SCHEMA,
                'structured': {'source_text': text},
            },
        )
        rows = _candidates(result.get('raw') or result, text)
        provider = str(result.get('provider') or '')[:100]
        with transaction.atomic():
            locked = BrandSource.objects.select_for_update().get(pk=source.pk)
            if locked.status == BrandSource.SourceStatus.ARCHIVED:
                return {'source': str(source.pk), 'skipped': 'ARCHIVED'}
            if previous.get('content_hash') and previous.get('content_hash') != digest:
                BrandMemory.objects.filter(
                    source=locked, status=BrandMemory.MemoryStatus.CANDIDATE
                ).update(status=BrandMemory.MemoryStatus.SUPERSEDED)
            ids = []
            for row in rows:
                memory = BrandMemory.objects.filter(
                    source=locked,
                    status=BrandMemory.MemoryStatus.CANDIDATE,
                    normalized_key=row['normalized_key'],
                    content=row['content'],
                ).first()
                if memory is None:
                    memory = BrandMemory.objects.create(
                        workspace=locked.workspace,
                        brand=locked.brand,
                        source=locked,
                        extracted_by_provider=provider,
                        **row,
                    )
                ids.append(str(memory.pk))
            locked.raw_text = locked.raw_text or text
            locked.content_hash = digest
            locked.status = (
                BrandSource.SourceStatus.NEEDS_REVIEW if ids else BrandSource.SourceStatus.READY
            )
            locked.metadata = _metadata(
                locked,
                content_hash=digest,
                provider=provider,
                candidate_ids=ids,
                completed_at=timezone.now().isoformat(),
                error='',
            )
            locked.save(update_fields=['raw_text', 'content_hash', 'status', 'metadata', 'updated_at'])
        return {'source': str(source.pk), 'candidates': len(ids), 'provider': provider}
    except Exception as exc:
        BrandSource.objects.filter(pk=source.pk).exclude(
            status=BrandSource.SourceStatus.ARCHIVED
        ).update(
            status=BrandSource.SourceStatus.FAILED,
            metadata=_metadata(source, failed_at=timezone.now().isoformat(), error=str(exc)[:500]),
        )
        raise
