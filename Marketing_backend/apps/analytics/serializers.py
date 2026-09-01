from rest_framework import serializers
from .models import (
    CampaignROI,
    DailyMetric,
    GrowthLead,
    PerformanceObservation,
    PerformanceSyncRun,
    PlatformPerformance,
    RevenueEvent,
)

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


class PerformanceObservationSerializer(serializers.ModelSerializer):
    content_headline = serializers.CharField(source='content_item.headline', read_only=True)
    ai_provider = serializers.CharField(source='content_item.ai_provider', read_only=True)
    layout_plugin = serializers.CharField(source='content_item.layout_plugin', read_only=True)

    class Meta:
        model = PerformanceObservation
        fields = [
            'id', 'source', 'source_record_id', 'platform', 'external_post_id',
            'campaign_name', 'impressions', 'reach', 'engagement', 'clicks',
            'conversions', 'spend', 'revenue', 'currency', 'observed_at',
            'ingested_at', 'content_item', 'content_headline', 'ai_provider',
            'layout_plugin', 'source_payload',
        ]


class PerformanceSyncRunSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source='social_connection.account_name', read_only=True)
    platform = serializers.CharField(source='social_connection.platform', read_only=True)

    class Meta:
        model = PerformanceSyncRun
        fields = [
            'id', 'social_connection', 'account_name', 'platform', 'status',
            'task_id', 'observed_count', 'error', 'started_at', 'completed_at',
            'created_at',
        ]
        read_only_fields = [
            'status', 'task_id', 'observed_count', 'error', 'started_at',
            'completed_at', 'created_at',
        ]


class GrowthLeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrowthLead
        fields = [
            'id', 'brand', 'engagement_item', 'name', 'handle', 'email', 'status',
            'source', 'external_reference', 'estimated_value', 'currency', 'notes',
            'converted_at', 'created_at', 'updated_at',
        ]
        read_only_fields = ['converted_at', 'created_at', 'updated_at']


class RevenueEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = RevenueEvent
        fields = [
            'id', 'lead', 'content_item', 'source', 'external_event_id',
            'campaign_name', 'amount', 'currency', 'occurred_at', 'metadata',
            'created_at',
        ]
        read_only_fields = ['created_at']
