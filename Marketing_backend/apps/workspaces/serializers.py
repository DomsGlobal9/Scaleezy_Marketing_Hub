from rest_framework import serializers
from .models import MarketingWorkspace
from apps.audit.models import AuditLog

class MarketingWorkspaceSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(
        write_only=True, required=False, allow_blank=False, max_length=255
    )

    class Meta:
        model = MarketingWorkspace
        fields = ['id', 'workspace_name', 'timezone', 'default_language', 'brand_name']

    def create(self, validated_data):
        validated_data.pop('brand_name', None)
        return super().create(validated_data)

class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'
