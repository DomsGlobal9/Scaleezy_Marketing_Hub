from rest_framework import serializers

from .models import AIProvider, AIUsageLog, WorkspaceAIProvider, WorkspaceAIRoute


class AIProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIProvider
        fields = ['id', 'key', 'display_name', 'capabilities', 'default_model',
                  'is_available', 'unit_cost', 'docs_url']
        read_only_fields = fields


class WorkspaceAIProviderSerializer(serializers.ModelSerializer):
    provider_key = serializers.CharField(source='provider.key', read_only=True)
    provider_name = serializers.CharField(source='provider.display_name', read_only=True)
    capabilities = serializers.JSONField(source='provider.capabilities', read_only=True)
    has_credentials = serializers.BooleanField(read_only=True)
    # Write-only: the plaintext key is accepted once, encrypted, and never
    # returned. Same treatment as the OAuth tokens.
    credentials = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = WorkspaceAIProvider
        fields = [
            'id', 'provider', 'provider_key', 'provider_name', 'capabilities',
            'enabled', 'credentials', 'has_credentials', 'model_override',
            'max_cost_per_generation', 'config',
            'last_health_check_at', 'last_health_ok', 'last_error',
        ]
        read_only_fields = ['id', 'last_health_check_at', 'last_health_ok', 'last_error']

    def _apply_credentials(self, validated):
        from apps.social_accounts.utils.encryption import encrypt_token

        raw = validated.pop('credentials', None)
        if raw is not None:
            validated['credentials_encrypted'] = encrypt_token(raw) if raw else ''
        return validated

    def create(self, validated_data):
        return super().create(self._apply_credentials(validated_data))

    def update(self, instance, validated_data):
        return super().update(instance, self._apply_credentials(validated_data))


class WorkspaceAIRouteSerializer(serializers.ModelSerializer):
    provider_key = serializers.CharField(source='provider.key', read_only=True)
    provider_name = serializers.CharField(source='provider.display_name', read_only=True)

    class Meta:
        model = WorkspaceAIRoute
        fields = ['id', 'capability', 'provider', 'provider_key', 'provider_name',
                  'priority', 'enabled', 'strategy']
        read_only_fields = ['id']

    def validate(self, attrs):
        provider = attrs.get('provider') or getattr(self.instance, 'provider', None)
        capability = attrs.get('capability') or getattr(self.instance, 'capability', None)
        if provider and capability and not provider.supports(capability):
            raise serializers.ValidationError(
                {'provider': f"{provider.display_name} cannot serve {capability}."}
            )
        return attrs


class AIUsageLogSerializer(serializers.ModelSerializer):
    provider_key = serializers.CharField(source='provider.key', read_only=True)

    class Meta:
        model = AIUsageLog
        fields = ['id', 'provider_key', 'capability', 'cost', 'latency_ms',
                  'success', 'error', 'strategy', 'selected', 'created_at']
        read_only_fields = fields
