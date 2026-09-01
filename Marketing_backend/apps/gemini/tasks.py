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

#: Rows stuck longer than this are failed without a re-run. Rescuing a brief
#: nobody has been polling for a day buys a draft nobody asked to pay for —
#: this matters most on the first pass after deploy, when the sweep meets
#: every row the pre-sweep era ever stranded.
RESCUE_HORIZON = timedelta(hours=24)

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
        request = GeminiGenerationRequest.objects.select_related(
            'workspace', 'result'
        ).get(id=request_id)
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

    if getattr(request, 'result', None) is not None:
        # The work is paid for and persisted; only the final bookkeeping was
        # lost (a worker died between the result write and the status save).
        # Finish the bookkeeping instead of buying the same work again. Rows
        # already FAILED are left alone — resurrecting an old failure weeks
        # later would surface a draft nobody is waiting for.
        metadata = request.result.metadata or {}
        GeminiGenerationRequest.objects.filter(
            pk=request.pk,
            status__in=[
                GeminiGenerationRequest.Status.PENDING,
                GeminiGenerationRequest.Status.GENERATING,
            ],
        ).update(
            status=GeminiGenerationRequest.Status.COMPLETED,
            provider=str(metadata.get('provider') or '')[:50],
            error_message=None,
            completed_at=timezone.now(),
            updated_at=timezone.now(),
        )
        logger.info("Generation %s already had a result; finished bookkeeping", request_id)
        return {'request': str(request_id), 'status': 'RESULT_ALREADY_LANDED'}

    # Atomic claim: only a PENDING row starts a run. A re-delivered task for
    # a row some other run already owns (GENERATING) or that ended (FAILED)
    # is a no-op — this is what keeps a reclaimed zombie TaskRun, a queue
    # retry, and the sweep's rescue from ever running the same request twice
    # or resurrecting a failure the user was already shown. The explicit
    # updated_at restarts the sweep's stuck clock at the moment work begins,
    # not at row creation (auto_now does not fire on queryset updates).
    # retry_count scopes the claim to the rescue generation this delivery
    # read: the sweep bumps it on every re-queue, so a stale delivery cannot
    # claim a row that has since moved on to a newer rescue.
    claimed = GeminiGenerationRequest.objects.filter(
        pk=request.pk,
        status=GeminiGenerationRequest.Status.PENDING,
        retry_count=request.retry_count,
    ).update(
        status=GeminiGenerationRequest.Status.GENERATING,
        updated_at=timezone.now(),
    )
    if not claimed:
        logger.info(
            "Generation %s not claimable (status %s); ignoring this delivery",
            request_id, request.status,
        )
        return {'request': str(request_id), 'status': 'NOT_CLAIMED'}

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
        # CAS on GENERATING *and* this run's claim generation: never
        # overwrite a terminal state some other actor already wrote, and
        # never fail a GENERATING claim that belongs to a newer rescue run
        # (the sweep bumps retry_count on every re-queue). Re-raised so the
        # worker records the traceback; a queue-level retry then no-ops at
        # the claim above, so FAILED is what the user actually sees — honest,
        # and consistent with the poller treating FAILED as final.
        GeminiGenerationRequest.objects.filter(
            pk=request.pk,
            status=GeminiGenerationRequest.Status.GENERATING,
            retry_count=request.retry_count,
        ).update(
            status=GeminiGenerationRequest.Status.FAILED,
            error_message=str(exc)[:2000],
            updated_at=timezone.now(),
        )
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

    completed = GeminiGenerationRequest.objects.filter(
        pk=request.pk,
        status=GeminiGenerationRequest.Status.GENERATING,
        retry_count=request.retry_count,
    ).update(
        status=GeminiGenerationRequest.Status.COMPLETED,
        provider=routed['provider'],
        error_message=None,
        completed_at=timezone.now(),
        updated_at=timezone.now(),
    )
    if not completed:
        # The sweep declared this run dead while it was merely slow. The
        # draft and result are persisted regardless; the row keeps the state
        # the user was already shown rather than flip-flopping under them.
        logger.warning(
            "Generation %s finished but its row had already been moved on; "
            "leaving the row's status as-is", request_id,
        )

    return {
        'request': str(request.id),
        'content_item': str(content_item.id) if content_item else None,
    }


