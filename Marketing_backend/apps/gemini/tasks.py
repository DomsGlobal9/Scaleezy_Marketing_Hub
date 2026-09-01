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

    if request.status == GeminiGenerationRequest.Status.COMPLETED:
        # A re-delivered or retried task for work that already finished. Run
        # again and it would spend provider money a second time and leave a
        # second draft; the honest response is to do nothing. Checked BEFORE
        # the status is marked GENERATING, or the check could never be true.
        logger.info("Generation %s already completed; skipping re-run", request_id)
        return {'request': str(request_id), 'status': 'ALREADY_COMPLETED'}

    request.status = GeminiGenerationRequest.Status.GENERATING
    request.save(update_fields=['status'])

    # prompt_data is a TextField that predates this path, so the brief is
    # stored as JSON in it rather than adding a parallel column.
    try:
        brief = json.loads(request.prompt_data or '{}')
    except (TypeError, ValueError):
        brief = {}
    if not isinstance(brief, dict):
        brief = {}

    try:
        routed = generate_marketing_payload(request.workspace, brief)
        result_data = routed['payload']
    except Exception as exc:
        logger.exception("Generation %s failed", request_id)
        request.status = GeminiGenerationRequest.Status.FAILED
        request.error_message = str(exc)[:2000]
        request.save(update_fields=['status', 'error_message'])
        # Re-raised so the worker records the traceback and can retry.
        raise

    content_item = _persist(
        request, brief, result_data, routed['provider'],
        brain_version=str(routed.get('brain_version') or ''),
    )

    # `generation_request`, not `request` — the field's actual name. With
    # the wrong keyword this line raised FieldError on every run, AFTER the
    # provider had been paid and the draft persisted: the task then retried
    # up to three times, spending and persisting again each round, and the
    # request row ended FAILED. Queued carousel and video generation has
    # never completed successfully because of this line.
    GeminiGenerationResult.objects.update_or_create(
        generation_request=request,
        defaults={
            'generated_text': result_data.get('postDescription', ''),
            # The composed poster when auto-compose succeeded, the raw image
            # otherwise — the poller must see what will actually be reviewed.
            'generated_asset_url': (
                (content_item.preview_url if content_item else '')
                or result_data.get('posterImageUrl', '')
                or ''
            ),
            'metadata': {
                'postTitle': result_data.get('postTitle', ''),
                'postHashtags': result_data.get('postHashtags', ''),
                'provider': routed['provider'],
                'provider_name': routed['provider_name'],
                'brain_version': routed['brain_version'],
                'completed_at': timezone.now().isoformat(),
                'contentItemId': str(content_item.id) if content_item else None,
                'assetId': str(content_item.asset_id) if content_item and content_item.asset_id else None,
            },
        },
    )

    request.status = GeminiGenerationRequest.Status.COMPLETED
    request.provider = routed['provider']
    request.completed_at = timezone.now()
    request.save(update_fields=['status', 'provider', 'completed_at'])

    return {
        'request': str(request.id),
        'content_item': str(content_item.id) if content_item else None,
    }


def _persist(request, brief, result_data, provider_key, *, brain_version=''):
    """
    Mirrors the synchronous path's persistence so a background generation
    produces exactly the same ContentItem a foreground one would.
    """
    from django.db import transaction

    from apps.brands.models import Brand
    from apps.content.models import ContentItem
    from apps.context.services.generation import (
        create_generated_asset,
        intelligence_in_force,
    )

    try:
        content_format = {
            'video': ContentItem.Format.VIDEO,
            'carousel': ContentItem.Format.CAROUSEL,
        }.get(str(brief.get('contentType', '')).lower(), ContentItem.Format.POSTER)

        slides = brief.get('slides') or []

        with transaction.atomic():
            asset = create_generated_asset(
                request.workspace, result_data, user=request.user
            )
            brand = (
                Brand.objects.filter(workspace=request.workspace)
                .order_by('-is_default')
                .first()
            )
            item = ContentItem.objects.create(
                workspace=request.workspace,
                brand=brand,
                asset=asset,
                # The same attribution the synchronous path records. Without
                # it a poster made on the queue vanished from "is this rule
                # reaching the work?" — the learning-usage report reads
                # exactly this key.
                layout_config={'generation_trace': {
                    'brain_version': brain_version,
                    **intelligence_in_force(brand, brain_version),
                }},
                content_format=content_format,
                status=ContentItem.Status.DRAFT,
                headline=(result_data.get('postTitle') or '')[:500],
                caption=result_data.get('postDescription') or '',
                hashtags=result_data.get('postHashtags') or '',
                cta=(brief.get('offer') or '')[:255],
                preview_url=(result_data.get('posterImageUrl') or '')[:1000],
                slides=slides if isinstance(slides, list) else [],
                ai_provider=(provider_key or 'UNKNOWN')[:100],
                ai_prompt=str(brief)[:5000],
                created_by=request.user,
            )

        # After the transaction commits, so a compose hiccup can never roll
        # back the persisted generation. Best-effort: on failure the raw
        # generated image stays in place.
        from apps.layouts.services import compose_generated_poster

        compose_generated_poster(item, user=request.user)
        return item
    except Exception:
        logger.exception("Could not persist background generation %s", request.pk)
        return None
