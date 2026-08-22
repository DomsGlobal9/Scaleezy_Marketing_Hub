import uuid
from django.db import models
from apps.workspaces.models import MarketingWorkspace
from apps.marketing.models import MarketingAsset
from apps.social_accounts.models import SocialConnection
from apps.content.models import ContentItem
from django.contrib.auth import get_user_model

User = get_user_model()

class PublishingJob(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        QUEUED = 'QUEUED', 'Queued'
        PUBLISHING = 'PUBLISHING', 'Publishing'
        PARTIALLY_PUBLISHED = 'PARTIALLY_PUBLISHED', 'Partially Published'
        PUBLISHED = 'PUBLISHED', 'Published'
        FAILED = 'FAILED', 'Failed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PublishMode(models.TextChoices):
        NOW = 'NOW', 'Now'
        SCHEDULED = 'SCHEDULED', 'Scheduled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(MarketingWorkspace, on_delete=models.CASCADE, related_name='publishing_jobs')
    asset = models.ForeignKey(MarketingAsset, on_delete=models.CASCADE, related_name='publishing_jobs')
    # Nullable only for pre-recovery history. Every new API-created job must
    # name the approved durable content version it publishes.
    content_item = models.ForeignKey(
        ContentItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='publishing_jobs',
    )
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_publishing_jobs')

    caption = models.TextField(blank=True, default='', help_text='Post caption/text to publish')

    status = models.CharField(max_length=50, choices=Status.choices, default=Status.DRAFT)
    publish_mode = models.CharField(max_length=50, choices=PublishMode.choices, default=PublishMode.NOW)

    scheduled_at = models.DateTimeField(blank=True, null=True)
    timezone = models.CharField(max_length=50, default='UTC')

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'publishing_jobs'

    def __str__(self):
        return f"Job {self.id} - {self.status}"


class PublishingJobItem(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'QUEUED', 'Queued'
        PUBLISHING = 'PUBLISHING', 'Publishing'
        PUBLISHED = 'PUBLISHED', 'Published'
        FAILED = 'FAILED', 'Failed'
        RETRYING = 'RETRYING', 'Retrying'
        CANCELLED = 'CANCELLED', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    publishing_job = models.ForeignKey(PublishingJob, on_delete=models.CASCADE, related_name='items')
    social_connection = models.ForeignKey(SocialConnection, on_delete=models.CASCADE, related_name='publishing_job_items')

    status = models.CharField(max_length=50, choices=Status.choices, default=Status.QUEUED)

    external_post_id = models.CharField(max_length=255, blank=True, null=True)
    external_post_url = models.URLField(max_length=1000, blank=True, null=True)

    error_code = models.CharField(max_length=100, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)

    retry_count = models.IntegerField(default=0)

    queued_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(blank=True, null=True)
    failed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'publishing_job_items'
        unique_together = ('publishing_job', 'social_connection')

    def __str__(self):
        return f"Item {self.id} for {self.social_connection.platform}"
