from rest_framework import serializers

from apps.brands.models import Brand
from apps.common.permissions import get_request_workspace
from apps.social_accounts.models import SocialConnection

from .models import EngagementItem, EngagementSyncRun, SavedReply


def _workspace(serializer):
    workspace, error = get_request_workspace(serializer.context['request'])
    if error or not workspace:
        raise serializers.ValidationError('A valid workspace is required.')
    return workspace


class EngagementItemSerializer(serializers.ModelSerializer):
    workspace = serializers.UUIDField(source='workspace_id', read_only=True)
    brand = serializers.UUIDField(source='brand_id', read_only=True)
    social_connection = serializers.UUIDField(source='social_connection_id', read_only=True)
    assigned_to_name = serializers.SerializerMethodField()
    locked_by_name = serializers.SerializerMethodField()

    class Meta:
        model = EngagementItem
        fields = [
            'id', 'workspace', 'brand', 'social_connection', 'platform', 'kind',
            'external_id', 'thread_id', 'author_name', 'author_handle', 'body',
            'source_url', 'occurred_at', 'status', 'sentiment', 'urgency',
            'assigned_to', 'assigned_to_name', 'locked_by', 'locked_by_name',
            'lock_expires_at', 'ai_draft', 'draft_status', 'draft_task_id',
            'ai_provider_key', 'ai_provider_name', 'ai_risk_flags',
            'approved_response', 'approved_by', 'approved_at',
            'external_response_id', 'responded_at', 'last_error', 'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    @staticmethod
    def get_assigned_to_name(obj):
        return obj.assigned_to.get_username() if obj.assigned_to else ''

    @staticmethod
    def get_locked_by_name(obj):
        return obj.locked_by.get_username() if obj.locked_by else ''


class EngagementSyncRunSerializer(serializers.ModelSerializer):
    workspace = serializers.UUIDField(source='workspace_id', read_only=True)

    class Meta:
        model = EngagementSyncRun
        fields = [
            'id', 'workspace', 'brand', 'social_connection', 'status', 'task_id',
            'cursor', 'imported_count', 'seen_count', 'error', 'started_at',
            'completed_at', 'created_at',
        ]
        read_only_fields = [
            'id', 'workspace', 'status', 'task_id', 'cursor', 'imported_count',
            'seen_count', 'error', 'started_at', 'completed_at', 'created_at',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is None:
            return
        workspace, error = get_request_workspace(request)
        if error or not workspace:
            return
        self.fields['brand'].queryset = Brand.objects.filter(workspace=workspace)
        self.fields['social_connection'].queryset = SocialConnection.objects.filter(
            workspace=workspace, status=SocialConnection.Status.CONNECTED
        )

    def validate(self, data):
        workspace = _workspace(self)
        brand = data.get('brand')
        connection = data.get('social_connection')
        if brand is None or brand.workspace_id != workspace.id:
            raise serializers.ValidationError({'brand': 'Brand must belong to this workspace.'})
        if connection is None or connection.workspace_id != workspace.id:
            raise serializers.ValidationError(
                {'social_connection': 'Connection must belong to this workspace.'}
            )
        if connection.platform not in (
            SocialConnection.Platform.X, SocialConnection.Platform.YOUTUBE
        ):
            raise serializers.ValidationError({
                'social_connection': (
                    'Live inbox sync currently supports X mentions and YouTube comments. '
                    'Other platforms remain explicitly unavailable.'
                )
            })
        return data


class SavedReplySerializer(serializers.ModelSerializer):
    workspace = serializers.UUIDField(source='workspace_id', read_only=True)

    class Meta:
        model = SavedReply
        fields = ['id', 'workspace', 'name', 'body', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'workspace', 'created_at', 'updated_at']

    def validate_name(self, value):
        value = ' '.join(str(value or '').split())[:120]
        if not value:
            raise serializers.ValidationError('Name is required.')
        return value

    def validate_body(self, value):
        value = str(value or '').strip()[:2000]
        if not value:
            raise serializers.ValidationError('Reply text is required.')
        return value

    def validate(self, data):
        workspace = _workspace(self)
        name = data.get('name') or getattr(self.instance, 'name', '')
        duplicate = SavedReply.objects.filter(workspace=workspace, name=name)
        if self.instance is not None:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError({'name': 'A saved reply with this name exists.'})
        return data
