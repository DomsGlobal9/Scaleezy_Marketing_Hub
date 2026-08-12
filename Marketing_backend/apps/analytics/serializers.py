from rest_framework import serializers
from .models import DailyMetric, PlatformPerformance, CampaignROI

class DailyMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyMetric
        fields = ['id', 'date', 'reach', 'engagement', 'posts_published', 'conversions']

class PlatformPerformanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformPerformance
        fields = ['id', 'platform', 'reach', 'engagement', 'clicks', 'conversions', 'roi_multiplier']

class CampaignROISerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignROI
        fields = ['id', 'campaign_name', 'roi_multiplier']
