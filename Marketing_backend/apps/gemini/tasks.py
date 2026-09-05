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
from .execution import media_outcome

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
TEMPLATE_INTERRUPTED_MESSAGE = (
    "The selected template render was interrupted. The generated draft was "
    "kept and needs a template before review."
)


def _lock_generation_references(*, reference_ids, workspace, brand):
    """Lock governed references without locking across a nullable outer join.

    ``eligible_for_retrieval()`` joins the optional provenance source. Applying
    PostgreSQL ``FOR UPDATE`` to that queryset attempts to lock the nullable
    side of the join and is rejected. Lock the inspiration rows first, then
    lock every non-null source row separately so source revocation cannot race
    final draft persistence.
    """
    from apps.inspirations.models import BrandInspiration
    from apps.knowledge.models import BrandSource

    references = list(
        BrandInspiration.objects.select_for_update().filter(
            pk__in=reference_ids,
            workspace=workspace,
            brand=brand,
            lifecycle_status=BrandInspiration.LifecycleStatus.ACTIVE,
        )
    )
    if len(references) != len(reference_ids):
        return []

    source_ids = {row.source_id for row in references if row.source_id}
    if source_ids:
        sources = list(
            BrandSource.objects.select_for_update().filter(
                pk__in=source_ids,
                workspace=workspace,
                brand=brand,
            )
        )
        if len(sources) != len(source_ids) or any(
            source.status == BrandSource.SourceStatus.ARCHIVED for source in sources
        ):
            return []

    return references