def sweep_stuck_generations(now=None):
    """
    Rescues generation requests abandoned by a killed worker.

    A worker SIGKILLed mid-generation (a deploy whose grace period ran out)
    leaves the request row GENERATING with nothing live finishing it: the
    frontend polls "AI is working…" forever and nothing is. Each worker pass
    sweeps rows stuck longer than STUCK_AFTER — measured from the last
    status transition, since every transition stamps updated_at. A row whose
    result actually landed is completed (only the final bookkeeping was
    lost); a fresh row in an active workspace is re-queued once; everything
    else — rescue already spent, workspace suspended or archived, or older
    than RESCUE_HORIZON — fails with an honest message the poller can show.

    PENDING rows are swept too, but only when no live TaskRun still serves
    them: an aged PENDING with a queued task is just a backlog, while one
    with no task was orphaned (an enqueue that never happened — a crash
    between the view's create and enqueue, or a task that burned its
    attempts during a deploy's schema window) and would otherwise spin
    forever, invisible to a GENERATING-only sweep.

    Returns how many rows were swept.
    """
    from django.db.models import Q

    from apps.gemini.models import GeminiGenerationRequest

    now = now or timezone.now()
    cutoff = now - STUCK_AFTER
    stuck = GeminiGenerationRequest.objects.filter(
        # The null arm covers rows inserted by old-code instances during a
        # deploy overlap, which know nothing of updated_at: without it such
        # a row, once stranded, would be invisible to every future sweep.
        Q(updated_at__lt=cutoff) | Q(updated_at__isnull=True, created_at__lt=cutoff),
        status__in=[
            GeminiGenerationRequest.Status.PENDING,
            GeminiGenerationRequest.Status.GENERATING,
        ],
    ).select_related('result', 'workspace')

    live_ids = None
    swept = 0
    for request in stuck:
        if request.status == GeminiGenerationRequest.Status.PENDING:
            if live_ids is None:
                live_ids = _live_generation_request_ids()
            if str(request.pk) in live_ids:
                continue  # Backlogged, not orphaned: its task will run.
        # One poisoned row must not stop the rest of the sweep — the same
        # rule the publishing scheduler applies per job.
        try:
            swept += _sweep_one(request, now)
        except Exception:
            logger.exception("Could not sweep stuck generation %s", request.pk)
    return swept


def _live_generation_request_ids():
    """Request ids that a queued or running generate_content task still serves."""
    from django.tasks import TaskResultStatus

    from apps.jobs.models import TaskRun

    rows = TaskRun.objects.filter(
        task_path=generate_content.module_path,
        status__in=[TaskResultStatus.READY, TaskResultStatus.RUNNING],
    ).values_list('args', flat=True)
    return {str(args[0]) for args in rows if args}


