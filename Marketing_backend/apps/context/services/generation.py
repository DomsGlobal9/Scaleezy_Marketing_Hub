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
from concurrent.futures import ThreadPoolExecutor

import httpx
from django.core.files.base import ContentFile

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
            if not image_url.startswith('https://'):
                raise OutputRejected("Ephemeral image URL must use HTTPS.")
            response = httpx.get(image_url, timeout=30.0, follow_redirects=True)
            response.raise_for_status()
            payload = response.content
            mime_type = mime_type or response.headers.get('content-type', '').split(';', 1)[0]
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
    image = metadata.get('generated_image') or {}
    if not isinstance(image, dict) or not image.get('image_url'):
        return None

    from apps.marketing.models import MarketingAsset

    return MarketingAsset.objects.create(
        workspace=workspace,
        asset_type=MarketingAsset.AssetType.IMAGE,
        file_name=str(image.get('file_name') or 'generated-image')[:255],
        file_url=str(image['image_url'])[:1000],
        storage_path=str(image.get('storage_path') or '')[:1000] or None,
        mime_type=str(image.get('mime_type') or '')[:100] or None,
        file_size=image.get('file_size') or None,
        source=MarketingAsset.Source.AI_GENERATED,
        created_by=user,
    )


#: Cheap deterministic checks per capability. No extra LLM call — these catch
#: the failures that need no judgement: empty output, missing fields, copy
#: that names something a hard rule forbids.
REQUIRED_FIELDS = {
    Capability.TEXT: ('headline',),
    Capability.IMAGE: ('image_url',),
}


def validate_output(capability, result, context):
    """Refuse obviously broken or rule-breaking output before accepting it."""
    if not isinstance(result, dict):
        raise OutputRejected(f"{capability} returned no structured result.")

    for field in REQUIRED_FIELDS.get(capability, ()):
        raw = result.get('raw') or {}
        if not (result.get(field) or raw.get('postTitle' if field == 'headline' else field)):
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
    text_brief = {**context_as_brief(text_context), **brief_extra}
    image_brief = {**context_as_brief(image_context), **brief_extra}

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


def generate_marketing_payload(workspace, brief, *, instruction=''):
    """Return the legacy marketing payload without choosing a vendor.

    This is the shared boundary used by both foreground and queued generation.
    Product code asks for TEXT and IMAGE; only AIRouter and adapters know which
    provider supplies them.
    """
    from apps.brands.models import Brand

    brand = Brand.objects.filter(workspace=workspace).order_by('-is_default').first()
    if brand is None:
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

    outcome = generate_copy_and_image(
        workspace,
        brand,
        brief,
        instruction=instruction or str(brief.get('campaign_name', ''))[:500],
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
