import uuid
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
