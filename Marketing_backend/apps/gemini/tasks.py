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
from datetime import timedelta

from django.tasks import task
from django.utils import timezone

logger = logging.getLogger(__name__)

#: A request still GENERATING after this long belongs to a worker that died
#: mid-task — a deploy's SIGKILL after the grace period, principally. Long
#: enough that a slow video or carousel generation is not bought twice while
#: it is still honestly running.
STUCK_AFTER = timedelta(minutes=10)

#: One rescue re-run, then the honest answer. Unbounded retries would spend
#: provider money forever on a brief that kills the worker every time.
MAX_RESCUE_ATTEMPTS = 1

INTERRUPTED_MESSAGE = (
    "Generation was interrupted by a server restart and could not be "
    "completed. Please try again."
)


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
                # The composed poster when auto-compose succeeded, the raw
                # media otherwise - the poller must see what will actually
                # be reviewed. Video output has no composition step.
                'generated_asset_url': (
                    result_data.get('videoUrl')
                    or (content_item.preview_url if content_item else '')
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


def sweep_stuck_generations(now=None):
    """
    Rescues generation requests abandoned by a killed worker.

    A worker SIGKILLed mid-generation (a deploy whose grace period ran out)
    leaves the request row GENERATING with nothing queued to finish it: the
    frontend polls "AI is working…" forever and nothing is. Each worker pass
    sweeps rows GENERATING for longer than STUCK_AFTER: a row whose result
    actually landed is completed (only the final bookkeeping was lost),
    anything else is re-queued once, and after that it fails with an honest
    message the poller can show. Returns how many rows were swept.
    """
    from django.db.models import Q

    from apps.gemini.models import GeminiGenerationRequest

    now = now or timezone.now()
    cutoff = now - STUCK_AFTER
    stuck = GeminiGenerationRequest.objects.filter(
        # updated_at is null on rows from before the field existed;
        # created_at is the only clock those have.
        Q(updated_at__lt=cutoff) | Q(updated_at__isnull=True, created_at__lt=cutoff),
        status=GeminiGenerationRequest.Status.GENERATING,
    ).select_related('result')

    swept = 0
    for request in stuck:
        generating = GeminiGenerationRequest.objects.filter(
            pk=request.pk, status=GeminiGenerationRequest.Status.GENERATING
        )
        if getattr(request, 'result', None) is not None:
            # The generation finished; the worker died between writing the
            # result and the final status save. Finish the bookkeeping rather
            # than paying for the same work again.
            swept += generating.update(
                status=GeminiGenerationRequest.Status.COMPLETED,
                completed_at=now,
                updated_at=now,
            )
        elif request.retry_count < MAX_RESCUE_ATTEMPTS:
            # Compare-and-swap on retry_count so two workers sweeping at once
            # cannot queue the same rescue twice.
            claimed = generating.filter(retry_count=request.retry_count).update(
                status=GeminiGenerationRequest.Status.PENDING,
                retry_count=request.retry_count + 1,
                updated_at=now,
            )
            if claimed:
                logger.warning(
                    "Generation %s abandoned by a dead worker; re-queued", request.pk
                )
                generate_content.enqueue(str(request.pk))
                swept += 1
        else:
            swept += generating.update(
                status=GeminiGenerationRequest.Status.FAILED,
                error_message=INTERRUPTED_MESSAGE,
                updated_at=now,
            )
            logger.warning(
                "Generation %s still stuck after a rescue; marked FAILED", request.pk
            )
    return swept


#: Which feedback groups touch which half of a poster. COPY, LINE_BY_LINE and
#: STRATEGY are about the words; VISUAL is about the photograph; TYPOGRAPHY,
#: LOGO and LAYOUT are about the dress the compose engine puts on — no
#: provider spend fixes those. Colour complaints straddle the photograph and
#: the dress. Anything unmapped (AUDIO, FORMAT, an unknown key) regenerates
#: everything, which is exactly what every request-edits did before scoping.
_COPY_GROUPS = frozenset({'COPY', 'LINE_BY_LINE', 'STRATEGY'})
_IMAGE_GROUPS = frozenset({'VISUAL'})
_RESTYLE_GROUPS = frozenset({'TYPOGRAPHY', 'LOGO', 'LAYOUT'})
_COLOUR_KEYS = frozenset({'brand_colours', 'colour_palette'})


def _regeneration_scope(feedback):
    """What a reviewer's flagged elements actually ask to be changed.

    The founder's question, verbatim: "what if i like some elements in the
    design and want edits — will it change all or only the ones we request?"
    Only the ones requested: elements the reviewer did not flag keep their
    photograph, their words and their look."""
    keys = list(getattr(feedback, 'element_keys', None) or [])
    if not keys:
        return {'copy': True, 'image': True, 'restyle': False}

    from apps.feedback.models import FeedbackElement

    groups = dict(
        FeedbackElement.objects.filter(key__in=keys).values_list('key', 'group')
    )
    scope = {'copy': False, 'image': False, 'restyle': False}
    for key in keys:
        group = groups.get(key)
        if key in _COLOUR_KEYS:
            scope['image'] = scope['restyle'] = True
        elif group in _COPY_GROUPS:
            scope['copy'] = True
        elif group in _IMAGE_GROUPS:
            scope['image'] = True
        elif group in _RESTYLE_GROUPS:
            scope['restyle'] = True
        else:
            scope['copy'] = scope['image'] = True
    return scope


@task
def regenerate_revision(revision_id: str):
    """
    Applies a reviewer's feedback by regenerating a returned item's revision.

    "Request edits" used to open an identical copy of the rejected version and
    then wait for a human to rewrite it by hand — the note, tags and fix
    request drove nothing. Here they become the instruction for a fresh
    generation, scoped to what was actually flagged: copy complaints keep the
    photograph, visual complaints keep the words, and typography/logo/layout
    complaints re-dress the same photograph without spending a provider call
    at all. Best-effort throughout: any refusal or failure leaves the
    revision exactly as the editable copy it already was.
    """
    from apps.billing.quota import QuotaExceeded, enforce
    from apps.content.models import ContentItem
    from apps.context.services.generation import (
        create_generated_asset,
        generate_copy_only,
        generate_marketing_payload,
        intelligence_in_force,
        retry_image,
    )
    from apps.feedback.models import Feedback
    from apps.feedback.training import element_labels
    from apps.layouts.services import compose_generated_poster

    revision = (
        ContentItem.objects.select_related('workspace', 'brand')
        .filter(pk=revision_id, status=ContentItem.Status.DRAFT)
        .first()
    )
    if revision is None or revision.parent_id is None:
        logger.info("Revision %s gone or already moved on; nothing to regenerate", revision_id)
        return {'revision': str(revision_id), 'status': 'MISSING'}

    def finish(status, **updates):
        """Clears the in-progress marker in every exit path, so a card can
        never claim to be regenerating forever."""
        config = dict(revision.layout_config or {})
        config.pop('regenerating', None)
        config.update(updates)
        revision.layout_config = config
        revision.save(update_fields=['layout_config', 'updated_at'])
        return {'revision': str(revision_id), 'status': status}

    try:
        enforce(revision.workspace)
    except QuotaExceeded:
        logger.info("Revision %s left for manual edits: quota exhausted", revision_id)
        return finish('QUOTA')

    # The verdict that sent this back lives on the parent — it is the
    # instruction for what to do differently this time.
    feedback = (
        Feedback.objects.filter(content_item_id=revision.parent_id)
        .order_by('-created_at')
        .first()
    )
    corrections = []
    if feedback is not None:
        if feedback.feedback_text:
            corrections.append(f"Reviewer note: {feedback.feedback_text}")
        if feedback.fix_request:
            corrections.append(f"How it should be fixed: {feedback.fix_request}")
        if feedback.element_keys:
            labels = element_labels(feedback.element_keys)
            named = ', '.join(
                labels.get(key, {}).get('label', key) for key in feedback.element_keys
            )
            corrections.append(f"Elements flagged as wrong: {named}")

    instruction = ' '.join([
        "Revise the previous version of this content. Keep what worked, fix what was flagged.",
        *corrections,
    ])[:500]

    brief = {
        'campaign_name': (revision.headline or '')[:255],
        'offer': revision.cta or '',
        'previous_headline': revision.headline or '',
        'previous_caption': (revision.caption or '')[:2000],
        'revision_feedback': corrections,
    }

    scope = _regeneration_scope(feedback)
    config = dict(revision.layout_config or {})
    config.pop('regenerating', None)
    brain_version = str(getattr(revision.brand, 'brain_version', '') or '')

    if (scope['copy'] and scope['image']) or revision.brand is None:
        # Everything was flagged (or nothing classifiable): the full
        # regeneration this task always did.
        try:
            routed = generate_marketing_payload(
                revision.workspace, brief, instruction=instruction
            )
            payload = routed['payload']
        except Exception:
            logger.exception(
                "Regeneration failed for revision %s; copy left as-is", revision_id
            )
            return finish('FAILED')

        asset = create_generated_asset(
            revision.workspace, payload, user=revision.created_by
        )
        revision.headline = (payload.get('postTitle') or revision.headline or '')[:500]
        revision.caption = payload.get('postDescription') or revision.caption or ''
        revision.hashtags = payload.get('postHashtags') or revision.hashtags or ''
        revision.ai_provider = (routed.get('provider') or revision.ai_provider or '')[:100]
        # The regeneration is a generation: it must carry the same trace
        # _persist writes, or the learning-usage report undercounts every
        # request-edits pass. Inherited keys stay untouched.
        config['generation_trace'] = {
            'brain_version': routed.get('brain_version', ''),
            **(routed.get('trace') or {}),
            **intelligence_in_force(
                revision.brand, str(routed.get('brain_version') or '')
            ),
        }
        if asset is not None:
            revision.asset = asset
            revision.preview_url = (
                (payload.get('posterImageUrl') or '')[:1000] or revision.preview_url
            )
            # A new photograph replaces the parent's; the old source no longer
            # describes what any future composition should build from.
            config.pop('source_asset', None)
    else:
        # Surgical: only what the reviewer flagged changes. Elements they
        # liked keep their photograph, their words and their look.
        if scope['copy']:
            try:
                payload = generate_copy_only(
                    revision.workspace, revision.brand, brief,
                    instruction=instruction,
                )
            except Exception:
                logger.exception(
                    "Copy regeneration failed for revision %s; left as-is",
                    revision_id,
                )
                return finish('FAILED')
            revision.headline = (
                payload.get('postTitle') or revision.headline or ''
            )[:500]
            revision.caption = payload.get('postDescription') or revision.caption or ''
            revision.hashtags = payload.get('postHashtags') or revision.hashtags or ''
        if scope['image']:
            try:
                image = retry_image(
                    revision.workspace, revision.brand, brief,
                    instruction=instruction,
                )
            except Exception:
                logger.exception(
                    "Image regeneration failed for revision %s; left as-is",
                    revision_id,
                )
                return finish('FAILED')
            asset = create_generated_asset(
                revision.workspace,
                {'metadata': {'generated_image': image or {}}},
                user=revision.created_by,
            )
            if asset is not None:
                revision.asset = asset
                # A new photograph replaces the parent's; the compose below
                # decides the preview.
                config.pop('source_asset', None)
        if scope['copy'] or scope['image']:
            config['generation_trace'] = {
                'brain_version': brain_version,
                **intelligence_in_force(revision.brand, brain_version),
            }
        if scope['restyle']:
            # The complaint is about the dress, not the photograph or the
            # words: drop the inherited look and let the compose engine pick
            # this revision's own layout and style variant. No provider spend.
            config.pop('style_variant', None)
            revision.layout_plugin = ''

    revision.layout_config = config
    revision.save(
        update_fields=[
            'headline', 'caption', 'hashtags', 'ai_provider', 'layout_plugin',
            'asset', 'preview_url', 'layout_config', 'updated_at',
        ]
    )

    compose_generated_poster(revision, user=revision.created_by)
    return {'revision': str(revision_id), 'status': 'OK'}


def _persist(request, brief, result_data, routed):
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

    content_format = {
        'video': ContentItem.Format.VIDEO,
        'carousel': ContentItem.Format.CAROUSEL,
    }.get(str(brief.get('contentType', '')).lower(), ContentItem.Format.POSTER)

    slides = (
        result_data.get('slides')
        if str(brief.get('contentType', '')).lower() == 'carousel'
        else brief.get('slides')
    ) or []

    try:
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
                # Creative direction and the generation trace, including which
                # rules were in force - the learning-usage report reads
                # exactly this key, and a poster made on the queue must be as
                # attributable as one made in the request.
                layout_config={
                    'creative_direction': brief.get('creative_direction') or {},
                    'generation_trace': {
                        'brain_version': routed.get('brain_version', ''),
                        **(routed.get('trace') or {}),
                        **intelligence_in_force(
                            brand, str(routed.get('brain_version') or '')
                        ),
                    },
                },
                created_by=request.user,
            )

        # After the transaction commits, so a compose hiccup can never roll
        # back the persisted generation. Only posters compose; the service
        # skips video and carousel output on its own.
        from apps.layouts.services import compose_generated_poster

        compose_generated_poster(item, user=request.user)
        return item
    except Exception:
        logger.exception("Could not persist background generation %s", request.pk)
        return None
