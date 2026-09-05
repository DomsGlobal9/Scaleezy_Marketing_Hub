from rest_framework import serializers

from .models import ContentItem


class ContentItemSerializer(serializers.ModelSerializer):
    is_publishable = serializers.BooleanField(read_only=True)

    class Meta:
        model = ContentItem
        fields = '__all__'
        # workspace is server-assigned; status only moves through the review
        # actions, never by a direct PATCH. layout_config is the engine's
        # ledger (generation traces, A/B pairing, per-item choices) — a
        # client-writable pairing authority would let any editor graft
        # ab_group onto arbitrary items and have a pick auto-reject them.
        read_only_fields = [
            'id', 'workspace', 'status', 'version', 'parent', 'layout_config',
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

    def validate(self, attrs):
        """Corrective verdicts must carry evidence the learner can use.

        Approvals and submission keep their existing lightweight contract.
        Reject/request-edits are different: allowing an untagged or empty
        correction would report success while teaching nothing, which breaks
        the immediate-learning promise.
        """
        if not self.context.get('requires_learning_signal'):
            return attrs

        # The reviewer's own words are a full learning signal: element keys
        # are parsed from them in the worker (apps.feedback.nl), so nobody
        # has to know the vocabulary to teach the engine. Tapped tags remain
        # accepted for callers that still send them.
        note = str(attrs.get('note') or '').strip()
        fix_request = str(attrs.get('fix_request') or '').strip()
        if not attrs.get('elements') and not note and not fix_request:
            raise serializers.ValidationError(
                {
                    'non_field_errors': (
                        'Say what is wrong in your own words — one sentence is '
                        'enough for Scaleezy to fix it and learn from it.'
                    )
                }
            )
        return attrs
