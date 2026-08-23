"""
Publishing service — executes publishing jobs synchronously.

Supports X (Twitter) and LinkedIn platforms.
Each platform item is processed independently so one failure
does not block the others.
"""

import logging
from datetime import timedelta

import requests
from django.utils import timezone

from apps.publishing.models import PublishingJob, PublishingJobItem
from apps.social_accounts.integrations.x import XAdapter
from apps.social_accounts.integrations.linkedin import LinkedInAdapter
from apps.social_accounts.integrations.exceptions import (
    LinkedInAuthenticationError,
    LinkedInPermissionError,
    LinkedInPublishingError,
    LinkedInMediaUploadError,
    LinkedInRateLimitError,
    LinkedInAPIError,
)
from apps.social_accounts.integrations.meta.facebook import FacebookAdapter
from apps.social_accounts.integrations.meta.instagram import InstagramAdapter
from apps.social_accounts.integrations.meta.exceptions import (
    MetaAuthenticationError,
    MetaPermissionError,
    MetaRateLimitError,
    MetaPublishingError,
    MetaMediaUploadError,
)
from apps.social_accounts.integrations.youtube.youtube import YouTubeAdapter
from apps.social_accounts.integrations.youtube.exceptions import (
    YouTubeAuthenticationError,
    YouTubePermissionError,
    YouTubeRateLimitError,
    YouTubePublishingError,
    YouTubeMediaUploadError,
)
from apps.social_accounts.utils.encryption import decrypt_token, encrypt_token
from apps.audit.models import AuditLog
from apps.publishing.policy import (
    PublishingPolicyError,
    automatic_retry_enabled,
    enforce_connection_policy,
)

logger = logging.getLogger(__name__)


def execute_publishing_job(job_id: str):
    """
    Publishes every outstanding item on a job.

    Runs on the background worker rather than in the request that created the
    job — a multi-channel post with a video upload takes long enough to hit a
    gateway timeout, and when it did the request died mid-publish with some
    channels posted and nothing to resume it.

    Each item is independent: one platform failing does not stop the others.
    """
    try:
        job = PublishingJob.objects.get(id=job_id)
    except PublishingJob.DoesNotExist:
        return

    job.status = PublishingJob.Status.PUBLISHING
    job.started_at = timezone.now()
    job.save()

    for item in job.items.all():
        if item.status == PublishingJobItem.Status.PUBLISHED:
            # Already live with an external_post_id. Both retry paths re-run
            # the whole job, so without this a retry of one failed channel
            # posts a second copy to every channel that had succeeded.
            continue

        try:
            enforce_connection_policy(item.social_connection, at=timezone.now())
        except PublishingPolicyError as exc:
            item.status = PublishingJobItem.Status.FAILED
            item.error_code = exc.code
            item.error_message = str(exc)
            item.failed_at = timezone.now()
            item.save(update_fields=[
                'status', 'error_code', 'error_message', 'failed_at'
            ])
            continue

        item.status = PublishingJobItem.Status.PUBLISHING
        item.save()

        platform = item.social_connection.platform

        if platform == 'X':
            _publish_to_x(item, job)
        elif platform == 'LINKEDIN':
            _publish_to_linkedin(item, job)
        elif platform == 'FACEBOOK':
            _publish_to_facebook(item, job)
        elif platform == 'INSTAGRAM':
            _publish_to_instagram(item, job)
        elif platform == 'YOUTUBE':
            _publish_to_youtube(item, job)
        else:
            item.status = PublishingJobItem.Status.FAILED
            item.error_code = "UNSUPPORTED_PLATFORM"
            item.error_message = "Platform not supported yet"
            item.failed_at = timezone.now()
            item.save()
            continue

    # Judged from the final state of every item, including ones that were
    # already published before this run.
    statuses = list(job.items.values_list('status', flat=True))
    any_success = any(s == PublishingJobItem.Status.PUBLISHED for s in statuses)
    all_success = bool(statuses) and all(
        s == PublishingJobItem.Status.PUBLISHED for s in statuses
    )

    policy_failures = {
        'PUBLISHING_PAUSED', 'OUTSIDE_PUBLISHING_WINDOW',
        'DAILY_POST_LIMIT_REACHED', 'UNSUPPORTED_PLATFORM',
    }
    retryable = [
        item for item in job.items.select_related('social_connection').filter(
            status=PublishingJobItem.Status.FAILED, retry_count__lt=2
        )
        if item.error_code not in policy_failures
        and automatic_retry_enabled(item.social_connection)
    ]
    if retryable:
        from apps.publishing.tasks import publish_job

        for item in retryable:
            item.status = PublishingJobItem.Status.RETRYING
            item.retry_count += 1
            item.save(update_fields=['status', 'retry_count'])
        job.status = PublishingJob.Status.PUBLISHING
        job.completed_at = None
        job.save(update_fields=['status', 'completed_at'])
        delay = max(item.retry_count for item in retryable) * 5
        publish_job.using(run_after=timezone.now() + timedelta(minutes=delay)).enqueue(
            str(job.id)
        )
        return

    job.completed_at = timezone.now()
    if all_success and any_success:
        job.status = PublishingJob.Status.PUBLISHED
    elif any_success:
        job.status = PublishingJob.Status.PARTIALLY_PUBLISHED
    else:
        job.status = PublishingJob.Status.FAILED
    job.save()

    if all_success and job.content_item_id:
        from apps.content.models import ContentItem

        ContentItem.objects.filter(
            id=job.content_item_id,
            workspace_id=job.workspace_id,
            status=ContentItem.Status.APPROVED,
        ).update(status=ContentItem.Status.PUBLISHED, updated_at=timezone.now())


