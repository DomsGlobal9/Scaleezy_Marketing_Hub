"""PR7 Super Admin controls for derived cross-client learned patterns."""
from django.tasks import TaskResultStatus
from rest_framework import status

from apps.common.responses import APIResponse
from apps.jobs.models import TaskRun
from apps.universal.models import LearnedPattern, LifecycleStatus
from apps.universal.services import publish_pattern, retire_pattern
from apps.universal.tasks import compile_learned_patterns_task
from apps.workspaces.models import MarketingWorkspace

from .views import PlatformView

#: The one task_path the status route below will reveal. Anything else is a
#: 404 — the console gets to watch its own compile, not browse the queue.
COMPILE_TASK_PATH = 'apps.universal.tasks.compile_learned_patterns_task'


def pattern_payload(pattern):
    """Platform list shape. Contributor ids require the separately audited route."""
    return {
        'id': str(pattern.pk),
        'category': pattern.category,
        'attribute': pattern.attribute,
        'value': pattern.value,
        'industry': pattern.industry,
        'channel': pattern.channel,
        'contributor_count': pattern.contributor_count,
        'supporting_brand_count': pattern.supporting_brand_count,
        'confidence': pattern.confidence,
        'status': pattern.status,
        'compiled_at': pattern.compiled_at.isoformat(),
        'pattern_version': pattern.pattern_version,
        'published_at': pattern.published_at.isoformat() if pattern.published_at else None,
        'retired_at': pattern.retired_at.isoformat() if pattern.retired_at else None,
    }


class PatternListView(PlatformView):
    def get(self, request):
        rows = LearnedPattern.objects.all()
        wanted = str(request.query_params.get('status', '')).upper()
        if wanted in LifecycleStatus.values:
            rows = rows.filter(status=wanted)
        category = str(request.query_params.get('category', '')).strip()
        if category:
            rows = rows.filter(category__iexact=category)
        direction = str(request.query_params.get('sort', 'contributors_desc')).lower()
        ordering = 'contributor_count' if direction == 'contributors_asc' else '-contributor_count'
        rows = list(rows.order_by(ordering, 'category', 'attribute')[:500])
        self.audit('LEARNED_PATTERNS_VIEWED', detail={
            'status': wanted or 'ALL', 'count': len(rows), 'sort': direction,
        })
        return APIResponse(success=True, data={
            'count': len(rows),
            'patterns': [pattern_payload(row) for row in rows],
        })


class PatternContributorsView(PlatformView):
    def get(self, request, pattern_id):
        pattern = LearnedPattern.objects.filter(pk=pattern_id).first()
        if pattern is None:
            return self.not_found('Pattern')
        ids = [str(value) for value in (pattern.contributing_workspace_ids or [])]
        clients = list(
            MarketingWorkspace.objects.filter(pk__in=ids)
            .order_by('client_code')
            .values('id', 'client_code', 'workspace_name')
        )
        payload = [
            {
                'workspace_id': str(row['id']),
                'client_code': row['client_code'],
                'name': row['workspace_name'],
            }
            for row in clients
        ]
        self.audit(
            'LEARNED_PATTERN_CONTRIBUTORS_VIEWED',
            target=f'pattern:{pattern.pk}',
            detail={'contributor_count': len(payload)},
        )
        return APIResponse(success=True, data={
            'pattern_id': str(pattern.pk),
            'contributors': payload,
        })


class PatternLifecycleView(PlatformView):
    def post(self, request, pattern_id, move):
        pattern = LearnedPattern.objects.filter(pk=pattern_id).first()
        if pattern is None:
            return self.not_found('Pattern')
        if move == 'publish':
            publish_pattern(pattern, by=request.user)
            message = 'Pattern published.'
        elif move == 'retire':
            reason = str(request.data.get('reason', ''))[:255]
            retire_pattern(pattern, by=request.user, reason=reason)
            message = 'Pattern retired; it stops reaching generations immediately.'
        else:
            return self.not_found('Action')
        pattern.refresh_from_db()
        return APIResponse(success=True, message=message, data=pattern_payload(pattern))


class PatternCompileView(PlatformView):
    def post(self, request):
        task_result = compile_learned_patterns_task.enqueue(actor_id=request.user.pk)
        current = (
            LearnedPattern.objects.order_by('-compiled_at')
            .values_list('pattern_version', flat=True).first()
        )
        self.audit(
            'LEARNED_PATTERN_COMPILE_QUEUED',
            target=f'task:{task_result.id}',
            detail={'current_pattern_version': current or ''},
        )
        return APIResponse(
            success=True,
            message='Pattern compilation queued.',
            data={
                'status': 'QUEUED',
                'task_id': str(task_result.id),
                'pattern_version': current or None,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class PatternCompileStatusView(PlatformView):
    """GET /api/platform/patterns/compile/<task_id>/ — one queued compile.

    Polled by the Learned Patterns page after it queues a compile, so the
    operator sees running → succeeded / failed instead of "refresh and hope".
    Scoped to `COMPILE_TASK_PATH`: any other task id is Not Found, which keeps
    this a compile-status route rather than a general task browser.
    """

    def get(self, request, task_id):
        run = TaskRun.objects.filter(
            pk=str(task_id)[:32], task_path=COMPILE_TASK_PATH,
        ).first()
        if run is None:
            return self.not_found('Compile task')

        error = ''
        if run.status == TaskResultStatus.FAILED and run.errors:
            last = run.errors[-1] or {}
            # A short tail of the last traceback names the failure without
            # shipping 8 KB of frames to the console.
            error = str(last.get('traceback') or '')[-500:].strip()
            if not error:
                error = str(last.get('exception_class_path') or '')

        # This is a 3-second poll: an audit row per tick would be noise, so
        # only the observation that matters — the terminal state — is
        # recorded, once, when the poller sees it and stops.
        if run.is_finished:
            self.audit(
                'LEARNED_PATTERN_COMPILE_STATUS_VIEWED',
                target=f'task:{run.pk}',
                detail={'status': run.status, 'attempts': run.attempts},
            )
        return APIResponse(success=True, data={
            'task_id': run.pk,
            'status': run.status,
            'enqueued_at': run.enqueued_at.isoformat(),
            'finished_at': run.finished_at.isoformat() if run.finished_at else None,
            'attempts': run.attempts,
            'error': error,
        })
