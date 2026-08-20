"""
A database-backed task backend for Django's Tasks API.

Django 6.1 defines the API and ships an immediate backend that runs the task
inside the request that enqueued it — useful in development, useless for the
two things Phase 8 needs: work that outlives the request, and work that runs
later. This backend stores the enqueued task in the database we already have,
and `manage.py run_tasks` executes it.

Deliberately not Celery: no broker, no Redis, no second service to pay for or
operate. At this volume Postgres is a perfectly good queue.
"""
from datetime import timedelta

from django.tasks import TaskResult, TaskResultStatus
from django.tasks.backends.base import BaseTaskBackend
from django.tasks.base import TaskError
from django.tasks.exceptions import TaskResultDoesNotExist
from django.tasks.signals import task_enqueued
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.json import normalize_json
from django.utils.module_loading import import_string

from .models import TaskRun

#: Base delay before a failed task is retried, doubling each attempt. Without
#: it a failure is retried inside the same worker pass, microseconds later —
#: which is useless against the things that actually fail here (a rate-limited
#: API, a provider blip) and burns every attempt in one go.
RETRY_BACKOFF_SECONDS = 30


class DatabaseBackend(BaseTaskBackend):
    supports_defer = True
    supports_get_result = True
    supports_priority = True
    # Coroutines would have to be run by the worker's event loop; nothing here
    # needs one yet, so it stays off rather than half-supported.
    supports_async_task = False

    def __init__(self, alias, params):
        super().__init__(alias, params)
        self.max_attempts = int(self.options.get('MAX_ATTEMPTS', 3))

    def enqueue(self, task, args, kwargs):
        self.validate_task(task)

        run = TaskRun.objects.create(
            id=get_random_string(32),
            task_path=task.module_path,
            args=normalize_json(list(args)),
            kwargs=normalize_json(dict(kwargs)),
            queue_name=task.queue_name,
            priority=task.priority,
            run_after=task.run_after,
            max_attempts=self.max_attempts,
            status=TaskResultStatus.READY,
        )

        result = self.result_from(run, task=task)
        task_enqueued.send(type(self), task_result=result)
        return result

    def get_result(self, result_id):
        try:
            run = TaskRun.objects.get(pk=result_id)
        except TaskRun.DoesNotExist:
            raise TaskResultDoesNotExist(result_id) from None
        return self.result_from(run)

    # -- mapping ----------------------------------------------------------
    def result_from(self, run: TaskRun, task=None) -> TaskResult:
        """Rebuilds a TaskResult from a stored row."""
        if task is None:
            task = import_string(run.task_path)

        result = TaskResult(
            task=task,
            id=run.pk,
            status=run.status,
            enqueued_at=run.enqueued_at,
            started_at=run.started_at,
            last_attempted_at=run.last_attempted_at,
            finished_at=run.finished_at,
            args=run.args or [],
            kwargs=run.kwargs or {},
            backend=self.alias,
            errors=[TaskError(**e) for e in (run.errors or [])],
            worker_ids=list(run.worker_ids or []),
        )
        # TaskResult is frozen; the framework's own backends set this the same
        # way.
        object.__setattr__(result, '_return_value', run.return_value)
        return result


def mark_started(run: TaskRun, worker_id: str):
    now = timezone.now()
    run.status = TaskResultStatus.RUNNING
    run.started_at = run.started_at or now
    run.last_attempted_at = now
    run.claimed_at = now
    run.attempts += 1
    worker_ids = list(run.worker_ids or [])
    worker_ids.append(worker_id)
    run.worker_ids = worker_ids
    run.save(update_fields=[
        'status', 'started_at', 'last_attempted_at', 'claimed_at', 'attempts', 'worker_ids',
    ])


def mark_succeeded(run: TaskRun, return_value):
    run.status = TaskResultStatus.SUCCESSFUL
    run.finished_at = timezone.now()
    run.claimed_at = None
    try:
        run.return_value = normalize_json(return_value)
    except Exception:
        # A task may legitimately return something unserialisable; the run
        # still succeeded, so record that rather than failing it.
        run.return_value = None
    run.save(update_fields=['status', 'finished_at', 'claimed_at', 'return_value'])


def mark_failed(run: TaskRun, exc: BaseException, *, retry: bool):
    """
    Records the error, then either releases the row for another attempt or
    finishes it as failed.
    """
    from traceback import format_exception

    exception_type = type(exc)
    errors = list(run.errors or [])
    errors.append({
        'exception_class_path': (
            f"{exception_type.__module__}.{exception_type.__qualname__}"
        ),
        'traceback': ''.join(format_exception(exc))[:8000],
    })
    run.errors = errors
    run.claimed_at = None

    if retry and run.can_retry:
        run.status = TaskResultStatus.READY
        run.run_after = timezone.now() + timedelta(
            seconds=RETRY_BACKOFF_SECONDS * (2 ** max(0, run.attempts - 1))
        )
        run.save(update_fields=['status', 'errors', 'claimed_at', 'run_after'])
    else:
        run.status = TaskResultStatus.FAILED
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'errors', 'claimed_at', 'finished_at'])
