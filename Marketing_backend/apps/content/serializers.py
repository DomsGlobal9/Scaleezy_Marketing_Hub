from rest_framework import serializers

from .models import ContentItem


class ContentItemSerializer(serializers.ModelSerializer):
    is_publishable = serializers.BooleanField(read_only=True)

    class Meta:
        model = ContentItem
        fields = '__all__'
        # workspace is server-assigned; status only moves through the review
        # actions, never by a direct PATCH.
        read_only_fields = [
            'id', 'workspace', 'status', 'version', 'parent',
            'reviewed_by', 'reviewed_at', 'created_by', 'created_at', 'updated_at',
        ]

    def validate(self, attrs):
        request = self.context.get('request')
        if request is None:
            return attrs

        from apps.common.permissions import resolve_workspace_id

        workspace_id = resolve_workspace_id(request)
        for field in ('brand', 'asset'):
            value = attrs.get(field)
            if value is not None and str(value.workspace_id) != str(workspace_id):
                raise serializers.ValidationError(
                    {field: "This object does not belong to the selected client."}
                )
        return attrs


class ReviewActionSerializer(serializers.Serializer):
    """
    The payload of approve / reject / request-edits.

    `note` is the message the creator reads. The rest is the structured signal
    the Phase 6 training engine learns from — all optional, so a reviewer who
    just wants to click Approve still can.
    """

    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    elements = serializers.ListField(
        child=serializers.SlugField(max_length=64), required=False, allow_empty=True
    )
    fix_request = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    urgency = serializers.ChoiceField(
        choices=['LOW', 'NORMAL', 'HIGH'], required=False, default='NORMAL'
    )

    def validate_elements(self, value):
        from apps.feedback.models import FeedbackElement

        keys = list(dict.fromkeys(value or []))
        if not keys:
            return []
        known = set(
            FeedbackElement.objects.filter(key__in=keys, is_active=True).values_list(
                'key', flat=True
            )
        )
        unknown = [k for k in keys if k not in known]
        if unknown:
            raise serializers.ValidationError(
                f"Unknown feedback element(s): {', '.join(unknown)}"
            )
        return keys
