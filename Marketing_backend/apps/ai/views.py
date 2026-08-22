import logging

from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.workspaces.models import WorkspaceMember

from .models import AIProvider, AIUsageLog, Capability, Strategy, WorkspaceAIProvider, WorkspaceAIRoute
from .registry import all_adapters
from .router import AIRouter
from .serializers import (
    AIProviderSerializer,
    AIUsageLogSerializer,
    WorkspaceAIProviderSerializer,
    WorkspaceAIRouteSerializer,
    ReplaceWorkspaceAIRouteSetSerializer,
)

logger = logging.getLogger(__name__)


class AIProviderCatalogueView(APIView):
    """
    Providers installed in this deployment, plus the capability and strategy
    vocabularies the console needs to render its controls.
    """

    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    required_read_role = WorkspaceMember.Role.ADMIN

    def get(self, request):
        installed = set(all_adapters())
        providers = AIProvider.objects.all()
        return APIResponse(
            success=True,
            data={
                'providers': [
                    {**AIProviderSerializer(p).data, 'adapter_installed': p.key in installed}
                    for p in providers
                ],
                'capabilities': [
                    {'value': c.value, 'label': c.label} for c in Capability
                ],
                'strategies': [
                    {'value': s.value, 'label': s.label} for s in Strategy
                ],
            },
        )


class WorkspaceAIProviderViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    """Per-customer provider enablement. This is the on/off switch."""

    queryset = WorkspaceAIProvider.objects.select_related('provider').all()
    serializer_class = WorkspaceAIProviderSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    # Provider credentials are a spend and security decision, not an editing one.
    required_role = WorkspaceMember.Role.ADMIN
    required_read_role = WorkspaceMember.Role.ADMIN

    def _workspace(self):
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        return workspace

    def perform_create(self, serializer):
        serializer.save(workspace=self._workspace())

    @action(detail=True, methods=['post'], url_path='test')
    def test(self, request, pk=None):
        """Runs the adapter's health check and records the outcome."""
        wp = self.get_object()
        result = AIRouter(wp.workspace).health(wp)
        return APIResponse(
            success=bool(result.get('ok')),
            message=result.get('detail', ''),
            data=WorkspaceAIProviderSerializer(wp).data,
        )


class WorkspaceAIRouteViewSet(WorkspaceScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Which provider serves which capability, and in what order.

    Route rows are deliberately read-only.  A capability's providers, order
    and strategy form one policy, so changing an individual row could bypass
    the validation and transaction in ``replace_set`` or leave a partially
    updated policy behind.
    """

    queryset = WorkspaceAIRoute.objects.select_related('provider').all()
    serializer_class = WorkspaceAIRouteSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.ADMIN
    required_read_role = WorkspaceMember.Role.ADMIN

    @action(detail=False, methods=['post'], url_path='replace-set')
    def replace_set(self, request):
        """Atomically replace the ordered provider set for one capability.

        One capability may have multiple providers. Priority defines failover
        order; BEST_OF and ROUND_ROBIN consume the same set. The entire set is
        validated before any existing route is changed.
        """
        workspace, error = get_request_workspace(request)
        if error:
            return error

        payload = ReplaceWorkspaceAIRouteSetSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        capability = data['capability']
        members = data['routes']

        for member in members:
            provider = member['provider']
            adapter = all_adapters().get(provider.key)
            declared = {str(value) for value in (getattr(adapter, 'capabilities', ()) or ())}
            if (
                not provider.is_available
                or adapter is None
                or not provider.supports(capability)
                or capability not in declared
            ):
                return APIResponse(
                    success=False,
                    message="That provider cannot serve this capability.",
                    error={"code": "INVALID_AI_ROUTE", "message": capability},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not WorkspaceAIProvider.objects.filter(
                workspace=workspace, provider=provider, enabled=True
            ).exists():
                return APIResponse(
                    success=False,
                    message="Enable the provider before routing work to it.",
                    error={"code": "PROVIDER_NOT_ENABLED", "message": provider.display_name},
                    status=status.HTTP_409_CONFLICT,
                )

        with transaction.atomic():
            existing = WorkspaceAIRoute.objects.select_for_update().filter(
                workspace=workspace, capability=capability
            )
            keep = []
            for member in members:
                provider = member['provider']
                route, _created = WorkspaceAIRoute.objects.update_or_create(
                    workspace=workspace,
                    capability=capability,
                    provider=provider,
                    defaults={
                        'priority': member['priority'],
                        'strategy': data['strategy'],
                        'enabled': True,
                    },
                )
                keep.append(route.pk)
            existing.exclude(pk__in=keep).delete()

        routes = WorkspaceAIRoute.objects.filter(
            workspace=workspace, capability=capability
        ).select_related('provider').order_by('priority')

        return APIResponse(
            success=True,
            data=WorkspaceAIRouteSerializer(routes, many=True).data,
            message="AI route set updated.",
        )

    @action(detail=False, methods=['get'])
    def resolved(self, request):
        """
        What the router would actually do right now, per capability.

        Answers "why did my image go to Gemini?" without reading logs.
        """
        workspace, error = get_request_workspace(request)
        if error:
            return error

        router = AIRouter(workspace)
        out = {}
        for capability in Capability:
            candidates = router._candidates(capability.value)
            out[capability.value] = {
                'strategy': router.strategy_for(capability.value),
                'providers': [c['route'].provider.key for c in candidates],
            }
        return APIResponse(success=True, data=out)


class AIUsageViewSet(WorkspaceScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Per-call cost and latency record."""

    queryset = AIUsageLog.objects.select_related('provider').all()
    serializer_class = AIUsageLogSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_read_role = WorkspaceMember.Role.MANAGER

    @action(detail=False, methods=['get'])
    def summary(self, request):
        from django.db.models import Count, Sum

        rows = (
            self.get_queryset()
            .values('provider__key', 'capability')
            .annotate(calls=Count('id'), spend=Sum('cost'))
            .order_by('-calls')
        )
        return APIResponse(success=True, data=list(rows))
