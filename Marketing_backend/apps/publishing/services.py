from django.utils import timezone
from apps.publishing.models import PublishingJob, PublishingJobItem
from apps.social_accounts.integrations.x import XAdapter
from apps.social_accounts.utils.encryption import decrypt_token
from apps.audit.models import AuditLog

def execute_publishing_job(job_id: str):
    """
    Executes a publishing job synchronously.
    """
    try:
        job = PublishingJob.objects.get(id=job_id)
    except PublishingJob.DoesNotExist:
        return
        
    job.status = PublishingJob.Status.PUBLISHING
    job.started_at = timezone.now()
    job.save()

    all_success = True
    any_success = False

    for item in job.items.all():
        item.status = PublishingJobItem.Status.PUBLISHING
        item.save()

        platform = item.social_connection.platform
        if platform == 'X':
            adapter = XAdapter()
            try:
                # Decrypt token
                access_token = decrypt_token(item.social_connection.access_token_encrypted)
                if not access_token:
                    raise Exception("Access token missing")
                
                # Verify media url
                media_url = job.asset.file_url
                if not media_url:
                    raise Exception("No media URL found on asset")
                
                # 1. Upload media
                media_id = adapter.upload_media(access_token, media_url)
                
                # 2. Publish post. (Assuming the asset has some text. If not, default text)
                text = f"New post from Scaleezy Marketing Hub"
                post_result = adapter.publish_post(access_token, text, media_id)
                
                # Success
                item.status = PublishingJobItem.Status.PUBLISHED
                item.external_post_id = post_result.get("id")
                item.external_post_url = post_result.get("url")
                item.published_at = timezone.now()
                item.save()
                
                any_success = True
                
                # Audit log
                AuditLog.objects.create(
                    workspace=job.workspace,
                    platform=platform,
                    action="Published Post",
                    result="Success"
                )
                
            except Exception as e:
                item.status = PublishingJobItem.Status.FAILED
                item.error_message = str(e)
                item.failed_at = timezone.now()
                item.save()
                all_success = False
                
                AuditLog.objects.create(
                    workspace=job.workspace,
                    platform=platform,
                    action="Published Post",
                    result="Failed",
                    error=str(e)
                )
        else:
            item.status = PublishingJobItem.Status.FAILED
            item.error_message = "Platform not supported yet"
            item.failed_at = timezone.now()
            item.save()
            all_success = False

    job.completed_at = timezone.now()
    if all_success and any_success:
        job.status = PublishingJob.Status.PUBLISHED
    elif any_success:
        job.status = PublishingJob.Status.PARTIALLY_PUBLISHED
    else:
        job.status = PublishingJob.Status.FAILED
    job.save()
