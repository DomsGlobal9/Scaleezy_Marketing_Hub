from django.db import models
from django.tasks import TaskResultStatus


class TaskRun(models.Model):
    """
    One enqueued background task, durable in Postgres.

    Django 6.1 ships the Tasks API but only an immediate (in-process) and a
    dummy backend, so nothing survives the request that enqueued it. This is
    the storage behind a database backend: the queue is the database we
    already run, which is the whole reason Phase 8 does not need Celery, Redis
    or a second service.
    """

    #: Matches TaskResult.id, which the framework generates as a 32-char token.
    id = models.CharField(primary_key=True, max_length=32, editable=False)

    #: Import path of the @task-decorated callable, e.g.
    #: "apps.publishing.tasks.publish_job".
    task_path = models.CharField(max_length=255)
    args = models.JSONField(default=list, blank=True)
    kwargs = models.JSONField(default=dict, blank=True)

    queue_name = models.CharField(max_length=64, default='default')
    priority = models.IntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=TaskResultStatus.choices, default=TaskResultStatus.READY
    )

    #: Earliest the task may run. This is what makes scheduled publishing
    #: possible without a second scheduling mechanism.
    run_after = models.DateTimeField(null=True, blank=True)

    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    #: Set while a worker holds the row, so a crashed worker's task can be
    #: reclaimed rather than being stuck RUNNING forever.
    claimed_at = models.DateTimeField(null=True, blank=True)

    worker_ids = models.JSONField(default=list, blank=True)
    errors = models.JSONField(default=list, blank=True)
    return_value = models.JSONField(null=True, blank=True)

    enqueued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'task_runs'
        ordering = ['-enqueued_at']
        indexes = [
            # The claim query: ready tasks on a queue, due now, best priority
            # first.
            models.Index(fields=['status', 'queue_name', 'run_after']),
            models.Index(fields=['status', '-priority', 'enqueued_at']),
        ]

    def __str__(self):
        return f"{self.task_path} ({self.status})"

    @property
    def is_finished(self) -> bool:
        return self.status in (TaskResultStatus.SUCCESSFUL, TaskResultStatus.FAILED)

    @property
    def can_retry(self) -> bool:
        return self.attempts < self.max_attempts
