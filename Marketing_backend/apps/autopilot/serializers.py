from rest_framework import serializers

from apps.common.permissions import get_request_workspace
from apps.social_accounts.models import SocialConnection

from .models import AutopilotPolicy, AutopilotRun, AutopilotStep


class AutopilotStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutopilotStep
        fields = ['id', 'key', 'status', 'detail', 'created_at', 'updated_at']


class AutopilotPolicySerializer(serializers.ModelSerializer):
    social_connections = serializers.PrimaryKeyRelatedField(
        queryset=SocialConnection.objects.all(), many=True, required=False
    )

    class Meta:
        model = AutopilotPolicy
        fields = [
            'id', 'brand', 'name', 'objective', 'campaign_brief', 'mode',
            'cadence', 'next_run_at', 'allowed_formats', 'social_connections',
            'daily_generation_limit', 'monthly_spend_cap', 'enabled', 'paused',
            'emergency_stop', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'cadence', 'next_run_at', 'emergency_stop', 'created_at', 'updated_at'
        ]

    def validate(self, attrs):
        request = self.context['request']
        workspace, error = get_request_workspace(request)
        if error:
            raise serializers.ValidationError('No accessible workspace selected.')
        brand = attrs.get('brand') or getattr(self.instance, 'brand', None)
        if brand is None or brand.workspace_id != workspace.id:
            raise serializers.ValidationError({'brand': 'Brand must belong to the selected client.'})
        connections = attrs.get('social_connections', [])
        if any(connection.workspace_id != workspace.id for connection in connections):
            raise serializers.ValidationError({
                'social_connections': 'Every social account must belong to the selected client.'
            })
        formats = attrs.get('allowed_formats', getattr(self.instance, 'allowed_formats', []))
        if not isinstance(formats, list):
            raise serializers.ValidationError({'allowed_formats': 'Choose a list of formats.'})
        unknown = set(map(str.upper, map(str, formats))) - {'POSTER', 'CAROUSEL', 'VIDEO'}
        if unknown:
            raise serializers.ValidationError({'allowed_formats': f'Unsupported formats: {sorted(unknown)}'})
        return attrs


class AutopilotRunSerializer(serializers.ModelSerializer):
    policy_name = serializers.CharField(source='policy.name', read_only=True)
    mode = serializers.CharField(source='policy.mode', read_only=True)
    steps = AutopilotStepSerializer(many=True, read_only=True)

    class Meta:
        model = AutopilotRun
        fields = [
            'id', 'policy', 'policy_name', 'mode', 'status', 'scheduled_for',
            'policy_snapshot', 'generation_request', 'content_item', 'task_id',
            'next_check_at', 'error_code', 'error', 'started_at', 'completed_at',
            'created_at', 'updated_at', 'steps',
        ]