def _sweep_one(request, now):
    """Settles one stuck row; returns 1 if it changed state, else 0."""
    from django.db import transaction

    from apps.gemini.models import GeminiGenerationRequest
    from apps.workspaces.models import MarketingWorkspace

    # Every write below is CAS'd against the state this pass observed, so a
    # row that moved on (claimed, completed, re-swept elsewhere) is untouched.
    in_flight = GeminiGenerationRequest.objects.filter(
        pk=request.pk, status=request.status
    )

    if getattr(request, 'result', None) is not None:
        # The generation finished; the worker died between writing the
        # result and the final status save. Finish the bookkeeping rather
        # than paying for the same work again.
        metadata = request.result.metadata or {}
        return in_flight.update(
            status=GeminiGenerationRequest.Status.COMPLETED,
            provider=str(metadata.get('provider') or '')[:50],
            error_message=None,
            completed_at=now,
            updated_at=now,
        )

    rescuable = (
        request.retry_count < MAX_RESCUE_ATTEMPTS
        # Suspension pauses all scheduled work and writes for a client; the
        # sibling sweeps filter on ACTIVE for the same reason. The row still
        # gets the honest FAILED below instead of spinning forever.
        and request.workspace.status == MarketingWorkspace.Status.ACTIVE
        # Nobody is polling a row this old; buying it a draft now would be
        # surprise spend, not a rescue. Matters most on the first pass after
        # deploy, which meets every row ever stranded before the sweep existed.
        and (request.updated_at or request.created_at) >= now - RESCUE_HORIZON
    )
    if rescuable:
        # The flip and the enqueue commit or roll back together (the queue is
        # a table in this same database), so a crash between them cannot
        # strand the row in a PENDING no-one will run. The retry_count
        # compare-and-swap keeps two workers sweeping at once from queuing
        # the same rescue twice, and moves the row to a new claim generation
        # so a stale run's terminal writes can no longer touch it.
        with transaction.atomic():
            claimed = in_flight.filter(retry_count=request.retry_count).update(
                status=GeminiGenerationRequest.Status.PENDING,
                retry_count=request.retry_count + 1,
                updated_at=now,
            )
            if claimed:
                generate_content.enqueue(str(request.pk))
        if claimed:
            logger.warning(
                "Generation %s abandoned by a dead worker; re-queued", request.pk
            )
        return 1 if claimed else 0

    failed = in_flight.update(
        status=GeminiGenerationRequest.Status.FAILED,
        error_message=INTERRUPTED_MESSAGE,
        updated_at=now,
    )
    if failed:
        logger.warning(
            "Generation %s stuck beyond rescue; marked FAILED", request.pk
        )
    return failed


@task
def regenerate_revision(revision_id: str):
    """
    Applies a reviewer's feedback by regenerating a returned item's revision.

    "Request edits" used to open an identical copy of the rejected version and
    then wait for a human to rewrite it by hand — the note, tags and fix
    request drove nothing. Here they become the instruction for a fresh
    generation, and the result lands on the revision as new copy and a newly
    composed poster. Best-effort throughout: any refusal or failure leaves the
    revision exactly as the editable copy it already was.
    """
    from apps.billing.quota import QuotaExceeded, enforce
    from apps.content.models import ContentItem
    from apps.context.services.generation import (
        create_generated_asset,
        generate_marketing_payload,
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

    try:
        routed = generate_marketing_payload(
            revision.workspace, brief, instruction=instruction
        )
        payload = routed['payload']
    except Exception:
        logger.exception("Regeneration failed for revision %s; copy left as-is", revision_id)
        return finish('FAILED')

    asset = create_generated_asset(revision.workspace, payload, user=revision.created_by)
    revision.headline = (payload.get('postTitle') or revision.headline or '')[:500]
    revision.caption = payload.get('postDescription') or revision.caption or ''
    revision.hashtags = payload.get('postHashtags') or revision.hashtags or ''
    revision.ai_provider = (routed.get('provider') or revision.ai_provider or '')[:100]

    config = dict(revision.layout_config or {})
    config.pop('regenerating', None)
    if asset is not None:
        revision.asset = asset
        revision.preview_url = (payload.get('posterImageUrl') or '')[:1000] or revision.preview_url
        # A new photograph replaces the parent's; the old source no longer
        # describes what any future composition should build from.
        config.pop('source_asset', None)
    revision.layout_config = config
    revision.save(
        update_fields=[
            'headline', 'caption', 'hashtags', 'ai_provider',
            'asset', 'preview_url', 'layout_config', 'updated_at',
        ]
    )

    compose_generated_poster(revision, user=revision.created_by)
    return {'revision': str(revision_id), 'status': 'OK'}


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
    from apps.gemini.models import GeminiGenerationResult

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

            # Seeded in the same transaction as the draft, so "a result row
            # exists" and "the provider's work is persisted" can never be
            # separated by a worker death: the stuck-generation sweep and
            # re-deliveries key their don't-buy-it-twice checks on this row.
            # The caller refreshes it with the composed poster afterwards.
            GeminiGenerationResult.objects.update_or_create(
                generation_request=request,
                defaults={
                    'generated_text': result_data.get('postDescription', ''),
                    'generated_asset_url': result_data.get('posterImageUrl', '') or '',
                    'metadata': {'provider': provider_key or '', 'seed': True},
                },
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
