"""
Generation through the gateway.

The chain the architecture requires, in one function:

    source systems -> Brand Brain -> Context Gateway -> AI Router -> adapter

Nothing here knows a provider exists. The router picks one from what the
workspace has routed, and the adapter turns the provider-neutral brief into
whatever that API wants.

The multi-capability path runs copy and imagery concurrently and keeps
whatever succeeded: a failed poster costs a poster, never the copy that was
already written. Retrying is per-capability for the same reason — repeating
work that succeeded is how failover turns into duplicate spend.
"""
import base64
import binascii
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.ai.endpoint_security import validate_public_https_endpoint
from apps.ai.models import Capability
from apps.ai.router import AIRouter, NoProviderAvailable

from .context_gateway import (
    CONTEXT_SCHEMA_VERSION,
    TaskType,
    build_generation_context,
    context_as_brief,
)

logger = logging.getLogger(__name__)

CAPABILITY_FOR_TASK = {
    TaskType.COPY: Capability.TEXT,
    TaskType.IMAGE: Capability.IMAGE,
    TaskType.VIDEO: Capability.VIDEO,
    TaskType.IMAGE_ANALYSIS: Capability.IMAGE_ANALYSIS,
}


class NoProviderConfigured(Exception):
    """The workspace has not routed a provider to this capability."""


def _require_spend_approved(workspace):
    """Refuse before any context is built or any thread is started.

    The router enforces the same rule, but `generate_copy_and_image` runs its
    dispatches inside workers that turn every exception into a FAILED trace
    entry — the refusal would surface as a vague provider failure. Checking
    here keeps it a clear, early refusal.
    """
    from apps.brands.services.approval import enforce_spend_approved

    enforce_spend_approved(workspace)


class OutputRejected(Exception):
    """The provider returned something that fails deterministic checks."""


MAX_GENERATED_IMAGE_BYTES = 20 * 1024 * 1024
MAX_GENERATED_VIDEO_BYTES = 250 * 1024 * 1024
MAX_MEDIA_REDIRECTS = 4


def _public_media_url(value: str) -> str:
    """Validate a signed media URL without discarding its query string."""
    raw = str(value or '').strip()
    parsed = urlsplit(raw)
    if parsed.username or parsed.password:
        raise OutputRejected("Generated media URL cannot contain credentials.")
    # The endpoint validator deliberately rejects queries because it protects
    # saved API base URLs. Provider media commonly uses signed query strings,
    # so validate the same host/path boundary and then retain the original URL.
    validation_target = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
    try:
        validate_public_https_endpoint(validation_target)
    except DjangoValidationError as exc:
        raise OutputRejected("Generated media URL must be public HTTPS.") from exc
    return raw


