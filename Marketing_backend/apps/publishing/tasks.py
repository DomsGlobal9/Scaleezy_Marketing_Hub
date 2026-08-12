from celery import shared_task
from django.utils import timezone
from .models import PublishingJob, PublishingJobItem
from apps.social_accounts.views import SocialConnectionViewSet

@shared_task
def process_publishing_job(job_id):
    """
    Main orchestrator task. Fans out to individual platform tasks.
    """
    try:
        job = PublishingJob.objects.get(id=job_id)
        job.status = PublishingJob.Status.PUBLISHING
        job.started_at = timezone.now()
        job.save()

        # Fan out
        for item in job.items.all():
            item.status = PublishingJobItem.Status.QUEUED
            item.save()
            process_publishing_job_item.delay(item.id)
            
    except PublishingJob.DoesNotExist:
        pass

@shared_task(bind=True, max_retries=3)
def process_publishing_job_item(self, item_id):
    """
    Executes the publishing for a single social platform.
    """
    try:
        item = PublishingJobItem.objects.select_related('social_connection', 'publishing_job__asset').get(id=item_id)
        
        item.status = PublishingJobItem.Status.PUBLISHING
        item.save()
        
        connection = item.social_connection
        asset = item.publishing_job.asset
        
        # Instantiate the correct adapter (using the helper from views for MVP)
        viewset = SocialConnectionViewSet()
        adapter = viewset.get_adapter(connection.platform)
        
        if not adapter:
            raise Exception(f"Adapter for {connection.platform} not found.")
            
        # Mock content package
        content = {
            "asset_url": asset.file_url,
            "text": "Generated or uploaded content here" 
        }
        
        # In real app: decrypt access token
        access_token = connection.access_token_encrypted
        
        # Publish
        result = adapter.publish(access_token, content)
        
        item.status = PublishingJobItem.Status.PUBLISHED
        item.external_post_id = result.get('id')
        item.published_at = timezone.now()
        item.save()
        
        check_job_completion(item.publishing_job_id)
        
    except Exception as e:
        item = PublishingJobItem.objects.get(id=item_id)
        item.status = PublishingJobItem.Status.FAILED
        item.error_message = str(e)
        item.failed_at = timezone.now()
        item.save()
        check_job_completion(item.publishing_job_id)
        
        # Simple retry logic fallback
        if connection.settings.automatic_retry_enabled and self.request.retries < self.max_retries:
            item.status = PublishingJobItem.Status.RETRYING
            item.retry_count += 1
            item.save()
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries)) # Exponential backoff


def check_job_completion(job_id):
    """
    Checks if all items in a job are completed (Published or Failed).
    If so, marks the Job as COMPLETED or PARTIALLY_PUBLISHED or FAILED.
    """
    job = PublishingJob.objects.get(id=job_id)
    items = job.items.all()
    
    total = items.count()
    completed = items.filter(status=PublishingJobItem.Status.PUBLISHED).count()
    failed = items.filter(status=PublishingJobItem.Status.FAILED).count()
    
    if completed + failed == total:
        job.completed_at = timezone.now()
        if completed == total:
            job.status = PublishingJob.Status.PUBLISHED
        elif failed == total:
            job.status = PublishingJob.Status.FAILED
        else:
            job.status = PublishingJob.Status.PARTIALLY_PUBLISHED
        job.save()
