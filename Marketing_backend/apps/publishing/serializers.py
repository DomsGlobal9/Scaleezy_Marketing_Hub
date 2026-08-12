from rest_framework import serializers
from .models import PublishingJob, PublishingJobItem
from apps.social_accounts.serializers import SocialConnectionSerializer

class PublishingJobItemSerializer(serializers.ModelSerializer):
    social_connection = SocialConnectionSerializer(read_only=True)
    
    class Meta:
        model = PublishingJobItem
        fields = '__all__'
        read_only_fields = ['id', 'status', 'queued_at', 'published_at', 'failed_at']

class PublishingJobSerializer(serializers.ModelSerializer):
    items = PublishingJobItemSerializer(many=True, read_only=True)
    
    class Meta:
        model = PublishingJob
        fields = '__all__'
        read_only_fields = ['id', 'status', 'created_at', 'started_at', 'completed_at', 'created_by']

class CreatePublishingJobSerializer(serializers.Serializer):
    workspace_id = serializers.UUIDField()
    asset_id = serializers.UUIDField()
    publish_mode = serializers.ChoiceField(choices=PublishingJob.PublishMode.choices)
    scheduled_at = serializers.DateTimeField(required=False, allow_null=True)
    timezone = serializers.CharField(required=False, default="UTC")
    social_connection_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False
    )
