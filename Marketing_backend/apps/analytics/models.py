import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.workspaces.models import MarketingWorkspace

class DailyMetric(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(MarketingWorkspace, on_delete=models.CASCADE, related_name='daily_metrics')
    date = models.DateField()
    reach = models.IntegerField(default=0)
    engagement = models.IntegerField(default=0)
    posts_published = models.IntegerField(default=0)
    conversions = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'analytics_daily_metrics'
        unique_together = ('workspace', 'date')

class PlatformPerformance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(MarketingWorkspace, on_delete=models.CASCADE, related_name='platform_performance')
    platform = models.CharField(max_length=50) # 'Instagram', 'Facebook', etc.
    reach = models.IntegerField(default=0)
    engagement = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    conversions = models.IntegerField(default=0)
    roi_multiplier = models.FloatField(default=0.0) # e.g. 4.2
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'analytics_platform_performance'
        unique_together = ('workspace', 'platform')

class CampaignROI(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(MarketingWorkspace, on_delete=models.CASCADE, related_name='campaign_rois')
    campaign_name = models.CharField(max_length=255)
    roi_multiplier = models.FloatField(default=0.0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'analytics_campaign_roi'
        unique_together = ('workspace', 'campaign_name')


class PerformanceObservation(models.Model):
    """One immutable measurement from a named source.

    The older analytics tables are projections. This row is the evidence that
    makes their numbers explainable, replay-safe and safe to rebuild.
    """

    class Source(models.TextChoices):
        X_API = 'X_API', 'X API'
        YOUTUBE_API = 'YOUTUBE_API', 'YouTube API'
        AUDITABLE_IMPORT = 'AUDITABLE_IMPORT', 'Auditable import'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.CASCADE,
        related_name='performance_observations',
    )
    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='performance_observations',
    )
    content_item = models.ForeignKey(
        'content.ContentItem', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='performance_observations',
    )
    publishing_job_item = models.ForeignKey(
        'publishing.PublishingJobItem', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='performance_observations',
    )
    social_connection = models.ForeignKey(
        'social_accounts.SocialConnection', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='performance_observations',
    )
    source = models.CharField(max_length=32, choices=Source.choices)
    source_record_id = models.CharField(max_length=255)
    platform = models.CharField(max_length=50)
    external_post_id = models.CharField(max_length=255, blank=True)
    campaign_name = models.CharField(max_length=255, blank=True)
    impressions = models.PositiveBigIntegerField(default=0)
    reach = models.PositiveBigIntegerField(default=0)
    engagement = models.PositiveBigIntegerField(default=0)
    clicks = models.PositiveBigIntegerField(default=0)
    conversions = models.PositiveBigIntegerField(default=0)
    spend = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    revenue = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    currency = models.CharField(max_length=3, default='USD')
    observed_at = models.DateTimeField()
    source_payload = models.JSONField(default=dict, blank=True)
    ingested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='performance_observations_ingested',
    )
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-observed_at', '-ingested_at']
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'source', 'source_record_id'],
                name='uniq_performance_source_record',
            ),
            models.CheckConstraint(
                condition=models.Q(spend__gte=0, revenue__gte=0),
                name='performance_money_non_negative',
            ),
        ]
        indexes = [
            models.Index(fields=['workspace', '-observed_at']),
            models.Index(fields=['workspace', 'platform', '-observed_at']),
            models.Index(fields=['workspace', 'content_item']),
        ]

    def save(self, *args, **kwargs):
        if self.brand_id and self.brand.workspace_id != self.workspace_id:
            raise ValidationError('Performance brand must belong to its workspace.')
        if self.content_item_id and self.content_item.workspace_id != self.workspace_id:
            raise ValidationError('Performance content must belong to its workspace.')
        if self.social_connection_id and self.social_connection.workspace_id != self.workspace_id:
            raise ValidationError('Performance connection must belong to its workspace.')
        if self.publishing_job_item_id:
            job = self.publishing_job_item.publishing_job
            if job.workspace_id != self.workspace_id:
                raise ValidationError('Performance publish item must belong to its workspace.')
        self.currency = (self.currency or 'USD').upper()
        return super().save(*args, **kwargs)


class PerformanceSyncRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'QUEUED', 'Queued'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.CASCADE, related_name='performance_sync_runs'
    )
    social_connection = models.ForeignKey(
        'social_accounts.SocialConnection', on_delete=models.CASCADE,
        related_name='performance_sync_runs',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    task_id = models.CharField(max_length=64, blank=True)
    observed_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='performance_sync_runs',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['workspace', 'status', '-created_at'])]

    def save(self, *args, **kwargs):
        if self.social_connection_id and self.social_connection.workspace_id != self.workspace_id:
            raise ValidationError('Performance sync connection must belong to its workspace.')
        return super().save(*args, **kwargs)


class GrowthLead(models.Model):
    class Status(models.TextChoices):
        NEW = 'NEW', 'New'
        QUALIFIED = 'QUALIFIED', 'Qualified'
        CONVERTED = 'CONVERTED', 'Converted'
        DISQUALIFIED = 'DISQUALIFIED', 'Disqualified'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.CASCADE, related_name='growth_leads'
    )
    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='growth_leads',
    )
    engagement_item = models.OneToOneField(
        'engagement.EngagementItem', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='growth_lead',
    )
    name = models.CharField(max_length=255, blank=True)
    handle = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    source = models.CharField(max_length=80, default='ENGAGEMENT')
    external_reference = models.CharField(max_length=255, blank=True)
    estimated_value = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    currency = models.CharField(max_length=3, default='USD')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='growth_leads_created',
    )
    converted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['workspace', 'status', '-created_at'])]

    def save(self, *args, **kwargs):
        if self.brand_id and self.brand.workspace_id != self.workspace_id:
            raise ValidationError('Lead brand must belong to its workspace.')
        if self.engagement_item_id and self.engagement_item.workspace_id != self.workspace_id:
            raise ValidationError('Lead engagement must belong to its workspace.')
        self.currency = (self.currency or 'USD').upper()
        return super().save(*args, **kwargs)


class RevenueEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.CASCADE, related_name='revenue_events'
    )
    lead = models.ForeignKey(
        GrowthLead, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='revenue_events',
    )
    content_item = models.ForeignKey(
        'content.ContentItem', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='revenue_events',
    )
    source = models.CharField(max_length=80)
    external_event_id = models.CharField(max_length=255)
    campaign_name = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(
        max_digits=14, decimal_places=4,
        validators=[MinValueValidator(Decimal('0'))],
    )
    currency = models.CharField(max_length=3, default='USD')
    occurred_at = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='revenue_events_recorded',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-occurred_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'source', 'external_event_id'],
                name='uniq_revenue_source_event',
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name='revenue_amount_non_negative'
            ),
        ]
        indexes = [models.Index(fields=['workspace', '-occurred_at'])]

    def save(self, *args, **kwargs):
        if self.lead_id and self.lead.workspace_id != self.workspace_id:
            raise ValidationError('Revenue lead must belong to its workspace.')
        if self.content_item_id and self.content_item.workspace_id != self.workspace_id:
            raise ValidationError('Revenue content must belong to its workspace.')
        self.currency = (self.currency or 'USD').upper()
        return super().save(*args, **kwargs)