def _publish_to_x(item: PublishingJobItem, job: PublishingJob):
    """Publish to X/Twitter."""
    adapter = XAdapter()
    try:
        access_token = decrypt_token(item.social_connection.access_token_encrypted)
        if not access_token:
            raise Exception("Access token missing")

        media_url = job.asset.file_url
        if not media_url:
            raise Exception("No media URL found on asset")

        # 1. Upload media
        media_id = adapter.upload_media(access_token, media_url)

        # 2. Publish post
        text = job.caption or "New post from Scaleezy Marketing Hub"
        post_result = adapter.publish_post(access_token, text, media_id)

        # Success
        item.status = PublishingJobItem.Status.PUBLISHED
        item.external_post_id = post_result.get("id")
        item.external_post_url = post_result.get("url")
        item.published_at = timezone.now()
        item.save()

        AuditLog.objects.create(
            workspace=job.workspace,
            platform='X',
            action="Published Post",
            result="Success",
        )

    except Exception as e:
        item.status = PublishingJobItem.Status.FAILED
        item.error_message = str(e)[:500]
        item.failed_at = timezone.now()
        item.save()

        AuditLog.objects.create(
            workspace=job.workspace,
            platform='X',
            action="Published Post",
            result="Failed",
            error=str(e)[:500],
        )


