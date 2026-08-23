"""PR7 Super Admin controls for derived cross-client learned patterns."""
from rest_framework import status

from apps.common.responses import APIResponse
from apps.universal.models import LearnedPattern, LifecycleStatus
from apps.universal.services import publish_pattern, retire_pattern
from apps.universal.tasks import compile_learned_patterns_task
from apps.workspaces.models import MarketingWorkspace

from .views import PlatformView


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
