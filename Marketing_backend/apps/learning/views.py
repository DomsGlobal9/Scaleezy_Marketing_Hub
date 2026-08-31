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
from rest_framework.views import APIView

from apps.brands.services.brand_brain import rebuild_brand_brain_safely
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
from .models import LearningEvent, SubjectType
from .services import (
    LearningError,
    create_explicit_rule,
    deactivate_rule,
    record_event_safely,
)
from .usage import learning_usage_report


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
        # "This is not us" is as much a judgment as "this is". Recorded so the
        # correction is part of the brand's history rather than a silent
        # deletion, and so a later pass can see that a person disagreed.
        record_event_safely(
            workspace=preference.workspace,
            brand=preference.brand,
            event_type=LearningEvent.EventType.PREFERENCE_SIGNAL,
            outcome=LearningEvent.Outcome.NEGATIVE,
            subject_type=SubjectType.OTHER,
            subject_id=preference.pk,
            context={
                'action': 'PREFERENCE_RETIRED',
                'category': preference.category,
                'attribute': preference.attribute,
                'value': preference.value,
            },
            dedupe_key=f'preference-retired:{preference.pk}',
            created_by=request.user,
        )
        rebuild_brand_brain_safely(preference.brand)
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
        # An explicit rule outranks everything learned; the snapshot that
        # generation reads must carry it immediately.
        rebuild_brand_brain_safely(rule.brand)
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
        # Switching off a LEARNED rule is a person overruling an inference —
        # the single strongest correction available to them. It has to be in
        # the ledger, or the only trace of it is a boolean on a row.
        record_event_safely(
            workspace=rule.workspace,
            brand=rule.brand,
            event_type=LearningEvent.EventType.EXPLICIT_RULE,
            outcome=LearningEvent.Outcome.NEGATIVE,
            subject_type=SubjectType.OTHER,
            subject_id=rule.pk,
            context={
                'action': 'RULE_DEACTIVATED',
                'origin': rule.origin,
                'hardness': rule.hardness,
                'text': rule.text[:500],
                'key': (rule.structured or {}).get('key', ''),
            },
            dedupe_key=f'rule-deactivated:{rule.pk}',
            created_by=request.user,
        )
        rebuild_brand_brain_safely(rule.brand)
        return APIResponse(
            success=True,
            message="Rule deactivated. It no longer constrains generation.",
            data=BrandRuleSerializer(
                rule, context=self.get_serializer_context()
            ).data,
        )


class LearningUsageView(APIView):
    """GET /learning/usage/?brand_id= — what has been learned, and what of it
    is actually reaching generation.

    A read, so VIEWER is enough; the same workspace resolution every other
    tenant view uses, and the brand is resolved INSIDE that workspace so a
    brand id from another client is simply not found.
    """

    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def get(self, request):
        from apps.brands.models import Brand

        workspace, error = get_request_workspace(request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")

        brands = Brand.objects.filter(workspace=workspace)
        brand_id = request.query_params.get('brand_id')
        brand = (
            brands.filter(pk=brand_id).first() if brand_id
            else brands.order_by('-is_default', 'created_at').first()
        )
        if brand is None:
            return APIResponse(
                success=False,
                message="Brand not found.",
                error={'code': 'NOT_FOUND', 'message': "Brand not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return APIResponse(success=True, data=learning_usage_report(workspace, brand))