def _publish_to_linkedin(item: PublishingJobItem, job: PublishingJob):
    """Publish to LinkedIn."""
    adapter = LinkedInAdapter()

    try:
        # Decrypt access token
        access_token = decrypt_token(item.social_connection.access_token_encrypted)
        if not access_token:
            raise LinkedInAuthenticationError("Access token missing — please reconnect LinkedIn.")

        # Build the author URN from the external_account_id
        external_id = item.social_connection.external_account_id
        account_type = item.social_connection.account_type or 'member'

        if account_type == 'organization':
            author_urn = f"urn:li:organization:{external_id}"
        else:
            author_urn = f"urn:li:person:{external_id}"

        # Build the caption
        caption = job.caption or "New post from Scaleezy Marketing Hub"

        # Determine if this is an image or text post
        media_url = job.asset.file_url if job.asset else None

        if media_url and not media_url.startswith("https://mock-storage.url"):
            # Image post — download the image, then publish
            logger.info(f"LinkedIn image publishing started for job {job.id}")

            try:
                img_response = requests.get(media_url, timeout=60)
                if not img_response.ok:
                    raise LinkedInMediaUploadError(
                        f"Failed to download media from storage (HTTP {img_response.status_code})"
                    )
                image_data = img_response.content
            except requests.RequestException as e:
                raise LinkedInMediaUploadError(f"Failed to download media: {e}")

            post_result = adapter.publish_image(
                access_token=access_token,
                author_urn=author_urn,
                text=caption,
                image_data=image_data,
                filename=job.asset.file_name or "poster.jpg",
            )
        else:
            # Text-only post
            logger.info(f"LinkedIn text publishing started for job {job.id}")
            post_result = adapter.publish_text(
                access_token=access_token,
                author_urn=author_urn,
                text=caption,
            )

        # Success
        item.status = PublishingJobItem.Status.PUBLISHED
        item.external_post_id = post_result.get("id", "")
        item.external_post_url = post_result.get("url", "")
        item.published_at = timezone.now()
        item.save()

        # Update last_published_at on the connection
        item.social_connection.last_published_at = timezone.now()
        item.social_connection.save(update_fields=['last_published_at'])

        logger.info(f"LinkedIn publishing succeeded for job {job.id} — post_id={post_result.get('id')}")

        AuditLog.objects.create(
            workspace=job.workspace,
            platform='LINKEDIN',
            action="Published Post",
            result="Success",
        )

    except LinkedInAuthenticationError as e:
        _fail_linkedin_item(item, job, e, "LINKEDIN_AUTH_FAILED")
        # Mark connection as needing reauthorization
        item.social_connection.status = 'TOKEN_EXPIRED'
        item.social_connection.reauthorization_required = True
        item.social_connection.last_error = e.safe_message
        item.social_connection.save(update_fields=['status', 'reauthorization_required', 'last_error'])

    except LinkedInPermissionError as e:
        _fail_linkedin_item(item, job, e, "LINKEDIN_PERMISSION_DENIED")

    except LinkedInRateLimitError as e:
        _fail_linkedin_item(item, job, e, "LINKEDIN_RATE_LIMITED")

    except LinkedInMediaUploadError as e:
        _fail_linkedin_item(item, job, e, "LINKEDIN_MEDIA_UPLOAD_FAILED")

    except LinkedInPublishingError as e:
        _fail_linkedin_item(item, job, e, "LINKEDIN_PUBLISH_FAILED")

    except LinkedInAPIError as e:
        _fail_linkedin_item(item, job, e, e.error_code)

    except Exception as e:
        logger.exception(f"Unexpected error publishing to LinkedIn for job {job.id}")
        item.status = PublishingJobItem.Status.FAILED
        item.error_code = "UNEXPECTED_ERROR"
        item.error_message = "An unexpected error occurred while publishing to LinkedIn."
        item.failed_at = timezone.now()
        item.save()

        AuditLog.objects.create(
            workspace=job.workspace,
            platform='LINKEDIN',
            action="Published Post",
            result="Failed",
            error="Unexpected error",
        )


def _fail_linkedin_item(item: PublishingJobItem, job: PublishingJob, error, error_code: str):
    """Mark a LinkedIn publishing item as failed with a safe error message."""
    safe_msg = getattr(error, 'safe_message', str(error))
    logger.warning(f"LinkedIn publishing failed for job {job.id}: {error}")

    item.status = PublishingJobItem.Status.FAILED
    item.error_code = error_code
    item.error_message = safe_msg
    item.failed_at = timezone.now()
    item.save()

    AuditLog.objects.create(
        workspace=job.workspace,
        platform='LINKEDIN',
        action="Published Post",
        result="Failed",
        error=safe_msg,
    )


def _publish_to_facebook(item: PublishingJobItem, job: PublishingJob):
    """Publish to Facebook Page."""
    adapter = FacebookAdapter()

    try:
        access_token = decrypt_token(item.social_connection.access_token_encrypted)
        if not access_token:
            raise MetaAuthenticationError("Access token missing — please reconnect Facebook.")

        author_urn = item.social_connection.external_account_id
        caption = job.caption or "New post from Scaleezy Marketing Hub"
        media_url = job.asset.file_url if job.asset else None

        if media_url and not media_url.startswith("https://mock-storage.url"):
            logger.info(f"Facebook image publishing started for job {job.id}")
            # Facebook supports uploading via image_url directly
            post_result = adapter.publish_image(
                access_token=access_token,
                author_urn=author_urn,
                text=caption,
                image_url=media_url
            )
        else:
            logger.info(f"Facebook text publishing started for job {job.id}")
            post_result = adapter.publish_text(
                access_token=access_token,
                author_urn=author_urn,
                text=caption
            )

        item.status = PublishingJobItem.Status.PUBLISHED
        item.external_post_id = post_result.get("id", "")
        item.external_post_url = f"https://facebook.com/{post_result.get('id')}"
        item.published_at = timezone.now()
        item.save()

        item.social_connection.last_published_at = timezone.now()
        item.social_connection.save(update_fields=['last_published_at'])

        AuditLog.objects.create(
            workspace=job.workspace,
            platform='FACEBOOK',
            action="Published Post",
            result="Success",
        )

    except MetaAuthenticationError as e:
        _fail_meta_item(item, job, e, "META_AUTH_FAILED")
        item.social_connection.status = 'TOKEN_EXPIRED'
        item.social_connection.reauthorization_required = True
        item.social_connection.last_error = e.safe_message
        item.social_connection.save(update_fields=['status', 'reauthorization_required', 'last_error'])
    except MetaPermissionError as e:
        _fail_meta_item(item, job, e, "META_PERMISSION_DENIED")
    except MetaRateLimitError as e:
        _fail_meta_item(item, job, e, "META_RATE_LIMITED")
    except MetaPublishingError as e:
        _fail_meta_item(item, job, e, "META_PUBLISHING_FAILED")
    except Exception as e:
        logger.exception(f"Unexpected error publishing to Facebook for job {job.id}")
        _fail_meta_item(item, job, Exception("Unexpected error occurred while publishing to Facebook."), "UNEXPECTED_ERROR")


