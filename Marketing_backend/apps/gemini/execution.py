"""Compact generation state derived from the existing durable task owner."""
from django.tasks import TaskResultStatus

from apps.jobs.models import TaskRun


def active_runs(request_ids):
    ids = [str(value) for value in request_ids]
    states = {}
    if not ids:
        return states
    for args, status in TaskRun.objects.filter(
        task_path='apps.gemini.tasks.generate_content',
        args__0__in=ids,
        status__in=[TaskResultStatus.READY, TaskResultStatus.RUNNING],
    ).values_list('args', 'status'):
        key = str(args[0])
        if states.get(key) != TaskResultStatus.RUNNING:
            states[key] = status
    return states


def execution_state(request, runs=None):
    runs = active_runs([request.pk]) if runs is None else runs
    owned = runs.get(str(request.pk))
    result = getattr(request, 'result', None)
    metadata = (result.metadata or {}) if result is not None else {}
    partial = (metadata.get('media') or {}).get('status') == 'FAILED'
    if owned:
        state = 'RETRY_PENDING' if owned == TaskResultStatus.READY and request.status == 'FAILED' else (
            'RUNNING' if owned == TaskResultStatus.RUNNING else 'QUEUED'
        )
    elif request.status == 'COMPLETED':
        state = 'PARTIAL' if partial else 'COMPLETED'
    else:
        state = {'PENDING': 'QUEUED', 'GENERATING': 'RUNNING'}.get(request.status, request.status)
    terminal = not owned and request.status in {'COMPLETED', 'FAILED'}
    return {
        'state': state,
        'terminal': terminal,
        # A saved partial belongs to its image-repair path, never a second
        # full generation that would repurchase successful copy.
        'retry_allowed': terminal and request.status == 'FAILED' and result is None,
        'image_retry_allowed': terminal and partial,
    }


def media_outcome(item, routed):
    capabilities = (routed.get('trace') or {}).get('capabilities') or {}
    failed = item.asset_id is None
    image = capabilities.get('IMAGE') or {}
    return {
        'status': 'FAILED' if failed else 'READY',
        'error': (image.get('error') or 'The image was not saved. Your copy is preserved.') if failed else '',
    }
