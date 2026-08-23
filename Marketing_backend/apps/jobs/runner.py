"""
The worker.

Claims one ready task at a time and runs it. Claiming is a locked read so two
workers on two dynos cannot both take the same row; on Postgres that is
SELECT ... FOR UPDATE SKIP LOCKED, and on SQLite (tests) the lock is the whole
database anyway.
"""
import logging
from datetime import timedelta

from django.db import connection, transaction
from django.tasks import TaskContext, TaskResultStatus
from django.tasks.signals import task_finished, task_started
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.module_loading import import_string

from .backend import DatabaseBackend, mark_failed, mark_started, mark_succeeded
from .models import TaskRun

logger = logging.getLogger(__name__)

#: A task still RUNNING after this long is assumed to belong to a worker that
#: died, and becomes claimable again.
STALE_AFTER = timedelta(minutes=30)


def reclaim_stale(now=None):
    """Returns rows abandoned by a dead worker to the ready queue."""
    now = now or timezone.now()
    return TaskRun.objects.filter(
        status=TaskResultStatus.RUNNING, claimed_at__lt=now - STALE_AFTER
    ).update(status=TaskResultStatus.READY, claimed_at=None)


def claim(queue_name=None, now=None):
    """
    Takes the next due task, or returns None.

    The status flip happens inside the same transaction as the locked read,
    which is what stops a second worker picking up the same row.
    """
    now = now or timezone.now()

    with transaction.atomic():
        rows = (
            TaskRun.objects.filter(status=TaskResultStatus.READY)
            .filter(models_due(now))
            .order_by('-priority', 'enqueued_at')
        )
        if queue_name:
            rows = rows.filter(queue_name=queue_name)

        if connection.features.has_select_for_update_skip_locked:
            rows = rows.select_for_update(skip_locked=True)
        elif connection.features.has_select_for_update:
            rows = rows.select_for_update()

        run = rows.first()
        if run is None:
            return None

        worker_id = get_random_string(32)
        mark_started(run, worker_id)
        return run


def models_due(now):
    """Q object for "no run_after, or run_after has passed"."""
    from django.db.models import Q

    return Q(run_after__isnull=True) | Q(run_after__lte=now)


def execute(run: TaskRun):
    """
    Runs one claimed task. Never raises: a task blowing up must not take the
    worker down with it.
    """
    backend = DatabaseBackend(alias='default', params={})
    try:
        task = import_string(run.task_path)
    except Exception as exc:
        logger.exception("Task %s could not be imported", run.task_path)
        # An unimportable path will not become importable on a retry.
        mark_failed(run, exc, retry=False)
        return False

    result = backend.result_from(run, task=task)
    task_started.send(sender=DatabaseBackend, task_result=result)

    try:
        if task.takes_context:
            value = task.call(TaskContext(task_result=result), *(run.args or []),
                              **(run.kwargs or {}))
        else:
            value = task.call(*(run.args or []), **(run.kwargs or {}))
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 - the worker must survive
        logger.exception("Task %s (%s) failed", run.task_path, run.pk)
        mark_failed(run, exc, retry=True)
        task_finished.send(
            sender=DatabaseBackend, task_result=backend.result_from(run, task=task)
        )
        return False

    mark_succeeded(run, value)
    task_finished.send(
        sender=DatabaseBackend, task_result=backend.result_from(run, task=task)
    )
    return True


def run_once(queue_name=None, limit=None):
    """
    Drains the ready queue and returns how many tasks ran.

    Also sweeps for work that became due since the last pass — scheduled
    publishing, principally — so a single cron invocation of
    `manage.py run_tasks --once` is a complete tick.
    """
    enqueue_due_work()
    reclaim_stale()

    processed = 0
    while limit is None or processed < limit:
        run = claim(queue_name)
        if run is None:
            break
        execute(run)
        processed += 1
    return processed


def enqueue_due_work():
    """
    Turns time-based state into queued tasks.

    Kept here rather than in a second scheduler process: the worker is already
    running on a timer, and a separate scheduler would be another thing to
    deploy and another thing to forget to deploy.
    """
    from apps.publishing.scheduler import enqueue_due_jobs
    from apps.universal.tasks import enqueue_due_enrichment

    count = 0
    try:
        count += enqueue_due_jobs()
    except Exception:
        logger.exception("Scheduled work sweep failed")
    try:
        count += enqueue_due_enrichment()
    except Exception:
        logger.exception("Recurring enrichment sweep failed")
    return count
