"""Governed manual generation over the existing Context Gateway and AIRouter."""
import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.ai.models import AIUsageLog
from apps.billing.quota import enforce as enforce_billing
from apps.brands.services.approval import enforce_spend_approved
from apps.content.models import ContentItem
from apps.gemini.models import GeminiGenerationRequest
from apps.workspaces.models import MarketingWorkspace

from .models import AutopilotPolicy, AutopilotRun, AutopilotStep

logger = logging.getLogger(__name__)


class AutopilotBlocked(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class AutopilotQueueUnavailable(Exception):
    def __init__(self, run):
        super().__init__(run.error)
        self.run = run


def policy_snapshot(policy):
    return {
        'policy_id': str(policy.pk),
        'name': policy.name,
        'mode': policy.mode,
        'cadence': policy.cadence,
        'objective': policy.objective,
        'campaign_brief': policy.campaign_brief,
        'allowed_formats': list(policy.allowed_formats or []),
        'target_social_connection_ids': [
            str(value) for value in policy.social_connections.values_list('id', flat=True)
        ],
        'daily_generation_limit': policy.daily_generation_limit,
        'monthly_spend_cap': str(policy.monthly_spend_cap),
        'captured_at': timezone.now().isoformat(),
    }


def create_run(policy, *, initiated_by=None, scheduled_for=None, dedupe_key=None):
    scheduled_for = scheduled_for or timezone.now()
    key = dedupe_key or f'manual:{policy.pk}:{timezone.now().isoformat()}'
    return AutopilotRun.objects.create(
        workspace=policy.workspace,
        policy=policy,
        scheduled_for=scheduled_for,
        dedupe_key=key[:255],
        policy_snapshot=policy_snapshot(policy),
        initiated_by=initiated_by,
    )


def queue_run(policy, *, initiated_by=None):
    """Create and enqueue a manual run while keeping queue failures truthful."""
    run = create_run(policy, initiated_by=initiated_by)
    return _enqueue_execute(run)


def _enqueue_execute(run):
    """Enqueues the durable execute task for an already-created run.

    A queue failure is recorded on the run itself (FAILED /
    QUEUE_ENQUEUE_FAILED) before AutopilotQueueUnavailable is raised, so the
    ledger never shows a run that silently went nowhere.
    """
    try:
        from .tasks import execute_autopilot_run

        result = execute_autopilot_run.enqueue(str(run.pk))
    except Exception as exc:
        logger.exception(
            'Autopilot run could not enter the durable task queue.',
            extra={'autopilot_run_id': str(run.pk), 'workspace_id': str(run.workspace_id)},
        )
        run.status = AutopilotRun.Status.FAILED
        run.error_code = 'QUEUE_ENQUEUE_FAILED'
        run.error = 'The run could not enter the task queue. Retry it from the control centre.'
        run.completed_at = timezone.now()
        run.next_check_at = None
        run.save(update_fields=[
            'status', 'error_code', 'error', 'completed_at', 'next_check_at', 'updated_at'
        ])
        _step(run, 'finish', 'FAILED', code=run.error_code, message=run.error)
        raise AutopilotQueueUnavailable(run) from exc

    run.task_id = str(result.id)
    run.save(update_fields=['task_id', 'updated_at'])
    return run


def _step(run, key, status, **detail):
    AutopilotStep.objects.update_or_create(
        run=run, key=key, defaults={'status': status, 'detail': detail}
    )


def _fail(run, code, message):
    run.status = AutopilotRun.Status.FAILED
    run.error_code = str(code)[:80]
    run.error = str(message)[:2000]
    run.completed_at = timezone.now()
    run.next_check_at = None
    run.save(update_fields=[
        'status', 'error_code', 'error', 'completed_at', 'next_check_at', 'updated_at'
    ])
    _step(run, 'finish', 'FAILED', code=run.error_code, message=run.error)
    return {'status': run.status, 'error': run.error}


def _enforce_policy(policy, run):
    workspace = policy.workspace
    if not policy.enabled or policy.paused or policy.emergency_stop:
        raise AutopilotBlocked('POLICY_STOPPED', 'This autopilot policy is disabled, paused or stopped.')
    if workspace.status != MarketingWorkspace.Status.ACTIVE:
        raise AutopilotBlocked('WORKSPACE_INACTIVE', 'The client is not active.')
    enforce_spend_approved(workspace)
    enforce_billing(workspace)

    day_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    used_today = AutopilotRun.objects.filter(
        policy=policy, created_at__gte=day_start
    ).exclude(
        status=AutopilotRun.Status.STOPPED
    ).exclude(
        error_code='QUEUE_ENQUEUE_FAILED'
    ).exclude(pk=run.pk).count()
    if policy.daily_generation_limit and used_today >= policy.daily_generation_limit:
        raise AutopilotBlocked(
            'DAILY_AUTOPILOT_LIMIT',
            f'This policy has reached its daily limit of {policy.daily_generation_limit}.',
        )

    if policy.monthly_spend_cap:
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        spent = AIUsageLog.objects.filter(
            workspace=workspace, created_at__gte=month_start
        ).aggregate(total=Sum('cost'))['total'] or Decimal('0')
        if spent >= policy.monthly_spend_cap:
            raise AutopilotBlocked(
                'AUTOPILOT_SPEND_CAP',
                f'This policy has reached its monthly spend cap of {policy.monthly_spend_cap}.',
            )


def _queue_generation(run, policy):
    formats = policy.allowed_formats or ['POSTER']
    previous = AutopilotRun.objects.filter(
        policy=policy, created_at__lt=run.created_at
    ).exclude(error_code='QUEUE_ENQUEUE_FAILED').count()
    chosen = str(formats[previous % len(formats)]).upper()
    content_type = {'POSTER': 'poster', 'CAROUSEL': 'carousel', 'VIDEO': 'video'}[chosen]
    brief = {
        'campaign_name': policy.name,
        'product': policy.objective,
        'target_audience': policy.brand.audience,
        'location': policy.brand.location,
        'occasion': '',
        'offer': policy.brand.cta_keyword,
        'brand_tone': policy.brand.brand_tone,
        'contentType': content_type,
        'slides': [],
        'brand_rules': [],
        # Enabling an autopilot mission is an explicit delegation to create an
        # original composition for each run. Template choice never comes from
        # Brand Brain or a brand-wide default.
        'creative_direction': {
            'mode': 'AI_ORIGINAL',
            'selection_count': 0,
            'layout': '',
            'selections': [],
            'instructions': [],
        },
        'layout': '',
        'autopilot': {
            'run_id': str(run.pk),
            'policy_id': str(policy.pk),
            'objective': policy.objective,
            'campaign_brief': policy.campaign_brief,
            'target_channels': [
                connection.platform for connection in policy.social_connections.all()
            ],
        },
    }
    generation = GeminiGenerationRequest.objects.create(
        workspace=run.workspace,
        user=run.initiated_by or policy.created_by,
        prompt_data=json.dumps(brief),
        campaign_name=policy.name[:255],
        product=policy.objective[:255],
        target_audience=policy.brand.audience[:255],
        location=policy.brand.location[:255],
        offer=policy.brand.cta_keyword[:255],
        brand_tone=policy.brand.brand_tone[:255],
        content_format=content_type,
    )
    from apps.gemini.tasks import generate_content

    # The run must already be WAITING_GENERATION with its FK saved when a
    # worker picks the generation up: the finished generation queues its
    # autopilot follow-up by reading that FK and that status, and enqueueing
    # first let a fast completion (or fast failure) look for the link before
    # it existed — a follow-up lost forever. An enqueue failure after this
    # save falls through to the caller's failure handler.
    run.generation_request = generation
    run.status = AutopilotRun.Status.WAITING_GENERATION
    run.next_check_at = timezone.now() + timedelta(seconds=20)
    run.save(update_fields=['generation_request', 'status', 'next_check_at', 'updated_at'])
    task_result = generate_content.enqueue(str(generation.pk))
    run.task_id = str(task_result.id)
    run.save(update_fields=['task_id', 'updated_at'])
    _step(run, 'generate', 'QUEUED', generation_id=str(generation.pk), format=chosen)
    return {'status': run.status, 'generation_id': str(generation.pk)}


def _content_from_generation(run):
    try:
        content_id = (run.generation_request.result.metadata or {}).get('contentItemId')
    except Exception:
        return None
    return ContentItem.objects.filter(workspace=run.workspace, pk=content_id).first()


def execute_run(run_id):
    with transaction.atomic():
        # of=('self',): created_by and generation_request are nullable FKs, so
        # select_related LEFT-JOINs them, and PostgreSQL refuses FOR UPDATE on
        # the nullable side of an outer join (NotSupportedError). Only the run
        # row needs the lock. SQLite ignores select_for_update entirely, which
        # is why no test caught this — verified against production Postgres.
        run = AutopilotRun.objects.select_for_update(of=('self',)).select_related(
            'workspace', 'policy__brand', 'policy__created_by', 'generation_request'
        ).get(pk=run_id)
        if run.status in (
            AutopilotRun.Status.COMPLETED, AutopilotRun.Status.FAILED,
            AutopilotRun.Status.STOPPED, AutopilotRun.Status.WAITING_REVIEW,
            AutopilotRun.Status.RUNNING,
        ):
            return {'status': run.status}
        prior_status = run.status
        run.status = AutopilotRun.Status.RUNNING
        run.started_at = run.started_at or timezone.now()
        run.error = ''
        run.error_code = ''
        run.save(update_fields=['status', 'started_at', 'error', 'error_code', 'updated_at'])

    policy = run.policy
    policy.refresh_from_db()
    try:
        # Policy caps gate NEW spend only, so they are enforced just before a
        # generation is bought (below). A run resuming from
        # WAITING_GENERATION has already paid for its answer; failing it on a
        # cap crossed mid-wait would orphan the draft the money bought.
        # Emergency stop still halts waiting runs directly (emergency_stop).
        if prior_status == AutopilotRun.Status.WAITING_GENERATION:
            generation = run.generation_request
            if generation is None:
                raise AutopilotBlocked('GENERATION_MISSING', 'The generation request is missing.')
            generation.refresh_from_db()
            if generation.status in (
                GeminiGenerationRequest.Status.PENDING,
                GeminiGenerationRequest.Status.GENERATING,
            ):
                run.status = AutopilotRun.Status.WAITING_GENERATION
                run.next_check_at = timezone.now() + timedelta(seconds=30)
                run.save(update_fields=['status', 'next_check_at', 'updated_at'])
                return {'status': run.status}
            if generation.status == GeminiGenerationRequest.Status.FAILED:
                return _fail(run, 'GENERATION_FAILED', generation.error_message or 'Generation failed.')
            content = _content_from_generation(run)
            if content is None:
                return _fail(run, 'CONTENT_MISSING', 'Generation completed without durable content.')
            run.content_item = content
            _step(run, 'generate', 'COMPLETED', content_item_id=str(content.pk))
            if policy.mode == AutopilotPolicy.Mode.APPROVAL_REQUIRED:
                content.status = ContentItem.Status.PENDING_REVIEW
                content.save(update_fields=['status', 'updated_at'])
                run.status = AutopilotRun.Status.WAITING_REVIEW
                run.next_check_at = None
                run.save(update_fields=['content_item', 'status', 'next_check_at', 'updated_at'])
                _step(run, 'review', 'WAITING', content_item_id=str(content.pk))
                return {'status': run.status, 'content_item_id': str(content.pk)}
            run.status = AutopilotRun.Status.COMPLETED
            run.completed_at = timezone.now()
            run.next_check_at = None
            run.save(update_fields=[
                'content_item', 'status', 'completed_at', 'next_check_at', 'updated_at'
            ])
            _step(run, 'finish', 'COMPLETED', outcome='DRAFT_CREATED')
            return {'status': run.status, 'content_item_id': str(content.pk)}
        _enforce_policy(policy, run)
        return _queue_generation(run, policy)
    except AutopilotBlocked as exc:
        return _fail(run, exc.code, str(exc))
    except Exception as exc:
        return _fail(run, type(exc).__name__.upper()[:80], str(exc))


#: A run may wait on its generation this long before the wait itself fails.
#: Generous on purpose: the generation queue has its own rescue-and-retry
#: ladder, and this bound only catches paths no rescue covers (for example a
#: generation row created but never enqueued because the worker died between
#: the two).
WAITING_GENERATION_DEADLINE = timedelta(hours=2)

#: A run RUNNING longer than this was abandoned mid-execute by a dead worker.
#: The execute body is synchronous seconds of work, and its re-entry guard
#: would otherwise block the run forever.
RUNNING_STALE_AFTER = timedelta(minutes=30)

#: How far the sweep pushes next_check_at when it claims a run. Doubles as
#: the retry interval if the enqueue it then attempts is lost.
SWEEP_RECHECK_INTERVAL = timedelta(seconds=60)

#: A run QUEUED longer than this has lost its durable task (crashed out of
#: all its attempts, or never enqueued). QUEUED means the RUNNING claim never
#: committed, so nothing was spent and re-enqueueing is free of double-spend:
#: at most one execution proceeds past the select_for_update claim.
QUEUED_STALE_AFTER = timedelta(minutes=10)


def enqueue_due_autopilot_runs(now=None):
    """Turns DAILY/WEEKLY policies whose time has come into queued runs.

    Claiming is a compare-and-swap on next_run_at (the stalled-run sweep's
    idiom): the conditional .update() is filtered on the value this sweep
    read, so of two workers sweeping the same tick exactly one creates the
    run. next_run_at advances from the due slot by whole intervals until it
    is in the future — an overdue policy catches up by skipping missed slots,
    ONE run per sweep pass, never a backfill burst. The unique
    (workspace, dedupe_key) constraint is the second line of defence: a
    duplicate slot key means the run already exists, which is the outcome we
    wanted, not an error. Every run created here still passes
    _enforce_policy (spend approval, daily limit, monthly cap) inside
    execute_run before any generation is bought.
    """
    now = now or timezone.now()
    created = 0
    due = AutopilotPolicy.objects.filter(
        enabled=True, paused=False, emergency_stop=False,
        cadence__in=(AutopilotPolicy.Cadence.DAILY, AutopilotPolicy.Cadence.WEEKLY),
        next_run_at__isnull=False, next_run_at__lte=now,
    ).values_list('id', 'cadence', 'next_run_at')
    for policy_id, cadence, due_slot in list(due):
        try:
            interval = AutopilotPolicy.CADENCE_INTERVALS[cadence]
            next_slot = due_slot + interval
            while next_slot <= now:
                next_slot += interval
            run = None
            # Claim and create commit together: a crash after a committed
            # claim would advance the schedule with no run row and nothing to
            # retry — the slot silently lost. Atomic, the claim rolls back
            # with the failure and the next tick retries the slot.
            with transaction.atomic():
                if not _claim_due_slot(policy_id, due_slot, next_slot, now):
                    continue  # another sweep (or a concurrent edit) owns this slot
                policy = AutopilotPolicy.objects.select_related('workspace').get(pk=policy_id)
                try:
                    with transaction.atomic():
                        run = create_run(
                            policy,
                            scheduled_for=due_slot,
                            dedupe_key=f'sched:{policy_id}:{due_slot.isoformat()}',
                        )
                except IntegrityError:
                    # This slot's run already exists. The savepoint rolled the
                    # create back; the committed claim still advances the
                    # schedule past the already-covered slot.
                    run = None
            if run is None:
                continue
            created += 1
            # Outside the claim transaction: if the process dies between the
            # commit and this enqueue, the run exists as QUEUED with a dead
            # task and the QUEUED-stale rescue re-drives it — never silent.
            try:
                _enqueue_execute(run)
            except AutopilotQueueUnavailable:
                # The run is already marked FAILED / QUEUE_ENQUEUE_FAILED and
                # can be retried from the control centre; the schedule keeps
                # moving regardless.
                pass
        except Exception:
            # One bad policy must not stop the rest of the schedule.
            logger.exception('Scheduled autopilot policy %s could not be swept', policy_id)
    return created


def _claim_due_slot(policy_id, due_slot, next_slot, now):
    """Advance next_run_at only if it still holds the slot we read.

    The compare-and-swap that makes two concurrent sweeps create one run:
    the loser's update matches zero rows because the winner already moved
    next_run_at. Kept as its own function so the conditional filter is
    directly pinned by test — the dedupe constraint would mask its loss.
    """
    return AutopilotPolicy.objects.filter(
        pk=policy_id, next_run_at=due_slot,
    ).update(next_run_at=next_slot, updated_at=now)


def sweep_stalled_autopilot_runs(now=None):
    """Re-drives runs whose generation follow-up never arrived.

    The fast path is event-driven: the generation task queues a follow-up
    when it finishes. This sweep is the liveness guarantee behind it — a
    follow-up can be lost to a dead worker, a queue hiccup, or a terminal
    path that never knew about the run. Claiming is a compare-and-swap on
    next_check_at (the gemini sweep's retry_count idiom) so two workers
    sweeping at once re-drive a run exactly once, and every claim only
    re-runs the existing execute_run state machine — no new generation is
    created, so a sweep can never spend money.
    """
    from .tasks import execute_autopilot_run

    now = now or timezone.now()
    swept = 0

    due = AutopilotRun.objects.filter(
        status=AutopilotRun.Status.WAITING_GENERATION, next_check_at__lte=now,
    ).values_list('id', 'started_at', 'generation_request_id')
    for run_id, started_at, generation_id in list(due):
        claimed = AutopilotRun.objects.filter(
            pk=run_id,
            status=AutopilotRun.Status.WAITING_GENERATION,
            next_check_at__lte=now,
        ).update(next_check_at=now + SWEEP_RECHECK_INTERVAL, updated_at=now)
        if not claimed:
            continue
        if started_at and now - started_at > WAITING_GENERATION_DEADLINE:
            # A long wait is only a dead end when no answer exists. A worker
            # outage longer than the deadline is precisely the case where the
            # generation may have COMPLETED with nobody left to say so —
            # failing without looking would discard paid work and invite the
            # user to pay for it again. Terminal generations fall through to
            # the re-drive, where the state machine lands the honest outcome.
            generation_status = GeminiGenerationRequest.objects.filter(
                pk=generation_id
            ).values_list('status', flat=True).first()
            if generation_status not in (
                GeminiGenerationRequest.Status.COMPLETED,
                GeminiGenerationRequest.Status.FAILED,
            ):
                # Guarded like the RUNNING branch: a run a concurrent
                # follow-up just advanced must never be clobbered to FAILED.
                failed = AutopilotRun.objects.filter(
                    pk=run_id, status=AutopilotRun.Status.WAITING_GENERATION,
                ).update(
                    status=AutopilotRun.Status.FAILED,
                    error_code='GENERATION_STUCK',
                    error='Generation did not finish in time. Trigger the policy again.',
                    completed_at=now,
                    next_check_at=None,
                    updated_at=now,
                )
                if failed:
                    _step(
                        AutopilotRun.objects.get(pk=run_id), 'finish', 'FAILED',
                        code='GENERATION_STUCK',
                        message='Generation did not finish in time.',
                    )
                    swept += 1
                continue
        try:
            execute_autopilot_run.enqueue(str(run_id))
            swept += 1
        except Exception:
            # The pushed next_check_at doubles as the retry timer: the next
            # pass tries again instead of this one dying mid-list.
            logger.exception('Stalled autopilot run %s could not be re-queued', run_id)

    # QUEUED runs whose durable task died — crashed out of every attempt, or
    # was never enqueued. The status proves execute_run's first save never
    # committed, so no generation exists and re-driving spends nothing. The
    # CAS is on updated_at: claiming touches it, so of two concurrent sweeps
    # only one update matches the old timestamp.
    queued_cutoff = now - QUEUED_STALE_AFTER
    lost = AutopilotRun.objects.filter(
        status=AutopilotRun.Status.QUEUED, updated_at__lt=queued_cutoff,
    ).values_list('id', 'updated_at')
    for run_id, seen_updated_at in list(lost):
        claimed = AutopilotRun.objects.filter(
            pk=run_id, status=AutopilotRun.Status.QUEUED,
            updated_at=seen_updated_at,
        ).update(updated_at=now)
        if not claimed:
            continue
        try:
            execute_autopilot_run.enqueue(str(run_id))
            swept += 1
            logger.warning('Autopilot run %s lost its task while QUEUED; re-queued', run_id)
        except Exception:
            logger.exception('Lost QUEUED autopilot run %s could not be re-queued', run_id)

    cutoff = now - RUNNING_STALE_AFTER
    stale = AutopilotRun.objects.filter(
        status=AutopilotRun.Status.RUNNING, updated_at__lt=cutoff,
    ).values_list('id', flat=True)
    for run_id in list(stale):
        # No re-enqueue here: RUNNING may have died between creating a
        # generation and recording it, and re-executing could pay for the
        # same work twice. Failing honestly is the only spend-safe recovery.
        claimed = AutopilotRun.objects.filter(
            pk=run_id, status=AutopilotRun.Status.RUNNING, updated_at__lt=cutoff,
        ).update(
            status=AutopilotRun.Status.FAILED,
            error_code='RUN_INTERRUPTED',
            error='The worker executing this run was interrupted. Trigger the policy again.',
            completed_at=now,
            next_check_at=None,
            updated_at=now,
        )
        if claimed:
            _step(
                AutopilotRun.objects.get(pk=run_id), 'finish', 'FAILED',
                code='RUN_INTERRUPTED', message='Worker interrupted mid-run.',
            )
            swept += 1
    return swept


@transaction.atomic
def emergency_stop(policy, *, by=None):
    policy = AutopilotPolicy.objects.select_for_update().get(pk=policy.pk)
    policy.emergency_stop = True
    policy.paused = True
    policy.save(update_fields=['emergency_stop', 'paused', 'updated_at'])
    now = timezone.now()
    for run in policy.runs.filter(status__in=[
        AutopilotRun.Status.QUEUED, AutopilotRun.Status.RUNNING,
        AutopilotRun.Status.WAITING_GENERATION, AutopilotRun.Status.WAITING_REVIEW,
    ]):
        run.status = AutopilotRun.Status.STOPPED
        run.error_code = 'EMERGENCY_STOP'
        run.error = 'Stopped by workspace administrator.'
        run.completed_at = now
        run.next_check_at = None
        run.save(update_fields=[
            'status', 'error_code', 'error', 'completed_at', 'next_check_at', 'updated_at'
        ])
        _step(run, 'finish', 'STOPPED', by=getattr(by, 'pk', None))
    return policy
