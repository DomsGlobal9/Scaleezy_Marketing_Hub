from rest_framework import serializers
from .models import SocialConnection, SocialAccountAuditLog

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
        # Only publishing_enabled and is_default_account are client-owned
        # configuration. Provider identity and lifecycle/health are written by
        # OAuth, verification and publishing, never by ordinary PATCH requests.
        read_only_fields = [
            'id', 'workspace', 'platform', 'account_type', 'external_account_id',
            'account_name', 'username', 'profile_url', 'profile_image_url',
            'status', 'last_verified_at', 'last_published_at', 'last_error',
            'connected_at', 'reauthorization_required',
        ]

class ConnectPlatformSerializer(serializers.Serializer):
    workspace_id = serializers.UUIDField()
    platform = serializers.ChoiceField(choices=SocialConnection.Platform.choices)


class SocialAccountAuditRowSerializer(serializers.ModelSerializer):
    """Connection events flattened to the row shape the accounts audit table
    renders — the same shape ``apps.audit.AuditLogSerializer`` produces — so
    the settings feed can interleave both without the frontend caring which
    table a row came from."""

    date = serializers.DateTimeField(source='created_at')
    user = serializers.SerializerMethodField()
    platform = serializers.SerializerMethodField()
    account = serializers.SerializerMethodField()
    action = serializers.CharField(source='get_action_display')
    previous_state = serializers.CharField(source='old_value')
    next_state = serializers.CharField(source='new_value')
    result = serializers.SerializerMethodField()
    error = serializers.CharField(source='error_message')

    class Meta:
        model = SocialAccountAuditLog
        fields = [
            'id', 'date', 'user', 'platform', 'account', 'action',
            'previous_state', 'next_state', 'result', 'error',
        ]

    def get_user(self, obj):
        # Publishing rows store the actor as plain text; render the same.
        return str(obj.user) if obj.user_id else ""

    def get_platform(self, obj):
        # The connection is SET_NULL, so a disconnect-then-delete keeps the row.
        return obj.social_connection.platform if obj.social_connection_id else ""

    def get_account(self, obj):
        return obj.social_connection.account_name if obj.social_connection_id else ""

    def get_result(self, obj):
        return "Failed" if obj.error_message else "Success"
