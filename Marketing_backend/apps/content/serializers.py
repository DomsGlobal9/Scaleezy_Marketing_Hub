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


class ReviewActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)
