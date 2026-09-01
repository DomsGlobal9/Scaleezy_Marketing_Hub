"""
Generation as background work.

Video and multi-slide carousels are the two things that genuinely need this:
a poster comes back in seconds, but a video generation or a six-slide carousel
runs long enough to hit a gateway timeout, and today the user simply loses the
work when it does.

The request row is the progress record — `GeminiGenerationRequest` has had
PENDING/GENERATING/COMPLETED/FAILED and a `result` relation since the
beginning, and was never populated. The frontend polls it.
"""
import json
import logging

from django.tasks import task
from django.utils import timezone

logger = logging.getLogger(__name__)


@task
def generate_content(request_id: str):
    """Runs one generation and records the outcome on the request row."""
    from apps.gemini.models import GeminiGenerationRequest, GeminiGenerationResult
    from apps.context.services.generation import generate_marketing_payload

    try:
        request = GeminiGenerationRequest.objects.select_related('workspace').get(
            id=request_id
        )
    except GeminiGenerationRequest.DoesNotExist:
        logger.warning("Generation request %s vanished before it ran", request_id)
        return {'request': str(request_id), 'status': 'MISSING'}

    request.status = GeminiGenerationRequest.Status.GENERATING
    request.error_message = ''
    request.save(update_fields=['status', 'error_message'])

    # prompt_data is a TextField that predates this path, so the brief is
    # stored as JSON in it rather than adding a parallel column.
    try:
        brief = json.loads(request.prompt_data or '{}')
    except (TypeError, ValueError):
        brief = {}
    if not isinstance(brief, dict):
        brief = {}

    def checkpoint(state):
        # Successful expensive capabilities are durable before this is called.
        # Persist their compact state so a worker retry resumes only the
        # missing video/slide instead of buying completed work again.
        brief['production_state'] = state
        request.prompt_data = json.dumps(brief)
        request.save(update_fields=['prompt_data'])

    try:
        creative = brief.get('creative_direction') or {}
        if creative.get('selections'):
            from apps.brands.models import Brand
            from apps.context.services.creative_direction import resolve_creative_direction

            brand = Brand.objects.filter(workspace=request.workspace).order_by('-is_default').first()
            creative = resolve_creative_direction(
                request.workspace,
                brand,
                creative.get('selections'),
                layout=brief.get('layout', ''),
            )
            brief['creative_direction'] = creative
        routed = generate_marketing_payload(
            request.workspace, brief, progress=checkpoint
        )
        result_data = routed['payload']
    except Exception as exc:
        logger.exception("Generation %s failed", request_id)
        request.status = GeminiGenerationRequest.Status.FAILED
        request.error_message = str(exc)[:2000]
        request.save(update_fields=['status', 'error_message'])
        _queue_autopilot_followups(request)
        # Re-raised so the worker records the traceback and can retry.
        raise

    try:
        content_item = _persist(request, brief, result_data, routed)
        if content_item is None:
            raise RuntimeError("Generated content could not be saved.")

        GeminiGenerationResult.objects.update_or_create(
            generation_request=request,
            defaults={
                'generated_text': result_data.get('postDescription', ''),
                'generated_asset_url': (
                    result_data.get('videoUrl')
                    or result_data.get('posterImageUrl', '')
                    or ''
                ),
                'metadata': {
                    'postTitle': result_data.get('postTitle', ''),
                    'postHashtags': result_data.get('postHashtags', ''),
                    'videoUrl': result_data.get('videoUrl', ''),
                    'slideImageUrls': result_data.get('slideImageUrls') or [],
                    'provider': routed['provider'],
                    'provider_name': routed['provider_name'],
                    'brain_version': routed['brain_version'],
                    'creative_direction': {
                        'selection_count': (brief.get('creative_direction') or {}).get(
                            'selection_count', 0
                        ),
                        'layout': brief.get('layout', ''),
                    },
                    'completed_at': timezone.now().isoformat(),
                    'contentItemId': str(content_item.id),
                    'assetId': str(content_item.asset_id) if content_item.asset_id else None,
                },
            },
        )
    except Exception as exc:
        logger.exception("Generation %s could not be persisted", request_id)
        request.status = GeminiGenerationRequest.Status.FAILED
        request.error_message = str(exc)[:2000]
        request.save(update_fields=['status', 'error_message'])
        _queue_autopilot_followups(request)
        raise

    request.status = GeminiGenerationRequest.Status.COMPLETED
    request.provider = routed['provider']
    request.completed_at = timezone.now()
    request.save(update_fields=['status', 'provider', 'completed_at'])

    # A manually authorised autopilot run is event-driven: generation queues
    # the follow-up that moves its durable draft to the configured review
    # state. No recurring scheduler, hidden spend or external publish is
    # involved, and ordinary generation requests have no related rows.
    _queue_autopilot_followups(request)

    return {
        'request': str(request.id),
        'content_item': str(content_item.id) if content_item else None,
    }


def _queue_autopilot_followups(request):
    try:
        from apps.autopilot.models import AutopilotRun
        from apps.autopilot.tasks import execute_autopilot_run

        for run_id in request.autopilot_runs.filter(
            status=AutopilotRun.Status.WAITING_GENERATION
        ).values_list('id', flat=True):
            execute_autopilot_run.enqueue(str(run_id))
    except Exception:
        logger.exception(
            "Autopilot follow-up could not be queued for generation %s", request.pk
        )


def _persist(request, brief, result_data, routed):
    """
    Mirrors the synchronous path's persistence so a background generation
    produces exactly the same ContentItem a foreground one would.
    """
    from django.db import transaction

    from apps.brands.models import Brand
    from apps.content.models import ContentItem
    from apps.context.services.generation import create_generated_asset

    content_format = {
        'video': ContentItem.Format.VIDEO,
        'carousel': ContentItem.Format.CAROUSEL,
    }.get(str(brief.get('contentType', '')).lower(), ContentItem.Format.POSTER)

    slides = (
        result_data.get('slides')
        if str(brief.get('contentType', '')).lower() == 'carousel'
        else brief.get('slides')
    ) or []

    with transaction.atomic():
        asset = create_generated_asset(
            request.workspace, result_data, user=request.user
        )
        return ContentItem.objects.create(
            workspace=request.workspace,
            brand=Brand.objects.filter(workspace=request.workspace)
            .order_by('-is_default')
            .first(),
            asset=asset,
            content_format=content_format,
            status=ContentItem.Status.DRAFT,
            headline=(result_data.get('postTitle') or '')[:500],
            caption=result_data.get('postDescription') or '',
            hashtags=result_data.get('postHashtags') or '',
            cta=(brief.get('offer') or '')[:255],
            preview_url=(
                result_data.get('videoUrl')
                or result_data.get('posterImageUrl')
                or ''
            )[:1000],
            slides=slides if isinstance(slides, list) else [],
            ai_provider=(routed.get('provider') or 'UNKNOWN')[:100],
            ai_prompt=str(brief)[:5000],
            layout_plugin=str(brief.get('layout') or '')[:64],
            layout_config={
                'creative_direction': brief.get('creative_direction') or {},
                'generation_trace': {
                    'brain_version': routed.get('brain_version', ''),
                    **(routed.get('trace') or {}),
                },
            },
            created_by=request.user,
        )
