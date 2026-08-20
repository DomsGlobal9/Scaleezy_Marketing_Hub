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
    from apps.gemini.services.generator import GeminiGeneratorService

    try:
        request = GeminiGenerationRequest.objects.select_related('workspace').get(
            id=request_id
        )
    except GeminiGenerationRequest.DoesNotExist:
        logger.warning("Generation request %s vanished before it ran", request_id)
        return {'request': str(request_id), 'status': 'MISSING'}

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
        result_data = GeminiGeneratorService.generate_marketing_content(brief)
    except Exception as exc:
        logger.exception("Generation %s failed", request_id)
        request.status = GeminiGenerationRequest.Status.FAILED
        request.error_message = str(exc)[:2000]
        request.save(update_fields=['status', 'error_message'])
        # Re-raised so the worker records the traceback and can retry.
        raise

    GeminiGenerationResult.objects.update_or_create(
        request=request,
        defaults={
            'generated_text': result_data.get('postDescription', ''),
            'generated_asset_url': result_data.get('posterImageUrl', '') or '',
            'metadata': {
                'postTitle': result_data.get('postTitle', ''),
                'postHashtags': result_data.get('postHashtags', ''),
                'completed_at': timezone.now().isoformat(),
            },
        },
    )

    content_item = _persist(request, brief, result_data)

    request.status = GeminiGenerationRequest.Status.COMPLETED
    request.completed_at = timezone.now()
    request.save(update_fields=['status', 'completed_at'])

    return {
        'request': str(request.id),
        'content_item': str(content_item.id) if content_item else None,
    }


def _persist(request, brief, result_data):
    """
    Mirrors the synchronous path's persistence so a background generation
    produces exactly the same ContentItem a foreground one would.
    """
    from apps.brands.models import Brand
    from apps.content.models import ContentItem

    try:
        content_format = {
            'video': ContentItem.Format.VIDEO,
            'carousel': ContentItem.Format.CAROUSEL,
        }.get(str(brief.get('contentType', '')).lower(), ContentItem.Format.POSTER)

        slides = brief.get('slides') or []

        return ContentItem.objects.create(
            workspace=request.workspace,
            brand=Brand.objects.filter(workspace=request.workspace)
            .order_by('-is_default')
            .first(),
            content_format=content_format,
            status=ContentItem.Status.DRAFT,
            headline=(result_data.get('postTitle') or '')[:500],
            caption=result_data.get('postDescription') or '',
            hashtags=result_data.get('postHashtags') or '',
            cta=(brief.get('offer') or '')[:255],
            preview_url=(result_data.get('posterImageUrl') or '')[:1000],
            slides=slides if isinstance(slides, list) else [],
            ai_provider='GOOGLE_GEMINI',
            ai_prompt=str(brief)[:5000],
            created_by=request.user,
        )
    except Exception:
        logger.exception("Could not persist background generation %s", request.pk)
        return None