@task
def generate_content(request_id: str):
    """Runs one generation and records the outcome on the request row."""
    from apps.gemini.models import GeminiGenerationRequest, GeminiGenerationResult
    from apps.context.services.generation import generate_marketing_payload

    try:
        request = GeminiGenerationRequest.objects.select_related(
            'workspace', 'result'
        ).get(id=request_id)
    except GeminiGenerationRequest.DoesNotExist:
        logger.warning("Generation request %s vanished before it ran", request_id)
        return {'request': str(request_id), 'status': 'MISSING'}

    existing_result = getattr(request, 'result', None)
    existing_metadata = (
        existing_result.metadata
        if existing_result is not None and isinstance(existing_result.metadata, dict)
        else {}
    )
    existing_composition = existing_metadata.get('composition') or {}
    if (
        request.status == GeminiGenerationRequest.Status.FAILED
        and existing_composition.get('status') == 'FAILED'
        and (existing_metadata.get('media') or {}).get('status') != 'FAILED'
    ):
        # Provider output and a recoverable draft already exist. Retrying this
        # request would buy the providers again and create a duplicate draft;
        # template repair happens against the saved ContentItem instead.
        return {'request': str(request_id), 'status': 'TERMINAL_FAILED'}

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
        if brief.get('retry_image_only'):
            brand = Brand.objects.filter(workspace=request.workspace, pk=brief.get('retry_brand_id')).first()
        if brand is None or brand.status != Brand.Status.ACTIVE:
            raise ValueError('The selected brand is inactive. Generation was not started.')
        # API generation preflights written brand law before queueing, but
        # Autopilot enters here directly and a brand owner can also tighten
        # guardrails while an ordinary job is waiting. Re-read the live law at
        # the worker boundary before analysis or routing can spend anything.
        from apps.brands.services import guardrails as guardrail_law

        guardrail_violations = guardrail_law.preflight_violations(
            brand, guardrail_law.preflight_fields(brief)
        )
        if guardrail_violations:
            raise ValueError(
                'Blocked before any AI was paid: ' + ' '.join(guardrail_violations)
            )
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
        # New Create Studio jobs always carry an explicit source mode. Resolve
        # it again at execution time even when it has no reference rows: a
        # selected catalogue layout can be removed while the job is queued.
        # Pre-deploy governed inspiration jobs carried selections but no mode;
        # those are unambiguously REFERENCE and must retain their revocation
        # checks. Rows with neither stay on the legacy path without inference.
        creative_mode = str(creative.get('mode') or '')
        if not creative_mode and creative.get('selections'):
            creative_mode = 'REFERENCE'
        if creative_mode:
            from apps.context.services.creative_direction import resolve_creative_direction

            creative = resolve_creative_direction(
                request.workspace,
                brand,
                creative.get('selections') or [],
                creative_mode=creative_mode,
                layout=creative.get('layout', brief.get('layout', '')),
                instruction=brief.get('instruction', ''),
            )
            brief['creative_direction'] = creative
            brief['layout'] = creative['layout']
        # The variety picks (composition archetype, scene seed) tie-break on
        # the request id, so a re-run of the same job - a repair included -
        # lands on the same pick.
        brief.setdefault('request_id', str(request.pk))
        if brief.get('retry_image_only'):
            return _repair_missing_image(request, brief, brand)
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

            # A missing image is an explicit partial, not a claim that a
            # reference-based poster exists. Preserve successful paid copy;
            # media_outcome records FAILED and exposes image-only recovery.
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
                locked_references = _lock_generation_references(
                    reference_ids=preprocessing_ids,
                    workspace=locked_workspace,
                    brand=locked_brand,
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

            creative_mode = str(
                (brief.get('creative_direction') or {}).get('mode') or ''
            )
            composition = (
                {
                    'status': 'PENDING',
                    'layout': brief.get('layout', ''),
                }
                if creative_mode == 'CATALOG_TEMPLATE'
                else None
            )
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
                    'media': media_outcome(content_item, routed),
                    'postTitle': result_data.get('postTitle', ''),
                    'postHashtags': result_data.get('postHashtags', ''),
                    'videoUrl': result_data.get('videoUrl', ''),
                    'slideImageUrls': result_data.get('slideImageUrls') or [],
                    'provider': routed['provider'],
                    'provider_name': routed['provider_name'],
                    'brain_version': routed['brain_version'],
                    'creative_direction': {
                        'mode': creative_mode,
                        'selection_count': (brief.get('creative_direction') or {}).get(
                            'selection_count', 0
                        ),
                        'layout': brief.get('layout', ''),
                    },
                    **({'composition': composition} if composition else {}),
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
        if creative_mode == 'CATALOG_TEMPLATE':
            metadata['composition'] = {
                'status': 'COMPLETED',
                'layout': brief.get('layout', ''),
            }
            config = dict(content_item.layout_config or {})
            config['composition'] = dict(metadata['composition'])
            content_item.layout_config = config
            content_item.save(update_fields=['layout_config', 'updated_at'])
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
    except Exception as exc:
        from apps.layouts.services import PosterCompositionError

        if isinstance(exc, PosterCompositionError):
            config = dict(content_item.layout_config or {})
            config['composition'] = {
                'status': 'FAILED',
                'error': str(exc)[:300],
            }
            content_item.layout_config = config
            content_item.save(update_fields=['layout_config', 'updated_at'])
            metadata = dict(generation_result.metadata or {})
            metadata['composition'] = {
                'status': 'FAILED',
                'layout': brief.get('layout', ''),
                'error': str(exc)[:300],
            }
            generation_result.metadata = metadata
            generation_result.save(update_fields=['metadata'])
            logger.warning(
                "Selected template could not be rendered for content %s; "
                "provider output kept as an honest partial result",
                content_item.pk,
            )
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


def _repair_missing_image(request, brief, brand):
    """Repair one saved partial poster, without regenerating its paid copy."""
    from apps.content.models import ContentItem
    from apps.context.services.creative_direction import resolve_creative_direction
    from apps.context.services.generation import create_generated_asset, retry_image
    from apps.layouts.services import compose_generated_poster, PosterCompositionError

    result = request.result
    item = ContentItem.objects.select_related('brand').get(
        pk=(result.metadata or {}).get('contentItemId'), workspace=request.workspace,
        status=ContentItem.Status.DRAFT, content_format=ContentItem.Format.POSTER,
    )
    if item.brand is None or item.brand.status != 'ACTIVE':
        raise ValueError('The saved draft needs an active brand before image retry.')
    direction = (item.layout_config or {}).get('creative_direction') or {}
    if direction.get('mode'):
        brief['creative_direction'] = resolve_creative_direction(
            request.workspace, item.brand, direction.get('selections') or [],
            creative_mode=direction['mode'], layout=direction.get('layout', ''),
            instruction=brief.get('instruction', ''),
        )
    # A previous attempt may have saved the image before its worker stopped.
    # The durable asset is the checkpoint; never buy it a second time.
    should_compose = item.asset_id is None or result.asset_id == item.asset_id
    if item.asset_id is None:
        # The saved draft's own headline: the poster being repaired must
        # carry the words the copy already won. And its own composition and
        # scene: the record already says which archetype and seed this
        # poster is, so the repaired picture matches the record instead of
        # drawing a fresh pair the trace would then misreport.
        stored = (item.layout_config or {}).get('generation_trace') or {}
        fixed = {
            key: stored[key]
            for key in ('composition_archetype', 'scene_variant')
            if isinstance(stored.get(key), str) and stored[key]
        }
        retry_trace = {}
        image = retry_image(
            request.workspace, item.brand,
            {**brief, **fixed, 'headline': item.headline},
            instruction=brief.get('instruction', ''), trace=retry_trace,
        )
        with transaction.atomic():
            locked = ContentItem.objects.select_for_update().get(pk=item.pk)
            if locked.status != ContentItem.Status.DRAFT:
                raise ValueError('The draft entered review before its image could be saved.')
            request.workspace.refresh_from_db(fields=['status'])
            if not request.workspace.is_active:
                raise ValueError('This client is inactive. Generated output was not saved.')
            item.brand.refresh_from_db(fields=['status'])
            if locked.brand_id != item.brand_id or item.brand.status != 'ACTIVE':
                raise ValueError('The saved draft brand changed before its image could be saved.')
            if direction.get('mode'):
                resolve_creative_direction(
                    request.workspace, item.brand, direction.get('selections') or [],
                    creative_mode=direction['mode'], layout=direction.get('layout', ''),
                    instruction=brief.get('instruction', ''),
                )
            # A user may have supplied an image while the provider was busy.
            # Preserve that durable choice rather than overwriting it.
            if locked.asset_id is None:
                locked.asset = create_generated_asset(
                    request.workspace, {'metadata': {'generated_image': image}}, user=request.user,
                )
                if locked.asset is None:
                    raise ValueError('The image was not saved. Your copy is unchanged.')
                locked.preview_url = locked.asset.file_url
                config = dict(locked.layout_config or {})
                trace = dict(config.get('generation_trace') or {})
                capabilities = dict(trace.get('capabilities') or {})
                capabilities['IMAGE'] = {'status': 'OK', 'provider': image.get('provider', '')}
                trace['capabilities'] = capabilities
                # What the text check read off the repaired picture (see
                # `_gate_image_text`), and only that: the variety keys the
                # retry reports back are the fixed ones already stored.
                if isinstance(retry_trace.get('image_text'), dict):
                    trace['image_text'] = retry_trace['image_text']
                config['generation_trace'] = trace
                locked.layout_config = config
                locked.save(update_fields=['asset', 'preview_url', 'layout_config', 'updated_at'])
            else:
                should_compose = False
            item = locked
            result.asset = item.asset
            result.generated_asset_url = item.preview_url
            result.metadata = {**(result.metadata or {}), 'assetId': str(item.asset_id), 'media': {'status': 'READY', 'error': ''}}
            result.save(update_fields=['asset', 'generated_asset_url', 'metadata'])
    try:
        if should_compose:
            compose_generated_poster(item, user=request.user)
    except PosterCompositionError as exc:
        config = dict(item.layout_config or {})
        config['composition'] = {'status': 'FAILED', 'error': str(exc)[:300]}
        item.layout_config = config
        item.save(update_fields=['layout_config', 'updated_at'])
        result.metadata = {**(result.metadata or {}), 'composition': config['composition']}
    else:
        result.metadata = dict(result.metadata or {})
        if should_compose:
            result.metadata.pop('composition', None)
    item.refresh_from_db(fields=['asset', 'preview_url'])
    result.asset = item.asset
    result.generated_asset_url = item.preview_url
    result.metadata = {**result.metadata, 'assetId': str(item.asset_id), 'media': {'status': 'READY', 'error': ''}}
    result.save(update_fields=['asset', 'generated_asset_url', 'metadata'])
    request.status = 'COMPLETED'
    request.error_message = ''
    request.completed_at = timezone.now()
    request.save(update_fields=['status', 'error_message', 'completed_at', 'updated_at'])
    return {'request': str(request.pk), 'content_item': str(item.pk)}


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
            metadata = (
                dict(request.result.metadata or {})
                if isinstance(request.result.metadata, dict)
                else {}
            )
            composition = metadata.get('composition') or {}
            if composition.get('status') == 'PENDING':
                # Provider output and the draft are durable, but a killed
                # worker never proved the explicitly selected template was
                # applied. Fail honestly and keep that draft recoverable;
                # never rerun providers and never call raw output complete.
                finished = generating.update(
                    status=GeminiGenerationRequest.Status.COMPLETED,
                    error_message='',
                    completed_at=now,
                    updated_at=now,
                )
                swept += finished
                if finished:
                    metadata['composition'] = {
                        **composition,
                        'status': 'FAILED',
                        'error': TEMPLATE_INTERRUPTED_MESSAGE,
                    }
                    request.result.metadata = metadata
                    request.result.save(update_fields=['metadata'])
                    content_item_id = metadata.get('contentItemId')
                    if content_item_id:
                        from apps.content.models import ContentItem

                        item = ContentItem.objects.filter(
                            pk=content_item_id,
                            workspace=request.workspace,
                        ).first()
                        if item is not None:
                            config = dict(item.layout_config or {})
                            config['composition'] = dict(metadata['composition'])
                            item.layout_config = config
                            item.save(update_fields=['layout_config', 'updated_at'])
                    _queue_autopilot_followups(request)
                continue
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


def _scope_for_revision(feedback, revision):
    """`_regeneration_scope`, corrected for where the words actually live.

    Since the no-default-dress decision a delegated poster's headline and CTA
    are typography the image model paints — there is no compose pass to carry
    new words onto the old picture. Scoping a headline complaint to copy-only
    on such an item shipped a revision whose caption was title case under an
    image still shouting ALL CAPS (seen live, 2026-09-05). Copy complaints on
    an undressed poster therefore re-buy the image too; dressed items
    (layout_plugin set) and carousels keep the surgical copy-only path.
    """
    scope = _regeneration_scope(feedback)
    words_live_in_the_image = (
        revision.content_format == revision.Format.POSTER
        and not revision.layout_plugin
    )
    if scope['copy'] and words_live_in_the_image:
        scope['image'] = True
    return scope


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
    from apps.layouts import registry, variants
    from apps.layouts.services import compose_generated_poster

    revision = (
        ContentItem.objects.select_related('workspace', 'brand', 'parent')
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

    scope = _scope_for_revision(feedback, revision)
    config = dict(revision.layout_config or {})
    config.pop('regenerating', None)
    parent_config = (
        revision.parent.layout_config
        if revision.parent is not None
        and isinstance(revision.parent.layout_config, dict)
        else {}
    )
    creative_direction = (
        config.get('creative_direction')
        or parent_config.get('creative_direction')
        or {}
    )
    if not isinstance(creative_direction, dict):
        creative_direction = {}
    # The original generation's choice to leave the brand's model out is
    # recorded on the item; a re-bought picture must honour it rather than
    # front a face the poster was deliberately made without. Items saved
    # before the choice was recorded default to the brand's model, as the
    # first buy did.
    brief['feature_ambassador'] = bool(
        config.get('feature_ambassador', parent_config.get('feature_ambassador', True))
    )
    if (
        str(creative_direction.get('mode') or '').strip().upper() == 'REFERENCE'
        and (scope['copy'] or scope['image'] or revision.brand is None)
    ):
        from apps.context.services.creative_direction import (
            CreativeDirectionError,
            resolve_creative_direction,
        )

        try:
            creative_direction = resolve_creative_direction(
                revision.workspace,
                revision.brand,
                creative_direction.get('selections') or [],
                creative_mode='REFERENCE',
                layout='',
                instruction=instruction,
            )
        except CreativeDirectionError as exc:
            logger.info(
                "Regeneration %s refused because a reference is no longer available: %s",
                revision_id,
                exc,
            )
            return finish(
                'REFERENCE_UNAVAILABLE',
                regeneration_error={
                    'code': 'REFERENCE_UNAVAILABLE',
                    'message': str(exc)[:300],
                },
            )
    if creative_direction:
        # `request_edits` now carries this directly. The parent fallback keeps
        # revisions already queued before that fix attributable without ever
        # consulting a brand-wide or platform-default template.
        creative_direction = dict(creative_direction)
        config['creative_direction'] = creative_direction
    brief['creative_direction'] = creative_direction
    brief['layout'] = (
        str(creative_direction.get('layout') or '')
        if creative_direction.get('mode') == 'CATALOG_TEMPLATE'
        else ''
    )
    brain_version = str(getattr(revision.brand, 'brain_version', '') or '')

    if (scope['copy'] and scope['image']) or revision.brand is None:
        # Everything was flagged (or nothing classifiable): the full
        # regeneration this task always did.
        try:
            # The revision's OWN brand, explicitly: resolving by workspace
            # default would enforce another brand's guardrails on this
            # brand's content in a multi-brand workspace.
            routed = generate_marketing_payload(
                revision.workspace, brief, instruction=instruction,
                brand=revision.brand,
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
            # describes what any future composition should build from — and
            # neither does its focal point, so the compose re-detects.
            config.pop('source_asset', None)
            config.pop('photo_focus', None)
    else:
        # Surgical: only what the reviewer flagged changes. Elements they
        # liked keep their photograph, their words and their look.
        # A kept photograph did not change, so its composition and scene did
        # not either: the trace written below must go on naming the archetype
        # and seed this poster is, or it misdescribes the picture it sits
        # under. request_edits leaves the trace on the parent (it describes
        # the parent's generation), so that is where a first edit reads it;
        # a revision regenerated before carries its own. An image edit
        # overwrites both with the new picture's own picks.
        stored = dict(
            config.get('generation_trace')
            or parent_config.get('generation_trace')
            or {}
        )
        variety = {
            key: stored[key]
            for key in ('composition_archetype', 'scene_variant')
            if isinstance(stored.get(key), str) and stored[key]
        }
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
                # A new photograph is a new poster: it draws its own
                # composition and scene, and the trace below must say so.
                image = retry_image(
                    revision.workspace, revision.brand, brief,
                    instruction=instruction, trace=variety,
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
                # The re-bought poster IS the preview until the compose below
                # dresses it - and for a delegated design it never does, so
                # without this line the review card kept showing the parent's
                # picture the reviewer had just sent back.
                revision.preview_url = (
                    str(getattr(asset, 'file_url', '') or '')[:1000]
                    or revision.preview_url
                )
                # A new photograph replaces the parent's; the compose below
                # decides the preview — and re-detects the focal point,
                # which described the old photograph.
                config.pop('source_asset', None)
                config.pop('photo_focus', None)
        if scope['copy'] or scope['image']:
            config['generation_trace'] = {
                'brain_version': brain_version,
                **variety,
                **intelligence_in_force(revision.brand, brain_version),
            }
        if scope['restyle']:
            # The complaint is about the dress, not the photograph or words.
            # A catalogue choice (and a legacy stored layout) remains fixed:
            # regeneration must never silently replace an explicit
            # per-content template. A user-delegated AI/reference design has
            # no dress at all any more — the raw provider poster ships — so
            # clearing the inherited plugin is the whole restyle: the compose
            # below keeps the raw image, and picking a variant for a dress
            # that will never be worn would only record misleading state.
            inherited_variant = config.get('style_variant')
            if creative_direction.get('mode') in {'AI_ORIGINAL', 'REFERENCE'}:
                revision.layout_plugin = ''
                restyle_layout = ''
            else:
                restyle_layout = revision.layout_plugin or str(
                    creative_direction.get('layout') or ''
                )
            if restyle_layout:
                config['style_variant'] = variants.different_variant_for(
                    revision,
                    inherited_variant,
                    uses_photo=getattr(registry.get(restyle_layout), 'uses_photo', True),
                )

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
                    # The studio's per-generation choice to leave the
                    # model out travels with the item, so a later edit
                    # honours it instead of fronting a face the original
                    # was made without.
                    'feature_ambassador': bool(brief.get('feature_ambassador', True)),
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
