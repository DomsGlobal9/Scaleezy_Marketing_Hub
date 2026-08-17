"""
Publishing service — executes publishing jobs synchronously.

Supports X (Twitter) and LinkedIn platforms.
Each platform item is processed independently so one failure
does not block the others.
"""

import logging

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
from apps.social_accounts.utils.encryption import decrypt_token
from apps.audit.models import AuditLog

logger = logging.getLogger(__name__)


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
            _publish_to_x(item, job)
        elif platform == 'LINKEDIN':
            _publish_to_linkedin(item, job)
        else:
            item.status = PublishingJobItem.Status.FAILED
            item.error_message = "Platform not supported yet"
            item.failed_at = timezone.now()
            item.save()
            all_success = False
            continue

        # Check item result
        if item.status == PublishingJobItem.Status.PUBLISHED:
            any_success = True
        else:
            all_success = False

    job.completed_at = timezone.now()
    if all_success and any_success:
        job.status = PublishingJob.Status.PUBLISHED
    elif any_success:
        job.status = PublishingJob.Status.PARTIALLY_PUBLISHED
    else:
        job.status = PublishingJob.Status.FAILED
    job.save()


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
