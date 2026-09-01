"""Governed manual generation over the existing Context Gateway and AIRouter."""
import json
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.ai.models import AIUsageLog
from apps.billing.quota import enforce as enforce_billing
from apps.brands.services.approval import enforce_spend_approved
from apps.content.models import ContentItem
from apps.gemini.models import GeminiGenerationRequest
from apps.workspaces.models import MarketingWorkspace

from .models import AutopilotPolicy, AutopilotRun, AutopilotStep


class AutopilotBlocked(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


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
    ).exclude(status=AutopilotRun.Status.STOPPED).exclude(pk=run.pk).count()
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
    previous = AutopilotRun.objects.filter(policy=policy, created_at__lt=run.created_at).count()
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
        'layout': policy.brand.layout_preference,
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

    task_result = generate_content.enqueue(str(generation.pk))
    run.generation_request = generation
    run.task_id = str(task_result.id)
    run.status = AutopilotRun.Status.WAITING_GENERATION
    run.next_check_at = timezone.now() + timedelta(seconds=20)
    run.save(update_fields=[
        'generation_request', 'task_id', 'status', 'next_check_at', 'updated_at'
    ])
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
        run = AutopilotRun.objects.select_for_update().select_related(
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
        _enforce_policy(policy, run)
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
        return _queue_generation(run, policy)
    except AutopilotBlocked as exc:
        return _fail(run, exc.code, str(exc))
    except Exception as exc:
        return _fail(run, type(exc).__name__.upper()[:80], str(exc))


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
