"""
Scheduled publishing.

`publish_mode=SCHEDULED` has always created a job with a `scheduled_at` and a
status of SCHEDULED — and then nothing ever ran it. A post scheduled for
Friday simply never went out. This is the sweep that closes that.
"""
import logging

from django.db import transaction
from django.utils import timezone

from .models import PublishingJob

logger = logging.getLogger(__name__)


def due_jobs(now=None):
    now = now or timezone.now()
    return PublishingJob.objects.filter(
        status=PublishingJob.Status.SCHEDULED,
        scheduled_at__isnull=False,
        scheduled_at__lte=now,
    )


def enqueue_due_jobs(now=None) -> int:
    """
    Moves every job whose time has come onto the queue, and returns how many.

    The status flips to QUEUED in the same transaction as the enqueue, so a
    sweep that overlaps the previous one cannot queue the same job twice.
    """
    from apps.publishing.tasks import publish_job

    count = 0
    for job_id in list(due_jobs(now).values_list('id', flat=True)):
        try:
            with transaction.atomic():
                claimed = (
                    PublishingJob.objects.select_for_update()
                    .filter(id=job_id, status=PublishingJob.Status.SCHEDULED)
                    .first()
                )
                if claimed is None:
                    continue  # another sweep got there first
                claimed.status = PublishingJob.Status.QUEUED
                claimed.save(update_fields=['status'])
                publish_job.enqueue(str(claimed.id))
            count += 1
        except Exception:
            # One bad job must not stop the rest of the schedule going out.
            logger.exception("Could not enqueue scheduled job %s", job_id)

    if count:
        logger.info("Enqueued %d scheduled publishing job(s)", count)
    return count
