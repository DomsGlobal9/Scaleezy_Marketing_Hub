import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class EngagementItem(models.Model):
    class Kind(models.TextChoices):
        COMMENT = 'COMMENT', 'Comment'
        MENTION = 'MENTION', 'Mention'
        MESSAGE = 'MESSAGE', 'Direct message'

    class Status(models.TextChoices):
        NEW = 'NEW', 'New'
        IN_PROGRESS = 'IN_PROGRESS', 'In progress'
        AWAITING_APPROVAL = 'AWAITING_APPROVAL', 'Awaiting approval'
        APPROVED = 'APPROVED', 'Approved to send'
        SENDING = 'SENDING', 'Sending'
        RESOLVED = 'RESOLVED', 'Resolved'
        IGNORED = 'IGNORED', 'Ignored'

    class Sentiment(models.TextChoices):
        UNKNOWN = 'UNKNOWN', 'Unknown'
        POSITIVE = 'POSITIVE', 'Positive'
        NEUTRAL = 'NEUTRAL', 'Neutral'
        NEGATIVE = 'NEGATIVE', 'Negative'

    class Urgency(models.TextChoices):
        LOW = 'LOW', 'Low'
        NORMAL = 'NORMAL', 'Normal'
        HIGH = 'HIGH', 'High'
        CRITICAL = 'CRITICAL', 'Critical'

    class DraftStatus(models.TextChoices):
        NOT_REQUESTED = 'NOT_REQUESTED', 'Not requested'
        QUEUED = 'QUEUED', 'Queued'
        PROCESSING = 'PROCESSING', 'Processing'
        READY = 'READY', 'Ready for review'
        FAILED = 'FAILED', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'workspaces.MarketingWorkspace', on_delete=models.CASCADE,
        related_name='engagement_items',
    )
    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.CASCADE, related_name='engagement_items'
    )
    social_connection = models.ForeignKey(
        'social_accounts.SocialConnection', on_delete=models.CASCADE,
        related_name='engagement_items',
    )
    platform = models.CharField(max_length=50)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    external_id = models.CharField(max_length=255)
    thread_id = models.CharField(max_length=255, blank=True)
    author_name = models.CharField(max_length=255, blank=True)
    author_handle = models.CharField(max_length=255, blank=True)
    body = models.TextField()
    source_url = models.URLField(max_length=1000, blank=True)
    occurred_at = models.DateTimeField()
    source_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.NEW
    )
    sentiment = models.CharField(
        max_length=16, choices=Sentiment.choices, default=Sentiment.UNKNOWN
    )
    urgency = models.CharField(
        max_length=16, choices=Urgency.choices, default=Urgency.NORMAL
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_engagement_items',
    )
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='locked_engagement_items',
    )
    lock_expires_at = models.DateTimeField(null=True, blank=True)
    ai_draft = models.TextField(blank=True)
    draft_status = models.CharField(
        max_length=20, choices=DraftStatus.choices, default=DraftStatus.NOT_REQUESTED
    )
    draft_task_id = models.CharField(max_length=64, blank=True)
    ai_provider_key = models.CharField(max_length=100, blank=True)
    ai_provider_name = models.CharField(max_length=100, blank=True)
    ai_risk_flags = models.JSONField(default=list, blank=True)
    approved_response = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_engagement_items',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    external_response_id = models.CharField(max_length=255, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-occurred_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['social_connection', 'external_id'],
                name='uniq_engagement_external_item',
            )
        ]
        indexes = [
            models.Index(fields=['workspace', 'status', '-occurred_at']),
            models.Index(fields=['workspace', 'assigned_to', 'status']),
            models.Index(fields=['workspace', 'platform', '-occurred_at']),
        ]

    def save(self, *args, **kwargs):
        if self.brand_id and self.brand.workspace_id != self.workspace_id:
            raise ValidationError('EngagementItem.brand must belong to its workspace.')
        if self.social_connection_id and self.social_connection.workspace_id != self.workspace_id:
            raise ValidationError('EngagementItem connection must belong to its workspace.')
        if self.social_connection_id and self.platform != self.social_connection.platform:
            raise ValidationError('EngagementItem platform must match its connection.')
        return super().save(*args, **kwargs)


class EngagementSyncRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'QUEUED', 'Queued'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'workspaces.MarketingWorkspace', on_delete=models.CASCADE,
        related_name='engagement_sync_runs',
    )
    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.CASCADE, related_name='engagement_sync_runs'
    )
    social_connection = models.ForeignKey(
        'social_accounts.SocialConnection', on_delete=models.CASCADE,
        related_name='engagement_sync_runs',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    task_id = models.CharField(max_length=64, blank=True)
    cursor = models.CharField(max_length=500, blank=True)
    imported_count = models.PositiveIntegerField(default=0)
    seen_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='engagement_sync_runs',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['workspace', 'status', '-created_at'])]

    def save(self, *args, **kwargs):
        if self.brand_id and self.brand.workspace_id != self.workspace_id:
            raise ValidationError('EngagementSyncRun.brand must belong to its workspace.')
        if self.social_connection_id and self.social_connection.workspace_id != self.workspace_id:
            raise ValidationError('EngagementSyncRun connection must belong to its workspace.')
        return super().save(*args, **kwargs)


class SavedReply(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'workspaces.MarketingWorkspace', on_delete=models.CASCADE,
        related_name='saved_replies',
    )
    name = models.CharField(max_length=120)
    body = models.TextField(max_length=2000)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='saved_replies_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'name'], name='uniq_saved_reply_name')
        ]