def _download_generated_media(url: str, *, max_bytes: int, expected_type: str):
    """Stream one provider file with redirect revalidation and a byte cap."""
    current = _public_media_url(url)
    for redirect_count in range(MAX_MEDIA_REDIRECTS + 1):
        try:
            with httpx.stream(
                'GET', current, timeout=60.0, follow_redirects=False
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if redirect_count >= MAX_MEDIA_REDIRECTS:
                        raise OutputRejected("Generated media redirected too many times.")
                    location = response.headers.get('location', '')
                    if not location:
                        raise OutputRejected("Generated media returned an invalid redirect.")
                    current = _public_media_url(urljoin(current, location))
                    continue
                response.raise_for_status()
                mime_type = response.headers.get('content-type', '').split(';', 1)[0].strip()
                if not mime_type.startswith(f'{expected_type}/'):
                    raise OutputRejected(
                        f"Generated media is not {expected_type}."
                    )
                advertised = response.headers.get('content-length')
                if advertised:
                    try:
                        if int(advertised) > max_bytes:
                            raise OutputRejected("Generated media exceeds the size limit.")
                    except ValueError:
                        pass
                chunks = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise OutputRejected("Generated media exceeds the size limit.")
                    chunks.append(chunk)
                payload = b''.join(chunks)
                if not payload:
                    raise OutputRejected("Generated media is empty.")
                return payload, mime_type
        except OutputRejected:
            raise
        except httpx.HTTPError as exc:
            raise OutputRejected(
                "Provider media could not be copied to durable storage."
            ) from exc
    raise OutputRejected("Generated media could not be retrieved.")


def persist_generated_image(workspace, result):
    """Replace provider-temporary image data with durable platform storage.

    Provider adapters normalize their output, but they do not own customer
    assets. Inline base64 and explicitly ephemeral hosted URLs are copied into
    the existing workspace storage boundary before any ContentItem records the
    result. Stable provider/CDN URLs are left alone for compatibility.
    """
    if not isinstance(result, dict):
        raise OutputRejected("Image provider returned no structured result.")

    image_url = str(result.get('image_url') or '')
    encoded = str(result.get('image_base64') or '')
    mime_type = str(result.get('mime_type') or '')

    if not encoded and image_url.startswith('data:'):
        try:
            header, encoded = image_url.split(',', 1)
            mime_type = mime_type or header[5:].split(';', 1)[0]
        except ValueError as exc:
            raise OutputRejected("Image provider returned an invalid data URL.") from exc

    try:
        if encoded:
            payload = base64.b64decode(encoded, validate=True)
        elif result.get('image_url_ephemeral'):
            payload, downloaded_type = _download_generated_media(
                image_url, max_bytes=MAX_GENERATED_IMAGE_BYTES, expected_type='image'
            )
            mime_type = mime_type or downloaded_type
        else:
            return result
    except (ValueError, binascii.Error) as exc:
        raise OutputRejected("Image provider returned invalid base64 data.") from exc
    except httpx.HTTPError as exc:
        raise OutputRejected("Provider image could not be copied to durable storage.") from exc

    if not payload or len(payload) > MAX_GENERATED_IMAGE_BYTES:
        raise OutputRejected("Generated image is empty or exceeds the 20 MB limit.")
    if not mime_type.startswith('image/'):
        raise OutputRejected("Generated media is not an image.")

    suffix = {
        'image/jpeg': 'jpg',
        'image/png': 'png',
        'image/webp': 'webp',
        'image/gif': 'gif',
    }.get(mime_type, 'img')
    filename = f'generated-{uuid.uuid4().hex}.{suffix}'
    upload = ContentFile(payload, name=filename)
    upload.content_type = mime_type

    from apps.marketing.services.storage import SupabaseStorageService

    stored = SupabaseStorageService.upload_and_describe(
        str(workspace.pk), upload, filename, prefix='generated'
    )
    return {
        **result,
        'image_url': stored['url'],
        'storage_path': stored['path'],
        'mime_type': mime_type,
        'file_size': len(payload),
        'file_name': filename,
        # Never carry the large provider payload beyond this boundary.
        'image_base64': '',
        'image_url_ephemeral': False,
    }


def persist_generated_video(workspace, result):
    """Copy provider video output into the workspace's durable storage."""
    if not isinstance(result, dict):
        raise OutputRejected("Video provider returned no structured result.")

    video_url = str(result.get('video_url') or '')
    encoded = str(result.get('video_base64') or '')
    mime_type = str(result.get('mime_type') or '')

    if not encoded and video_url.startswith('data:'):
        try:
            header, encoded = video_url.split(',', 1)
            mime_type = mime_type or header[5:].split(';', 1)[0]
        except ValueError as exc:
            raise OutputRejected("Video provider returned an invalid data URL.") from exc

    try:
        if encoded:
            payload = base64.b64decode(encoded, validate=True)
        elif video_url:
            # Unlike stable image CDN URLs, video delivery URLs are commonly
            # short-lived. Always copy the completed clip before recording it.
            payload, downloaded_type = _download_generated_media(
                video_url, max_bytes=MAX_GENERATED_VIDEO_BYTES, expected_type='video'
            )
            mime_type = mime_type or downloaded_type
        else:
            raise OutputRejected("Video provider returned no video.")
    except (ValueError, binascii.Error) as exc:
        raise OutputRejected("Video provider returned invalid base64 data.") from exc

    if not payload or len(payload) > MAX_GENERATED_VIDEO_BYTES:
        raise OutputRejected("Generated video is empty or exceeds the 250 MB limit.")
    if not mime_type.startswith('video/'):
        raise OutputRejected("Generated media is not a video.")

    suffix = {
        'video/mp4': 'mp4',
        'video/webm': 'webm',
        'video/quicktime': 'mov',
    }.get(mime_type, 'video')
    filename = f'generated-{uuid.uuid4().hex}.{suffix}'
    upload = ContentFile(payload, name=filename)
    upload.content_type = mime_type

    from apps.marketing.services.storage import SupabaseStorageService

    stored = SupabaseStorageService.upload_and_describe(
        str(workspace.pk), upload, filename, prefix='generated'
    )
    return {
        **result,
        'video_url': stored['url'],
        'storage_path': stored['path'],
        'mime_type': mime_type,
        'file_size': len(payload),
        'file_name': filename,
        'video_base64': '',
        'video_url_ephemeral': False,
    }


def intelligence_in_force(brand, brain_version):
    """Which rules and preferences a generation actually read.

    A trace names the brain by its fingerprint, but a brain is recompiled in
    place, so a fingerprint alone cannot be resolved back to the rows behind
    it a week later. Recording the ids at generation time is what makes "how
    often has this rule been used" answerable at all.

    Only recorded while the brand's brain is still the one that was used —
    if a recompile landed in between, the ids on disk are no longer the ids
    that produced this item, and a plausible wrong answer is worse than none.

    Shared by the synchronous view and the background task, so a poster made
    on the queue is exactly as attributable as one made in the request.
    """
    brain = getattr(brand, 'creative_brain', None) or {}
    if not brain_version or brain.get('brain_version') != brain_version:
        return {}
    sources = brain.get('sources') or {}
    return {
        'rule_ids': list(sources.get('rule_ids') or []),
        'preference_ids': list(sources.get('preference_ids') or []),
    }


def create_generated_asset(workspace, result_data, *, user=None):
    """Create the durable MarketingAsset described by a normalized payload."""
    metadata = result_data.get('metadata') or {}
    video = metadata.get('generated_video') or {}
    image = metadata.get('generated_image') or {}
    media = video if isinstance(video, dict) and video.get('video_url') else image
    if not isinstance(media, dict):
        return None
    media_url = media.get('video_url') or media.get('image_url')
    if not media_url:
        return None

    from apps.marketing.models import MarketingAsset

    return MarketingAsset.objects.create(
        workspace=workspace,
        asset_type=(
            MarketingAsset.AssetType.VIDEO
            if media is video else MarketingAsset.AssetType.IMAGE
        ),
        file_name=str(media.get('file_name') or 'generated-media')[:255],
        file_url=str(media_url)[:1000],
        storage_path=str(media.get('storage_path') or '')[:1000] or None,
        mime_type=str(media.get('mime_type') or '')[:100] or None,
        file_size=media.get('file_size') or None,
        duration=media.get('duration') or None,
        source=MarketingAsset.Source.AI_GENERATED,
        created_by=user,
    )


#: Cheap deterministic checks per capability. No extra LLM call — these catch
#: the failures that need no judgement: empty output, missing fields, copy
#: that names something a hard rule forbids.
REQUIRED_FIELDS = {
    Capability.TEXT: ('headline',),
    Capability.IMAGE: ('image_url',),
    Capability.VIDEO: ('video_url',),
}


def validate_output(capability, result, context):
    """Refuse obviously broken or rule-breaking output before accepting it."""
    if not isinstance(result, dict):
        raise OutputRejected(f"{capability} returned no structured result.")

    for field in REQUIRED_FIELDS.get(capability, ()):
        raw = result.get('raw') or {}
        inline_field = {
            Capability.IMAGE: 'image_base64',
            Capability.VIDEO: 'video_base64',
        }.get(capability, '')
        if not (
            result.get(field)
            or (inline_field and result.get(inline_field))
            or raw.get('postTitle' if field == 'headline' else field)
        ):
            raise OutputRejected(f"{capability} output is missing '{field}'.")

    if capability == Capability.TEXT:
        text_blob = ' '.join(
            str(result.get(key, '')) for key in ('headline', 'caption', 'hashtags')
        ).casefold()
        for rule in context.get('hard_rules', []):
            structured = rule.get('text', '')
            # Only the "never X" shape is deterministically checkable: if a
            # hard rule names a forbidden literal and the copy contains it,
            # no judgement is needed to reject.
            lowered = structured.casefold()
            if lowered.startswith('never ') and len(lowered) > 6:
                forbidden = lowered.removeprefix('never ').strip(' .')
                # Compare on a distinctive tail phrase to avoid false hits on
                # common words.
                if len(forbidden) >= 12 and forbidden in text_blob:
                    raise OutputRejected(
                        f"Output violates a hard rule: {rule.get('text', '')!r}"
                    )
    return result


def generate_with_context(workspace, brand, task_type=TaskType.COPY, *, instruction='',
                          channel='', content_format='', objective='',
                          content_item_id=None):
    """Build brand context, then dispatch it through the router.

    Returns the provider result alongside the context that produced it, so a
    generation can always be explained by the brain version it was cut from.
    """
    _require_spend_approved(workspace)
    context = build_generation_context(
        workspace, brand, task_type,
        instruction=instruction, channel=channel,
        content_format=content_format, objective=objective,
    )
    brief = context_as_brief(context)
    capability = CAPABILITY_FOR_TASK[task_type]

    try:
        result = AIRouter(workspace).dispatch(capability, brief, content_item_id)
    except NoProviderAvailable as exc:
        # Reported as unavailable rather than dressed up as an empty success:
        # a workspace with no provider routed has not generated anything.
        raise NoProviderConfigured(str(exc)) from exc

    validate_output(capability, result, context)
    if capability == Capability.IMAGE:
        result = persist_generated_image(workspace, result)

    return {
        'result': result,
        'brain_version': context['brain_version'],
        'task_type': task_type,
        'context_summary': {
            'hard_rules': len(context['hard_rules']),
            'soft_rules': len(context['soft_rules']),
            'preferences': len(context['preferences']),
            'verified_truth': len(context['verified_truth']),
            'unresolved_conflicts': context['unresolved_conflict_count'],
        },
    }


def generate_copy_and_image(workspace, brand, brief_extra, *, instruction=''):
    """Copy and imagery, concurrently, each surviving the other's failure.

    Returns {'text': …, 'image': …, 'trace': …} where either capability may be
    None with its error recorded in the trace. The caller keeps whatever
    succeeded and retries only what failed — `retry_image()` exists for
    exactly that, so a poster retry can never regenerate the copy.

    Task-specific contexts are cut per capability (copy does not carry the
    layout grid; the image does not carry the objection list); both come from
    the same brain version, so the pair is still one coherent generation.
    """
    # Primed here, on the main thread, before any context is built or worker
    # started: the workers' dispatch() calls then skip the brands read.
    router = AIRouter(workspace)
    router.require_spend_approved()

    text_context = build_generation_context(
        workspace, brand, TaskType.COPY, instruction=instruction,
    )
    image_context = build_generation_context(
        workspace, brand, TaskType.IMAGE, instruction=instruction,
    )
    # The gateway's cut wins for the keys it owns: the synchronous endpoint's
    # brief_extra carries a COPY-task brand_context, and merging it last used
    # to clobber the IMAGE brief's own lines — including the no-text
    # constraint, which then never reached the image provider on the main
    # path. Campaign fields only exist in brief_extra, so they survive.
    text_brief = {**brief_extra, **context_as_brief(text_context)}
    image_brief = {**brief_extra, **context_as_brief(image_context)}

    trace = {
        'brain_version': text_context['brain_version'],
        'context_schema_version': CONTEXT_SCHEMA_VERSION,
        'universal_version': text_context.get('universal_version', ''),
        'learned_pattern_version': text_context.get('learned_pattern_version', ''),
        'capabilities': {},
    }

    def run(capability, brief, context):
        try:
            result = router.dispatch(capability, brief)
            validate_output(capability, result, context)
            trace['capabilities'][capability] = {
                'status': 'OK',
                'provider': result.get('provider', ''),
                'latency_ms': result.get('latency_ms'),
            }
            return result
        except Exception as exc:
            trace['capabilities'][capability] = {
                'status': 'FAILED',
                'error': str(exc)[:300],
                'error_type': type(exc).__name__,
            }
            return None

    # When one provider serves BOTH capabilities and its text result already
    # carries the poster, a concurrent IMAGE dispatch would repeat the same
    # upstream call - concurrency as pure duplicate spend. One call is also
    # strictly faster than two. Decided per-request from the router's own
    # resolution, never from a provider name.
    text_primary = router.primary_adapter(Capability.TEXT)
    image_primary = router.primary_adapter(Capability.IMAGE)
    combined = (
        text_primary is not None
        and image_primary is not None
        and text_primary.key == image_primary.key
        and getattr(text_primary, 'yields_poster_with_text', False)
    )

    if combined:
        text = run(Capability.TEXT, text_brief, text_context)
        image = None
        if text is not None:
            poster = (text.get('raw') or {}).get('posterImageUrl', '')
            if poster:
                image = {'image_url': poster, 'provider': text.get('provider', '')}
                trace['capabilities'][Capability.IMAGE] = {
                    'status': 'OK', 'combined_with_text': True,
                    'provider': text.get('provider', ''),
                }
    else:
        # Two independent providers, two independent calls, at the same time:
        # nothing shared but the trace dict, which each branch writes under
        # its own key.
        with ThreadPoolExecutor(max_workers=2) as pool:
            text_future = pool.submit(run, Capability.TEXT, text_brief, text_context)
            image_future = pool.submit(run, Capability.IMAGE, image_brief, image_context)
            text = text_future.result()
            image = image_future.result()

        # A failed IMAGE dispatch does not throw away a poster the TEXT call
        # happened to return - partial success keeps everything that exists.
        if image is None and text is not None:
            poster = (text.get('raw') or {}).get('posterImageUrl', '')
            if poster:
                image = {'image_url': poster, 'provider': text.get('provider', '')}
                trace['capabilities'][Capability.IMAGE] = {
                    'status': 'OK', 'fallback_from_text': True,
                    'provider': text.get('provider', ''),
                }

    if image is not None:
        try:
            image = persist_generated_image(workspace, image)
        except Exception as exc:
            # Storage is part of completing an image. Keep successfully
            # generated copy, but never call a temporary/truncated image done.
            trace['capabilities'][Capability.IMAGE] = {
                'status': 'FAILED',
                'error': str(exc)[:300],
                'error_type': type(exc).__name__,
            }
            image = None

    if text is None:
        failure = trace['capabilities'].get(Capability.TEXT, {})
        if failure.get('error_type') == 'NoProviderAvailable':
            # Honest unavailability outranks partial success: with no copy
            # there is no generation to be partial about.
            raise NoProviderConfigured(failure.get('error', 'No provider routed.'))

    return {'text': text, 'image': image, 'trace': trace}


def _compact_text_result(result):
    """Checkpoint only the provider-neutral copy, never a large raw payload."""
    raw = result.get('raw') or {}
    return {
        'headline': result.get('headline') or raw.get('postTitle', ''),
        'caption': result.get('caption') or raw.get('postDescription', ''),
        'hashtags': result.get('hashtags') or raw.get('postHashtags', ''),
        'provider': result.get('provider', ''),
        'provider_name': result.get('provider_name', ''),
        'latency_ms': result.get('latency_ms'),
    }


def _production_state(brief):
    state = brief.get('production_state') or {}
    return state if isinstance(state, dict) else {}


def _save_progress(progress, state):
    if progress is not None:
        progress(state)


def generate_video_and_copy(workspace, brand, brief_extra, *, instruction='', progress=None):
    """Generate copy plus one real VIDEO capability result with checkpoints."""
    router = AIRouter(workspace)
    router.require_spend_approved()
    text_context = build_generation_context(
        workspace, brand, TaskType.COPY, instruction=instruction,
    )
    video_context = build_generation_context(
        workspace, brand, TaskType.VIDEO, instruction=instruction,
    )
    state = _production_state(brief_extra)
    trace = {
        'brain_version': text_context['brain_version'],
        'context_schema_version': CONTEXT_SCHEMA_VERSION,
        'universal_version': text_context.get('universal_version', ''),
        'learned_pattern_version': text_context.get('learned_pattern_version', ''),
        'capabilities': {},
    }

    text = state.get('text') if isinstance(state.get('text'), dict) else None
    if text:
        trace['capabilities'][Capability.TEXT] = {
            'status': 'OK', 'resumed': True, 'provider': text.get('provider', ''),
        }
    else:
        text = router.dispatch(
            Capability.TEXT,
            {**context_as_brief(text_context), **brief_extra},
        )
        validate_output(Capability.TEXT, text, text_context)
        text = _compact_text_result(text)
        state['text'] = text
        _save_progress(progress, state)
        trace['capabilities'][Capability.TEXT] = {
            'status': 'OK', 'provider': text.get('provider', ''),
            'latency_ms': text.get('latency_ms'),
        }

    video = state.get('video') if isinstance(state.get('video'), dict) else None
    if video and video.get('video_url'):
        trace['capabilities'][Capability.VIDEO] = {
            'status': 'OK', 'resumed': True, 'provider': video.get('provider', ''),
        }
    else:
        video_brief = {
            **context_as_brief(video_context),
            **brief_extra,
            'generated_copy': {
                key: text.get(key, '') for key in ('headline', 'caption', 'hashtags')
            },
            'instruction': (
                str(brief_extra.get('video_script') or '').strip()
                or instruction
            )[:4000],
        }
        try:
            video = router.dispatch(Capability.VIDEO, video_brief)
        except NoProviderAvailable as exc:
            raise NoProviderConfigured(str(exc)) from exc
        validate_output(Capability.VIDEO, video, video_context)
        video = persist_generated_video(workspace, video)
        state['video'] = {
            key: video.get(key)
            for key in (
                'video_url', 'storage_path', 'mime_type', 'file_size', 'file_name',
                'duration', 'provider', 'provider_name', 'latency_ms',
            )
            if video.get(key) not in (None, '')
        }
        video = state['video']
        _save_progress(progress, state)
        trace['capabilities'][Capability.VIDEO] = {
            'status': 'OK', 'provider': video.get('provider', ''),
            'latency_ms': video.get('latency_ms'),
        }
    return {'text': text, 'video': video, 'trace': trace, 'production_state': state}


def generate_carousel_and_copy(
    workspace, brand, brief_extra, *, instruction='', progress=None
):
    """Generate every ordered carousel slide through IMAGE with resume state."""
    slides = brief_extra.get('slides') or []
    if not isinstance(slides, list) or not slides:
        raise OutputRejected("A carousel requires at least one slide.")
    if any(not isinstance(row, dict) for row in slides):
        raise OutputRejected("Every carousel slide must be an object.")

    router = AIRouter(workspace)
    router.require_spend_approved()
    # Prime the immutable route snapshot on the main thread before concurrent
    # slide calls, matching the existing poster accelerator's safety pattern.
    router._routing_snapshot()
    text_context = build_generation_context(
        workspace, brand, TaskType.COPY, instruction=instruction,
    )
    image_context = build_generation_context(
        workspace, brand, TaskType.IMAGE, instruction=instruction,
    )
    state = _production_state(brief_extra)
    slide_state = state.get('slides')
    if not isinstance(slide_state, dict):
        slide_state = {}
        state['slides'] = slide_state
    trace = {
        'brain_version': text_context['brain_version'],
        'context_schema_version': CONTEXT_SCHEMA_VERSION,
        'universal_version': text_context.get('universal_version', ''),
        'learned_pattern_version': text_context.get('learned_pattern_version', ''),
        'capabilities': {},
        'carousel_slides': [],
    }

    text = state.get('text') if isinstance(state.get('text'), dict) else None
    if text:
        trace['capabilities'][Capability.TEXT] = {
            'status': 'OK', 'resumed': True, 'provider': text.get('provider', ''),
        }
    else:
        text = router.dispatch(
            Capability.TEXT,
            {**context_as_brief(text_context), **brief_extra},
        )
        validate_output(Capability.TEXT, text, text_context)
        text = _compact_text_result(text)
        state['text'] = text
        _save_progress(progress, state)
        trace['capabilities'][Capability.TEXT] = {
            'status': 'OK', 'provider': text.get('provider', ''),
            'latency_ms': text.get('latency_ms'),
        }

    ordered = []
    pending = []
    for index, raw_slide in enumerate(slides):
        position = int(raw_slide.get('position') or index + 1)
        description = str(raw_slide.get('description') or '').strip()
        key = str(position)
        saved = slide_state.get(key)
        if isinstance(saved, dict) and saved.get('image_url'):
            ordered.append((position, description, saved))
            trace['carousel_slides'].append({
                'position': position, 'status': 'OK', 'resumed': True,
                'provider': saved.get('provider', ''),
            })
        else:
            pending.append((position, description))

    def generate_slide(position, description):
        slide_brief = {
            **context_as_brief(image_context),
            **brief_extra,
            'contentType': 'carousel_slide',
            'slide': {
                'position': position,
                'count': len(slides),
                'description': description,
            },
            'instruction': (
                f"Create slide {position} of {len(slides)}. {description}"
            )[:2400],
        }
        image = router.dispatch(Capability.IMAGE, slide_brief)
        validate_output(Capability.IMAGE, image, image_context)
        image = persist_generated_image(workspace, image)
        return {
            key: image.get(key)
            for key in (
                'image_url', 'storage_path', 'mime_type', 'file_size', 'file_name',
                'provider', 'provider_name', 'latency_ms',
            )
            if image.get(key) not in (None, '')
        }

    failures = []
    if pending:
        with ThreadPoolExecutor(max_workers=min(4, len(pending))) as pool:
            futures = {
                pool.submit(generate_slide, position, description): (position, description)
                for position, description in pending
            }
            for future in as_completed(futures):
                position, description = futures[future]
                try:
                    image = future.result()
                    slide_state[str(position)] = image
                    ordered.append((position, description, image))
                    trace['carousel_slides'].append({
                        'position': position, 'status': 'OK',
                        'provider': image.get('provider', ''),
                        'latency_ms': image.get('latency_ms'),
                    })
                    _save_progress(progress, state)
                except Exception as exc:
                    failures.append((position, exc))
                    trace['carousel_slides'].append({
                        'position': position, 'status': 'FAILED',
                        'error': str(exc)[:300], 'error_type': type(exc).__name__,
                    })

    trace['carousel_slides'].sort(key=lambda row: row['position'])
    if failures:
        if len(failures) == len(pending) and all(
            isinstance(exc, NoProviderAvailable) for _position, exc in failures
        ):
            raise NoProviderConfigured(
                "No AI provider is enabled for IMAGE in this workspace."
            )
        failed_positions = ', '.join(str(position) for position, _ in sorted(failures))
        raise OutputRejected(
            f"Carousel slide generation failed for position(s) {failed_positions}. "
            "Completed slides were saved and will not be regenerated on retry."
        )

    ordered.sort(key=lambda row: row[0])
    generated_slides = [
        {
            'position': position,
            'description': description,
            'preview_url': image['image_url'],
            'provider': image.get('provider', ''),
            'storage_path': image.get('storage_path', ''),
        }
        for position, description, image in ordered
    ]
    trace['capabilities'][Capability.IMAGE] = {
        'status': 'OK', 'count': len(generated_slides),
    }
    return {
        'text': text,
        'slides': generated_slides,
        'slide_media': [image for _position, _description, image in ordered],
        'trace': trace,
        'production_state': state,
    }


def recent_headlines(workspace, limit=6):
    """
    The newest distinct headlines this workspace has generated.

    Fed into the brief so the copy model knows what it must NOT say again;
    trimmed hard because these ride inside a prompt.
    """
    from apps.content.models import ContentItem

    rows = (
        ContentItem.objects.filter(workspace=workspace)
        .exclude(headline='')
        .order_by('-created_at')
        .values_list('headline', flat=True)[: limit * 2]
    )
    return list(dict.fromkeys(str(h)[:120] for h in rows if str(h).strip()))[:limit]


def generate_marketing_payload(
    workspace, brief, *, instruction='', progress=None, brand=None
):
    """Return the legacy marketing payload without choosing a vendor.

    This is the shared boundary used by both foreground and queued generation.
    Product code asks for TEXT and IMAGE; only AIRouter and adapters know which
    provider supplies them.
    """
    from apps.brands.models import Brand

    if brand is None:
        brand = Brand.objects.filter(workspace=workspace).order_by('-is_default').first()
    elif brand.workspace_id != workspace.pk:
        raise OutputRejected('The selected brand does not belong to this workspace.')
    content_type = str(brief.get('contentType') or '').strip().lower()
    if brand is None:
        if content_type in {'video', 'carousel'}:
            raise OutputRejected(
                f"A brand is required before {content_type} production can start."
            )
        text = AIRouter(workspace).dispatch(Capability.TEXT, brief)
        raw = text.get('raw') or {}
        return {
            'provider': text.get('provider', ''),
            'provider_name': text.get('provider_name', ''),
            'brain_version': '',
            'trace': {'capabilities': {Capability.TEXT: {'status': 'OK'}}},
            'payload': {
                'postTitle': text.get('headline') or raw.get('postTitle', ''),
                'postDescription': text.get('caption') or raw.get('postDescription', ''),
                'postHashtags': text.get('hashtags') or raw.get('postHashtags', ''),
                'posterImageUrl': raw.get('posterImageUrl', ''),
                'metadata': raw.get('metadata', {}),
            },
        }

    effective_instruction = instruction or str(brief.get('campaign_name', ''))[:500]

    # What this workspace's last posters already said. Without it, two similar
    # briefs produce the same headline and concept back to back — reviewers see
    # "the same poster" — because the model has no idea what it said last time.
    recent = recent_headlines(workspace)
    if recent and 'recent_headlines' not in brief:
        brief = {**brief, 'recent_headlines': recent}

    if content_type == 'video':
        outcome = generate_video_and_copy(
            workspace, brand, brief,
            instruction=effective_instruction, progress=progress,
        )
        text = outcome['text'] or {}
        video = outcome['video'] or {}
        return {
            'provider': text.get('provider', '') or video.get('provider', ''),
            'provider_name': text.get('provider_name', '') or video.get('provider_name', ''),
            'brain_version': outcome['trace'].get('brain_version', ''),
            'trace': outcome['trace'],
            'payload': {
                'postTitle': text.get('headline', ''),
                'postDescription': text.get('caption', ''),
                'postHashtags': text.get('hashtags', ''),
                'posterImageUrl': '',
                'videoUrl': video.get('video_url', ''),
                'slideImageUrls': [],
                'metadata': {'generated_video': video},
            },
        }
    if content_type == 'carousel':
        outcome = generate_carousel_and_copy(
            workspace, brand, brief,
            instruction=effective_instruction, progress=progress,
        )
        text = outcome['text'] or {}
        media = outcome['slide_media']
        first = media[0] if media else {}
        return {
            'provider': text.get('provider', '') or first.get('provider', ''),
            'provider_name': text.get('provider_name', '') or first.get('provider_name', ''),
            'brain_version': outcome['trace'].get('brain_version', ''),
            'trace': outcome['trace'],
            'payload': {
                'postTitle': text.get('headline', ''),
                'postDescription': text.get('caption', ''),
                'postHashtags': text.get('hashtags', ''),
                'posterImageUrl': first.get('image_url', ''),
                'videoUrl': '',
                'slideImageUrls': [row['preview_url'] for row in outcome['slides']],
                'slides': outcome['slides'],
                'metadata': {
                    'generated_image': first,
                    'carousel_slides': media,
                },
            },
        }

    outcome = generate_copy_and_image(
        workspace, brand, brief, instruction=effective_instruction,
    )
    text = outcome['text'] or {}
    image = outcome['image'] or {}
    raw = text.get('raw') or {}
    if not text:
        failure = outcome['trace']['capabilities'].get(Capability.TEXT, {})
        raise OutputRejected(failure.get('error', 'Generation produced no copy.'))

    return {
        'provider': text.get('provider', ''),
        'provider_name': text.get('provider_name', ''),
        'brain_version': outcome['trace'].get('brain_version', ''),
        'trace': outcome['trace'],
        'payload': {
            'postTitle': text.get('headline') or raw.get('postTitle', ''),
            'postDescription': text.get('caption') or raw.get('postDescription', ''),
            'postHashtags': text.get('hashtags') or raw.get('postHashtags', ''),
            'posterImageUrl': image.get('image_url', ''),
            'videoUrl': '',
            'slideImageUrls': [],
            'metadata': {
                **(raw.get('metadata', {}) or {}),
                **({'generated_image': {
                    key: image.get(key)
                    for key in ('image_url', 'storage_path', 'mime_type', 'file_size', 'file_name')
                    if image.get(key) not in (None, '')
                }} if image else {}),
            },
        },
    }


def retry_image(workspace, brand, brief_extra, *, instruction=''):
    """Retry ONLY the image capability. The copy that succeeded stays won."""
    _require_spend_approved(workspace)
    context = build_generation_context(
        workspace, brand, TaskType.IMAGE, instruction=instruction,
    )
    brief = {**context_as_brief(context), **brief_extra}
    try:
        result = AIRouter(workspace).dispatch(Capability.IMAGE, brief)
        validate_output(Capability.IMAGE, result, context)
        return persist_generated_image(workspace, result)
    except NoProviderAvailable as exc:
        raise NoProviderConfigured(str(exc)) from exc


def generate_copy_only(workspace, brand, brief_extra, *, instruction=''):
    """Regenerate ONLY the words. The photograph the reviewer liked stays won.

    The surgical half of request-edits: when every flagged element is about
    copy, spending an image generation — and changing a picture the reviewer
    did not complain about — would be worse than doing nothing."""
    _require_spend_approved(workspace)
    context = build_generation_context(
        workspace, brand, TaskType.COPY, instruction=instruction,
    )
    brief = {**brief_extra, **context_as_brief(context)}
    try:
        result = AIRouter(workspace).dispatch(Capability.TEXT, brief)
        validate_output(Capability.TEXT, result, context)
    except NoProviderAvailable as exc:
        raise NoProviderConfigured(str(exc)) from exc
    raw = result.get('raw') or {}
    return {
        'postTitle': result.get('headline') or raw.get('postTitle', ''),
        'postDescription': result.get('caption') or raw.get('postDescription', ''),
        'postHashtags': result.get('hashtags') or raw.get('postHashtags', ''),
    }
