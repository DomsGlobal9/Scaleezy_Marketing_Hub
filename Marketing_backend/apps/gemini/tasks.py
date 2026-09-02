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

from django.db import transaction
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

    # Claim with one database compare-and-swap. Two workers can receive the
    # same task, but only one may move a PENDING request to GENERATING and buy
    # provider work. FAILED remains claimable for the task backend's explicit
    # retry semantics; the stuck-worker sweep first moves its one rescue back
    # to PENDING, so that path is preserved too.
    claimed = GeminiGenerationRequest.objects.filter(
        pk=request.pk,
        status__in=(
            GeminiGenerationRequest.Status.PENDING,
            GeminiGenerationRequest.Status.FAILED,
        ),
    ).update(
        status=GeminiGenerationRequest.Status.GENERATING,
        error_message='',
        updated_at=timezone.now(),
    )
    if not claimed:
        request.refresh_from_db(fields=['status'])
        if request.status == GeminiGenerationRequest.Status.COMPLETED:
            logger.info("Generation %s already completed; skipping re-run", request_id)
            return {'request': str(request_id), 'status': 'ALREADY_COMPLETED'}
        if request.status == GeminiGenerationRequest.Status.GENERATING:
            logger.info("Generation %s already has an active worker", request_id)
            return {'request': str(request_id), 'status': 'ALREADY_RUNNING'}
        return {'request': str(request_id), 'status': 'NOT_CLAIMED'}

    request.status = GeminiGenerationRequest.Status.GENERATING
    request.error_message = ''

    # Lifecycle may change after the API accepted the request. Do not analyse
    # a reference or spend with a provider for a client that is now suspended
    # or archived.
    if not request.workspace.is_active:
        request.status = GeminiGenerationRequest.Status.FAILED
        request.error_message = 'This client is inactive. Generation was not started.'
        request.save(update_fields=['status', 'error_message'])
        return {'request': str(request_id), 'status': 'FAILED'}

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
        from apps.brands.models import Brand

        brand = Brand.objects.filter(workspace=request.workspace).order_by('-is_default').first()
        if brand is None or brand.status != Brand.Status.ACTIVE:
            raise ValueError('The selected brand is inactive. Generation was not started.')
        preprocessing_ids = brief.get('analyze_before_generation_ids') or []
        if preprocessing_ids:
            from apps.inspirations.analysis import analyze_inspiration
            from apps.inspirations.models import BrandInspiration, InspirationSignal

            selected_brand_ids = {
                str(row.get('id'))
                for row in (creative.get('selections') or [])
                if row.get('source_type') == 'BRAND'
            }
            if (
                not isinstance(preprocessing_ids, list)
                or len(preprocessing_ids) > 12
                or len(set(map(str, preprocessing_ids))) != len(preprocessing_ids)
                or not set(map(str, preprocessing_ids)).issubset(selected_brand_ids)
            ):
                raise ValueError('Generation inspiration preprocessing is invalid.')
            rows = {
                str(row.pk): row
                for row in BrandInspiration.objects.eligible_for_retrieval().filter(
                    pk__in=preprocessing_ids,
                    workspace=request.workspace,
                    brand=brand,
                )
            }
            if len(rows) != len(preprocessing_ids):
                raise ValueError('One or more selected inspirations are unavailable.')
            for inspiration_id in preprocessing_ids:
                inspiration = rows[str(inspiration_id)]
                stale_processing = False
                if inspiration.analysis_status in (
                    BrandInspiration.AnalysisStatus.QUEUED,
                    BrandInspiration.AnalysisStatus.PROCESSING,
                ):
                    analysis = (inspiration.metadata or {}).get('analysis') or {}
                    started_at = analysis.get('started_at')
                    if (
                        inspiration.analysis_status
                        == BrandInspiration.AnalysisStatus.PROCESSING
                        and started_at
                    ):
                        from django.utils.dateparse import parse_datetime

                        parsed_started_at = parse_datetime(str(started_at))
                        stale_processing = bool(
                            parsed_started_at
                            and parsed_started_at <= timezone.now() - STUCK_AFTER
                        )
                    if not stale_processing:
                        raise ValueError(
                            'A selected inspiration is already being analysed.'
                        )
                has_any_observation = InspirationSignal.objects.filter(
                    inspiration_id=inspiration.pk,
                ).exists()
                if inspiration.analysis_status in (
                    BrandInspiration.AnalysisStatus.NOT_ANALYSED,
                    BrandInspiration.AnalysisStatus.FAILED,
                ) or stale_processing or (
                    inspiration.analysis_status == BrandInspiration.AnalysisStatus.READY
                    and not has_any_observation
                ):
                    analyze_inspiration(str(inspiration.pk))
                has_grounded_observation = InspirationSignal.objects.filter(
                    inspiration_id=inspiration.pk,
                    superseded_at__isnull=True,
                ).exclude(
                    user_confirmation=InspirationSignal.UserConfirmation.REJECTED
                ).exists()
                if not has_grounded_observation:
                    raise ValueError(
                        'The selected inspiration produced no usable creative observations.'
                    )

            # Analysis can be slow. Re-read lifecycle after it finishes so a
            # suspension during preprocessing cannot race into provider spend.
            request.workspace.refresh_from_db(fields=['status'])
            if not request.workspace.is_active:
                raise ValueError('This client is inactive. Generation was not started.')
            brand.refresh_from_db(fields=['status'])
            if brand.status != Brand.Status.ACTIVE:
                raise ValueError('The selected brand is inactive. Generation was not started.')
        if creative.get('selections'):
            from apps.context.services.creative_direction import resolve_creative_direction

            creative = resolve_creative_direction(
                request.workspace,
                brand,
                creative.get('selections'),
                layout=brief.get('layout', ''),
                instruction=brief.get('instruction', ''),
            )
            brief['creative_direction'] = creative
        routed = generate_marketing_payload(
            request.workspace,
            brief,
            instruction=brief.get('instruction', ''),
            progress=checkpoint,
            # A governed inspiration job must keep the exact brand whose
            # Brain/reference was validated, even if the default changes
            # while providers are working. Legacy jobs retain default lookup.
            brand=brand if preprocessing_ids else None,
        )
        result_data = routed['payload']
        if preprocessing_ids:
            from apps.ai.models import Capability

            # A client, brand, or selected reference can be revoked while the
            # provider is working. Spending has already occurred, but no draft
            # may be persisted under authority that no longer exists.
            request.workspace.refresh_from_db(fields=['status'])
            brand.refresh_from_db(fields=['status'])
            if not request.workspace.is_active:
                raise ValueError('This client is inactive. Generated output was not saved.')
            if brand.status != Brand.Status.ACTIVE:
                raise ValueError('The selected brand is inactive. Generated output was not saved.')
            still_eligible = (
                BrandInspiration.objects.eligible_for_retrieval()
                .filter(
                    pk__in=preprocessing_ids,
                    workspace=request.workspace,
                    brand=brand,
                )
                .count()
            )
            if still_eligible != len(preprocessing_ids):
                raise ValueError(
                    'One or more selected inspirations were revoked before output could be saved.'
                )

            capabilities = (routed.get('trace') or {}).get('capabilities') or {}
            image_trace = capabilities.get(Capability.IMAGE) or {}
            metadata = result_data.get('metadata') or {}
            generated_image = metadata.get('generated_image') or {}
            image_url = (
                result_data.get('posterImageUrl')
                or (
                    generated_image.get('image_url')
                    if isinstance(generated_image, dict)
                    else ''
                )
            )
            if image_trace.get('status') != 'OK' or not image_url:
                raise RuntimeError(
                    'Inspiration-based poster generation did not produce an image.'
                )
    except Exception as exc:
        logger.exception("Generation %s failed", request_id)
        request.status = GeminiGenerationRequest.Status.FAILED
        request.error_message = str(exc)[:2000]
        request.save(update_fields=['status', 'error_message'])
        _queue_autopilot_followups(request)
        # Re-raised so the worker records the traceback and can retry.
        raise

    try:
        # The draft and its durable polling result are one unit. If the result
        # row cannot be written, roll the draft back so a worker retry cannot
        # leave duplicates behind.
        with transaction.atomic():
            if preprocessing_ids:
                locked_workspace = request.workspace.__class__.objects.select_for_update().get(
                    pk=request.workspace_id
                )
                locked_brand = Brand.objects.select_for_update().get(
                    pk=brand.pk, workspace=locked_workspace
                )
                if not locked_workspace.is_active:
                    raise ValueError('This client is inactive. Generated output was not saved.')
                if locked_brand.status != Brand.Status.ACTIVE:
                    raise ValueError(
                        'The selected brand is inactive. Generated output was not saved.'
                    )
                locked_references = list(
                    BrandInspiration.objects.eligible_for_retrieval()
                    .select_for_update()
                    .filter(
                        pk__in=preprocessing_ids,
                        workspace=locked_workspace,
                        brand=locked_brand,
                    )
                )
                if len(locked_references) != len(preprocessing_ids):
                    raise ValueError(
                        'One or more selected inspirations were revoked before output could be saved.'
                    )
                brand = locked_brand

            content_item = _persist(
                request,
                brief,
                result_data,
                routed,
                brand=brand if preprocessing_ids else None,
            )
            if content_item is None:
                raise RuntimeError("Generated content could not be saved.")

            generation_result, _created = GeminiGenerationResult.objects.update_or_create(
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

    # Composition writes an optional derivative asset and therefore stays
    # outside the exactly-once database transaction. A composition/storage
    # failure keeps the original generated image and a completed request.
    try:
        from apps.layouts.services import compose_generated_poster

        compose_generated_poster(content_item, user=request.user)
        content_item.refresh_from_db(fields=['asset', 'preview_url'])
        metadata = dict(generation_result.metadata or {})
        metadata['assetId'] = (
            str(content_item.asset_id) if content_item.asset_id else None
        )
        generation_result.asset = content_item.asset
        generation_result.generated_asset_url = (
            content_item.preview_url
            or result_data.get('posterImageUrl', '')
            or ''
        )
        generation_result.metadata = metadata
        generation_result.save(
            update_fields=['asset', 'generated_asset_url', 'metadata']
        )
    except Exception:
        logger.exception(
            "Auto-compose result refresh failed for background content %s; raw image kept",
            content_item.pk,
        )

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
            finished = generating.update(
                status=GeminiGenerationRequest.Status.COMPLETED,
                completed_at=now,
                updated_at=now,
            )
            swept += finished
            if finished:
                # The dead worker never queued the follow-up either; an
                # autopilot run waiting on this generation would otherwise
                # stall.
                _queue_autopilot_followups(request)
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
            abandoned = generating.update(
                status=GeminiGenerationRequest.Status.FAILED,
                error_message=INTERRUPTED_MESSAGE,
                updated_at=now,
            )
            swept += abandoned
            if abandoned:
                # Terminal for the run too: the follow-up reads the FAILED
                # status and fails the run with this same honest message.
                _queue_autopilot_followups(request)
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


def _persist(request, brief, result_data, routed, *, brand=None):
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
            if brand is None:
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

    except Exception:
        logger.exception("Could not persist background generation %s", request.pk)
        return None

    return item