def _publish_to_instagram(item: PublishingJobItem, job: PublishingJob):
    """Publish to Instagram Professional Account."""
    adapter = InstagramAdapter()

    try:
        access_token = decrypt_token(item.social_connection.access_token_encrypted)
        if not access_token:
            raise MetaAuthenticationError("Access token missing — please reconnect Instagram.")

        author_urn = item.social_connection.external_account_id
        caption = job.caption or "New post from Scaleezy Marketing Hub"
        media_url = job.asset.file_url if job.asset else None

        if not media_url or media_url.startswith("https://mock-storage.url"):
            # IG requires an image/video
            raise MetaPublishingError("Instagram requires an image or video to publish. Text-only posts are not supported.")

        logger.info(f"Instagram image publishing started for job {job.id}")
        post_result = adapter.publish_image(
            access_token=access_token,
            author_urn=author_urn,
            text=caption,
            image_url=media_url
        )

        item.status = PublishingJobItem.Status.PUBLISHED
        item.external_post_id = post_result.get("id", "")
        # IG post URLs are typically not directly predictable via ID alone without fetching the permalink
        item.external_post_url = ""
        item.published_at = timezone.now()
        item.save()

        item.social_connection.last_published_at = timezone.now()
        item.social_connection.save(update_fields=['last_published_at'])

        AuditLog.objects.create(
            workspace=job.workspace,
            platform='INSTAGRAM',
            action="Published Post",
            result="Success",
        )

    except MetaAuthenticationError as e:
        _fail_meta_item(item, job, e, "META_AUTH_FAILED")
        item.social_connection.status = 'TOKEN_EXPIRED'
        item.social_connection.reauthorization_required = True
        item.social_connection.last_error = e.safe_message
        item.social_connection.save(update_fields=['status', 'reauthorization_required', 'last_error'])
    except MetaPermissionError as e:
        _fail_meta_item(item, job, e, "META_PERMISSION_DENIED")
    except MetaRateLimitError as e:
        _fail_meta_item(item, job, e, "META_RATE_LIMITED")
    except MetaMediaUploadError as e:
        _fail_meta_item(item, job, e, "META_MEDIA_UPLOAD_FAILED")
    except MetaPublishingError as e:
        _fail_meta_item(item, job, e, "META_PUBLISHING_FAILED")
    except Exception as e:
        logger.exception(f"Unexpected error publishing to Instagram for job {job.id}")
        _fail_meta_item(item, job, Exception("Unexpected error occurred while publishing to Instagram."), "UNEXPECTED_ERROR")


def _fail_meta_item(item: PublishingJobItem, job: PublishingJob, error, error_code: str):
    """Mark a Meta publishing item as failed with a safe error message."""
    safe_msg = getattr(error, 'safe_message', str(error))
    logger.warning(f"Meta publishing failed for job {job.id}: {error}")

    item.status = PublishingJobItem.Status.FAILED
    item.error_code = error_code
    item.error_message = safe_msg
    item.failed_at = timezone.now()
    item.save()

    AuditLog.objects.create(
        workspace=job.workspace,
        platform=item.social_connection.platform,
        action="Published Post",
        result="Failed",
        error=safe_msg,
    )


