"""
Learning fabric APIs.

Same shape as `apps.knowledge` and `apps.inspirations`: workspace-scoped
queryset, role-gated writes, lifecycle through named actions, and nothing that
carries provenance can be edited or deleted.
"""
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.workspaces.models import WorkspaceMember

from .models import BrandPreference, BrandRule, LearningEvent
from .serializers import (
    BrandPreferenceSerializer,
    BrandRuleSerializer,
    LearningEventSerializer,
)
from .services import LearningError, create_explicit_rule, deactivate_rule


class LearningBaseViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def _authorised_workspace(self):
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        return workspace

    def get_queryset(self):
        queryset = super().get_queryset()
        brand_id = self.request.query_params.get('brand_id')
        if brand_id:
            queryset = queryset.filter(brand_id=brand_id)
        return queryset


class LearningEventViewSet(
    WorkspaceScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    LearningBaseViewSet,
):
    """Evidence. Append-only.

    No update and no delete, deliberately: a rule cites the events it was
    learned from, and evidence that can be rewritten afterwards cannot support
    anything.
    """

    queryset = LearningEvent.objects.all()
    serializer_class = LearningEventSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        event_type = self.request.query_params.get('event_type')
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        subject_id = self.request.query_params.get('subject_id')
        if subject_id:
            queryset = queryset.filter(subject_id=subject_id)
        if self.request.query_params.get('aggregate_eligible') == 'true':
            queryset = queryset.eligible_for_aggregate()
        return queryset

    def perform_create(self, serializer):
        serializer.save(
            workspace=self._authorised_workspace(), created_by=self.request.user
        )


class BrandPreferenceViewSet(
    WorkspaceScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    LearningBaseViewSet,
):
    """Leanings. Read-only through the API.

    A preference is derived from evidence, so there is no endpoint to declare
    one — that would be a way to assert a brand truth with nothing behind it.
    They are created by `services.reinforce_preference`, and retired here when
    a human decides they no longer apply.
    """

    queryset = BrandPreference.objects.all()
    serializer_class = BrandPreferenceSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get('active_only') == 'true':
            queryset = queryset.active()
        return queryset

    @action(detail=True, methods=['post'])
    def retire(self, request, pk=None):
        preference = self.get_object()
        if preference.state == BrandPreference.State.RETIRED:
            return APIResponse(
                success=False,
                message="Preference is already retired.",
                status=status.HTTP_400_BAD_REQUEST,
            )
        preference.state = BrandPreference.State.RETIRED
        preference.save(update_fields=['state', 'updated_at'])
        return APIResponse(
            success=True,
            message="Preference retired. It no longer influences generation.",
            data=BrandPreferenceSerializer(
                preference, context=self.get_serializer_context()
            ).data,
        )


class BrandRuleViewSet(
    WorkspaceScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    LearningBaseViewSet,
):
    """Instructions the generator obeys.

    Creating one through the API always produces an EXPLICIT rule: a person is
    stating it. Learned rules exist only through
    `services.promote_preference_to_rule`, which requires corroborating
    evidence and can only ever produce a soft rule.
    """

    queryset = BrandRule.objects.all()
    serializer_class = BrandRuleSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get('in_force') == 'true':
            queryset = queryset.in_force()
        hardness = self.request.query_params.get('hardness')
        if hardness:
            queryset = queryset.filter(hardness=hardness)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            rule = create_explicit_rule(
                workspace=self._authorised_workspace(),
                brand=data.get('brand'),
                text=data['text'],
                hardness=data.get('hardness', BrandRule.Hardness.SOFT),
                priority=data.get('priority', 0),
                scope=data.get('scope', BrandRule.scope.field.default),
                structured=data.get('structured'),
                created_by=request.user,
            )
        except LearningError as exc:
            return APIResponse(
                success=False,
                message=str(exc),
                error={"code": "LEARNING_CONFLICT", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return APIResponse(
            success=True,
            data=BrandRuleSerializer(
                rule, context=self.get_serializer_context()
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        rule = self.get_object()
        if not rule.is_active:
            return APIResponse(
                success=False,
                message="Rule is already inactive.",
                status=status.HTTP_400_BAD_REQUEST,
            )
        deactivate_rule(rule=rule, user=request.user)
        return APIResponse(
            success=True,
            message="Rule deactivated. It no longer constrains generation.",
            data=BrandRuleSerializer(
                rule, context=self.get_serializer_context()
            ).data,
        )
