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
import logging
from concurrent.futures import ThreadPoolExecutor

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


class OutputRejected(Exception):
    """The provider returned something that fails deterministic checks."""


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
    text_context = build_generation_context(
        workspace, brand, TaskType.COPY, instruction=instruction,
    )
    image_context = build_generation_context(
        workspace, brand, TaskType.IMAGE, instruction=instruction,
    )
    text_brief = {**context_as_brief(text_context), **brief_extra}
    image_brief = {**context_as_brief(image_context), **brief_extra}

    router = AIRouter(workspace)
    trace = {
        'brain_version': text_context['brain_version'],
        'context_schema_version': CONTEXT_SCHEMA_VERSION,
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
            'metadata': raw.get('metadata', {}),
        },
    }


def retry_image(workspace, brand, brief_extra, *, instruction=''):
    """Retry ONLY the image capability. The copy that succeeded stays won."""
    context = build_generation_context(
        workspace, brand, TaskType.IMAGE, instruction=instruction,
    )
    brief = {**context_as_brief(context), **brief_extra}
    try:
        result = AIRouter(workspace).dispatch(Capability.IMAGE, brief)
        validate_output(Capability.IMAGE, result, context)
        return result
    except NoProviderAvailable as exc:
        raise NoProviderConfigured(str(exc)) from exc