def _publish_to_youtube(item: PublishingJobItem, job: PublishingJob):
    """Publish video to YouTube Channel."""
    adapter = YouTubeAdapter()

    try:
        connection = item.social_connection
        
        # Check if token is expired or expires in the next 5 minutes
        from datetime import timedelta
        if connection.token_expires_at and timezone.now() >= (connection.token_expires_at - timedelta(minutes=5)):
            refresh_token = decrypt_token(connection.refresh_token_encrypted)
            if refresh_token:
                logger.info(f"Refreshing YouTube token for connection {connection.id}")
                new_token_data = adapter.refresh_token(refresh_token)
                
                connection.access_token_encrypted = encrypt_token(new_token_data["access_token"])
                if new_token_data.get("refresh_token"):
                    connection.refresh_token_encrypted = encrypt_token(new_token_data["refresh_token"])
                
                expires_in = new_token_data.get("expires_in", 3599)
                connection.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
                connection.last_token_refresh_at = timezone.now()
                connection.save()
        
        access_token = decrypt_token(connection.access_token_encrypted)
        if not access_token:
            raise YouTubeAuthenticationError("Access token missing — please reconnect YouTube.")

        raw_title = job.caption or "New video from Scaleezy Marketing Hub"
        
        # YouTube titles must be <= 100 chars and cannot contain < or >
        title_cleaned = raw_title.split('\n')[0].replace('<', '').replace('>', '').strip()
        if not title_cleaned:
            title_cleaned = "New video from Scaleezy"
        if len(title_cleaned) > 95:
            title_cleaned = title_cleaned[:95] + "..."
            
        title = title_cleaned
        description = job.caption or ""
        media_url = job.asset.file_url if job.asset else None

        if not media_url:
            raise YouTubePublishingError("YouTube requires a video to publish. Text-only posts are not supported.")
            
        # We need to stream the video data to YouTube API
        # Let's use requests to fetch it and stream
        import requests as req
        video_response = req.get(media_url, stream=True, timeout=10)
        
        if not video_response.ok:
            raise YouTubeMediaUploadError("Failed to fetch video asset for uploading.")
            
        content_length = video_response.headers.get('content-length')
            
        logger.info(f"YouTube video publishing started for job {job.id}")
        
        # publish_video takes a stream (video_response.raw)
        # Note: requests.get with stream=True exposes .raw
        post_result = adapter.publish_video(
            access_token=access_token,
            title=title,
            description=description,
            video_stream=video_response.raw,
            content_length=int(content_length) if content_length else None
        )

        item.status = PublishingJobItem.Status.PUBLISHED
        item.external_post_id = post_result.get("id", "")
        item.external_post_url = f"https://www.youtube.com/watch?v={post_result.get('id')}"
        item.published_at = timezone.now()
        item.save()

        item.social_connection.last_published_at = timezone.now()
        item.social_connection.save(update_fields=['last_published_at'])

        AuditLog.objects.create(
            workspace=job.workspace,
            platform='YOUTUBE',
            action="Published Video",
            result="Success",
        )

    except YouTubeAuthenticationError as e:
        _fail_youtube_item(item, job, e, "YOUTUBE_AUTH_FAILED")
        item.social_connection.status = 'TOKEN_EXPIRED'
        item.social_connection.reauthorization_required = True
        item.social_connection.last_error = e.safe_message
        item.social_connection.save(update_fields=['status', 'reauthorization_required', 'last_error'])
    except YouTubePermissionError as e:
        _fail_youtube_item(item, job, e, "YOUTUBE_PERMISSION_DENIED")
    except YouTubeRateLimitError as e:
        _fail_youtube_item(item, job, e, "YOUTUBE_QUOTA_EXCEEDED")
    except YouTubeMediaUploadError as e:
        _fail_youtube_item(item, job, e, "YOUTUBE_MEDIA_UPLOAD_FAILED")
    except YouTubePublishingError as e:
        _fail_youtube_item(item, job, e, "YOUTUBE_PUBLISHING_FAILED")
    except Exception as e:
        logger.exception(f"Unexpected error publishing to YouTube for job {job.id}")
        _fail_youtube_item(item, job, Exception("Unexpected error occurred while publishing to YouTube."), "UNEXPECTED_ERROR")


def _fail_youtube_item(item: PublishingJobItem, job: PublishingJob, error, error_code: str):
    """Mark a YouTube publishing item as failed with a safe error message."""
    safe_msg = getattr(error, 'safe_message', str(error))
    logger.warning(f"YouTube publishing failed for job {job.id}: {error}")

    item.status = PublishingJobItem.Status.FAILED
    item.error_code = error_code
    item.error_message = safe_msg
    item.failed_at = timezone.now()
    item.save()

    AuditLog.objects.create(
        workspace=job.workspace,
        platform=item.social_connection.platform,
        action="Published Video",
        result="Failed",
        error=safe_msg,
    )
