"""Publishing as background work."""
import logging

from django.tasks import task

logger = logging.getLogger(__name__)


@task
def publish_job(job_id: str):
    """
    Runs one publishing job off the request thread.

    Thin on purpose: `execute_publishing_job` already handles per-item
    isolation and status transitions, and has been doing so since long before
    there was a queue. This only changes *where* it runs.
    """
    from apps.publishing.services import execute_publishing_job

    execute_publishing_job(job_id)
    return {'job': str(job_id)}
