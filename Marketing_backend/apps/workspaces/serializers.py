from rest_framework import serializers
from .models import MarketingWorkspace
from apps.audit.models import AuditLog

class MarketingWorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketingWorkspace
        fields = ['id', 'workspace_name', 'timezone', 'default_language']

class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'
