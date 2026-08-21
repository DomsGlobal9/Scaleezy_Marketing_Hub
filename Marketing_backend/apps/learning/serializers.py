"""
Serializers for the learning fabric.

Every tenant-owned relation is re-checked against the workspace resolved from
the authenticated request, and the fields that decide how much authority a
record carries — origin, evidence, state, active — are server-owned.
"""
from rest_framework import serializers

from apps.brands.models import Brand
from apps.common.permissions import get_request_workspace

from .models import BrandPreference, BrandRule, LearningEvent


def request_workspace_or_raise(serializer):
    workspace, error = get_request_workspace(serializer.context['request'])
    if error or not workspace:
        raise serializers.ValidationError("Workspace is required and must be valid.")
    return workspace


class WorkspaceScopedBrandSerializer(serializers.ModelSerializer):
    """Shared brand handling: the queryset is scoped to the caller's workspace
    and `validate` re-checks it, so a foreign id is neither resolvable nor
    accepted on any path."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is None:
            return
        workspace, error = get_request_workspace(request)
        if error or not workspace:
            return
        if 'brand' in self.fields:
            self.fields['brand'].queryset = Brand.objects.filter(workspace=workspace)

    def validate(self, data):
        workspace = request_workspace_or_raise(self)
        brand = data.get('brand') or getattr(self.instance, 'brand', None)
        if brand is not None and brand.workspace_id != workspace.id:
            raise serializers.ValidationError(
                {"brand": "Brand must belong to the authorized workspace."}
            )
        if self.instance is not None and 'brand' in data:
            if data['brand'] != self.instance.brand:
                raise serializers.ValidationError(
                    {"brand": "Brand cannot be changed once set."}
                )
        return data


class LearningEventSerializer(WorkspaceScopedBrandSerializer):
    class Meta:
        model = LearningEvent
        fields = [
            'id', 'workspace', 'brand', 'event_type', 'outcome',
            'subject_type', 'subject_id', 'source_type', 'source_id',
            'context', 'eligibility_for_aggregate_learning', 'dedupe_key',
            'created_by', 'created_at',
        ]
        read_only_fields = [
            'id', 'workspace', 'created_by', 'created_at',
            # Set by the service. A client that could choose its own dedupe key
            # could suppress somebody else's evidence by claiming it first.
            'dedupe_key',
        ]


class BrandPreferenceSerializer(WorkspaceScopedBrandSerializer):
    # The lineage, not just the number. A reviewer asking why the brand
    # believes something needs the events, and a count with nothing behind it
    # is what the CTO rework removed.
    evidence_event_ids = serializers.SerializerMethodField()

    def get_evidence_event_ids(self, obj):
        return [
            str(pk)
            for pk in obj.evidence.order_by('created_at').values_list(
                'learning_event_id', flat=True
            )
        ]

    class Meta:
        model = BrandPreference
        fields = [
            'id', 'workspace', 'brand', 'category', 'attribute', 'value',
            'weight', 'confidence', 'evidence_count', 'evidence_event_ids',
            'state', 'scope', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'workspace', 'created_at', 'updated_at',
            # Derived from evidence. If a client could set these it could
            # declare a one-off opinion "established" and skip the threshold
            # that stops one review becoming brand law.
            'evidence_count', 'state',
        ]


class BrandRuleSerializer(WorkspaceScopedBrandSerializer):
    class Meta:
        model = BrandRule
        fields = [
            'id', 'workspace', 'brand', 'text', 'structured', 'hardness',
            'origin', 'priority', 'scope', 'evidence_event_ids', 'confidence',
            'is_active', 'deactivated_at', 'deactivated_by',
            'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'workspace', 'created_by', 'created_at', 'updated_at',
            # A rule created through the API is one a person stated, so origin
            # is server-assigned; a client cannot mint a LEARNED rule and
            # borrow the authority of evidence that does not exist.
            'origin', 'evidence_event_ids', 'confidence',
            # Lifecycle moves through the deactivate action.
            'is_active', 'deactivated_at', 'deactivated_by',
        ]
