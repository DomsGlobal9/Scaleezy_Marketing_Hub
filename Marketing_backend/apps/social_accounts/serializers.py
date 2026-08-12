from rest_framework import serializers
from .models import SocialConnection

class SocialConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialConnection
        fields = [
            'id', 'workspace', 'platform', 'account_type', 'external_account_id',
            'account_name', 'username', 'profile_url', 'profile_image_url',
            'status', 'publishing_enabled', 'is_default_account',
            'last_verified_at', 'last_published_at', 'last_error',
            'connected_at', 'reauthorization_required'
        ]
        read_only_fields = ['id', 'workspace', 'connected_at', 'status']

class ConnectPlatformSerializer(serializers.Serializer):
    workspace_id = serializers.UUIDField()
    platform = serializers.ChoiceField(choices=SocialConnection.Platform.choices)
