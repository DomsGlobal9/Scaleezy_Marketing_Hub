from rest_framework import serializers

from .models import Feedback, FeedbackElement


class FeedbackElementSerializer(serializers.ModelSerializer):
    group_label = serializers.CharField(source='get_group_display', read_only=True)

    class Meta:
        model = FeedbackElement
        fields = ['key', 'label', 'group', 'group_label', 'description', 'is_provisional']


class FeedbackSerializer(serializers.ModelSerializer):
    element_keys = serializers.ListField(
        child=serializers.SlugField(max_length=64), required=False, allow_empty=True
    )
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = Feedback
        # The embedding is a large float list of no use to the browser, so it
        # is never serialised out.
        exclude = ['embedding']
        # before/after assets are set server-side from the content item.
        # Accepting them from the client would let a caller point feedback at
        # another tenant's asset id.
        read_only_fields = [
            'id', 'workspace', 'brand', 'user', 'sentiment', 'embedding_model',
            'pattern_extracted', 'rules_updated', 'created_at',
            'before_asset', 'after_asset',
        ]

    def validate_element_keys(self, value):
        """
        Rejects tags outside the vocabulary. Without this the training engine
        would happily learn rules about elements that do not exist, and a
        typo would silently become its own pattern.
        """
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

    def validate(self, attrs):
        """Every corrective entry path must carry an actionable signal."""
        if attrs.get('verdict') not in Feedback.CORRECTIVE:
            return attrs
        if not attrs.get('element_keys'):
            raise serializers.ValidationError(
                {
                    'element_keys': (
                        'Select at least one issue so Scaleezy can learn from this correction.'
                    )
                }
            )
        if not str(attrs.get('feedback_text') or '').strip() and not str(
            attrs.get('fix_request') or ''
        ).strip():
            raise serializers.ValidationError(
                'Explain the problem or how it should be fixed so the learned rule is actionable.'
            )
        return attrs
