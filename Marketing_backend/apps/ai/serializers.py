from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .endpoint_security import validate_public_https_endpoint

from .models import (
    AIProvider,
    AIUsageLog,
    Capability,
    ProviderIntegrationType,
    Strategy,
    WorkspaceAIProvider,
    WorkspaceAIRoute,
)


class AIProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIProvider
        fields = ['id', 'key', 'display_name', 'capabilities', 'default_model',
                  'is_available', 'unit_cost', 'docs_url', 'integration_type',
                  'base_url']
        read_only_fields = fields


class CustomWorkspaceAIProviderSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=100, trim_whitespace=True)
    base_url = serializers.URLField(max_length=500)
    credentials = serializers.CharField(
        write_only=True,
        trim_whitespace=True,
        required=False,
        allow_blank=True,
        default='',
    )
    model = serializers.CharField(max_length=100, trim_whitespace=True)
    integration_type = serializers.ChoiceField(choices=(
        ProviderIntegrationType.OPENAI_COMPATIBLE,
        ProviderIntegrationType.SCALEEZY_JSON,
    ))
    capabilities = serializers.ListField(
        child=serializers.ChoiceField(choices=Capability.choices),
        min_length=1,
        allow_empty=False,
    )
    enabled = serializers.BooleanField(default=True)

    def validate_display_name(self, value):
        if len(value.strip()) < 2:
            raise serializers.ValidationError('Enter a provider name.')
        return value.strip()

    def validate_base_url(self, value):
        try:
            return validate_public_https_endpoint(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0]) from exc

    def validate_credentials(self, value):
        return value.strip()

    def validate_model(self, value):
        if not value.strip():
            raise serializers.ValidationError('Enter the exact model identifier.')
        return value.strip()

    def validate(self, attrs):
        capabilities = list(dict.fromkeys(attrs['capabilities']))
        if attrs['integration_type'] == ProviderIntegrationType.OPENAI_COMPATIBLE:
            supported = {
                Capability.TEXT,
                Capability.IMAGE,
                Capability.IMAGE_ANALYSIS,
                Capability.IMAGE_CAPTION,
                Capability.EMBEDDING,
            }
            if any(value not in supported for value in capabilities):
                raise serializers.ValidationError({
                    'capabilities': (
                        'OpenAI-compatible APIs do not define a standard video contract. '
                        'Use the Scaleezy universal JSON protocol for video capabilities.'
                    )
                })
        attrs['capabilities'] = capabilities
        return attrs


class WorkspaceAIProviderSerializer(serializers.ModelSerializer):
    provider_key = serializers.CharField(source='provider.key', read_only=True)
    provider_name = serializers.CharField(source='provider.display_name', read_only=True)
    capabilities = serializers.ListField(
        child=serializers.ChoiceField(choices=Capability.choices),
        required=False,
        allow_empty=True,
        allow_null=True,
    )
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

    def validate_provider(self, provider):
        if self.instance is not None and provider.pk != self.instance.provider_id:
            raise serializers.ValidationError(
                "A configured provider cannot be changed. Add a separate provider instead."
            )
        return provider

    @staticmethod
    def _supported_capabilities(provider):
        from .registry import adapter_class_for_provider

        adapter = adapter_class_for_provider(provider)
        if adapter is None:
            return set()
        adapter_capabilities = {
            str(value) for value in (getattr(adapter, 'capabilities', ()) or ())
        }
        if provider.is_custom:
            return adapter_capabilities
        return adapter_capabilities.intersection(provider.capabilities or [])

    def validate(self, attrs):
        provider = attrs.get('provider') or getattr(self.instance, 'provider', None)
        if provider and 'capabilities' in attrs:
            capabilities = list(dict.fromkeys(attrs['capabilities'] or []))
            unsupported = set(capabilities) - self._supported_capabilities(provider)
            if unsupported:
                raise serializers.ValidationError({
                    'capabilities': (
                        f"{provider.display_name} cannot serve: "
                        f"{', '.join(sorted(unsupported))}."
                    )
                })
            attrs['capabilities'] = capabilities
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['capabilities'] = instance.assigned_capabilities
        return data

    def create(self, validated_data):
        if 'capabilities' not in validated_data:
            provider = validated_data['provider']
            supported = self._supported_capabilities(provider)
            validated_data['capabilities'] = [
                value for value in Capability.values if value in supported
            ]
        return super().create(self._apply_credentials(validated_data))

    def update(self, instance, validated_data):
        updated = super().update(instance, self._apply_credentials(validated_data))
        if 'capabilities' in validated_data and updated.provider.is_custom:
            updated.provider.capabilities = list(updated.capabilities or [])
            updated.provider.save(update_fields=['capabilities'])
        return updated


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


class WorkspaceAIRouteMemberSerializer(serializers.Serializer):
    provider = serializers.PrimaryKeyRelatedField(queryset=AIProvider.objects.all())
    priority = serializers.IntegerField(min_value=0)


class ReplaceWorkspaceAIRouteSetSerializer(serializers.Serializer):
    capability = serializers.ChoiceField(choices=Capability.choices)
    routes = WorkspaceAIRouteMemberSerializer(many=True, allow_empty=True)
    strategy = serializers.ChoiceField(
        choices=Strategy.choices,
        default=Strategy.ROUND_ROBIN,
    )

    def validate_routes(self, routes):
        provider_ids = [route['provider'].id for route in routes]
        if len(provider_ids) != len(set(provider_ids)):
            raise serializers.ValidationError("A provider can appear only once per capability.")
        priorities = [route['priority'] for route in routes]
        if len(priorities) != len(set(priorities)):
            raise serializers.ValidationError("Route priorities must be unique.")
        return routes


class AIUsageLogSerializer(serializers.ModelSerializer):
    provider_key = serializers.CharField(source='provider.key', read_only=True)

    class Meta:
        model = AIUsageLog
        fields = ['id', 'provider_key', 'capability', 'cost', 'latency_ms',
                  'success', 'error', 'strategy', 'selected', 'created_at']
        read_only_fields = fields
