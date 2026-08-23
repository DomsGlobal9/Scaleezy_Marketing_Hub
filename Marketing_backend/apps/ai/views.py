import logging
import uuid

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
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

from .models import (
    AIProvider,
    AIUsageLog,
    Capability,
    ProviderIntegrationType,
    Strategy,
    WorkspaceAIProvider,
    WorkspaceAIRoute,
)
from .registry import adapter_class_for_provider, all_adapters
from .router import AIRouter
from .serializers import (
    AIProviderSerializer,
    AIUsageLogSerializer,
    CustomWorkspaceAIProviderSerializer,
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
        workspace, error = get_request_workspace(request)
        if error:
            return error
        installed = set(all_adapters())
        providers = AIProvider.objects.filter(
            Q(owner_workspace__isnull=True) | Q(owner_workspace=workspace)
        )
        return APIResponse(
            success=True,
            data={
                'providers': [
                    {
                        **AIProviderSerializer(p).data,
                        'adapter_installed': p.is_custom or p.key in installed,
                    }
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
        workspace = self._workspace()
        provider = serializer.validated_data['provider']
        if provider.owner_workspace_id not in (None, workspace.id):
            raise ValidationError({
                'provider': 'That provider is not available to the selected client.'
            })
        if WorkspaceAIProvider.objects.filter(
            workspace=workspace, provider=provider
        ).exists():
            raise ValidationError({
                'provider': 'This provider is already configured for the selected client.'
            })
        try:
            # The nested transaction keeps a concurrent duplicate from
            # breaking the request transaction before it becomes a friendly
            # validation response.
            with transaction.atomic():
                serializer.save(workspace=workspace)
        except IntegrityError as exc:
            raise ValidationError({
                'provider': 'This provider is already configured for the selected client.'
            }) from exc

    @action(detail=False, methods=['post'], url_path='custom')
    def custom(self, request):
        """Create one tenant-owned, manually described integration atomically."""
        workspace = self._workspace()
        payload = CustomWorkspaceAIProviderSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        from apps.social_accounts.utils.encryption import encrypt_token

        with transaction.atomic():
            provider = AIProvider.objects.create(
                owner_workspace=workspace,
                key=f'custom-{uuid.uuid4().hex}',
                display_name=data['display_name'],
                integration_type=data['integration_type'],
                base_url=data['base_url'],
                capabilities=data['capabilities'],
                default_model='',
                is_available=True,
                unit_cost=0,
            )
            workspace_provider = WorkspaceAIProvider.objects.create(
                workspace=workspace,
                provider=provider,
                enabled=data['enabled'],
                capabilities=data['capabilities'],
                credentials_encrypted=(
                    encrypt_token(data['credentials']) if data['credentials'] else ''
                ),
                model_override=data['model'],
            )

        return APIResponse(
            success=True,
            data=WorkspaceAIProviderSerializer(workspace_provider).data,
            message='Custom AI provider added.',
            status=status.HTTP_201_CREATED,
        )

    def perform_update(self, serializer):
        with transaction.atomic():
            workspace_provider = serializer.save()
            WorkspaceAIRoute.objects.filter(
                workspace=workspace_provider.workspace,
                provider=workspace_provider.provider,
            ).exclude(capability__in=workspace_provider.assigned_capabilities).delete()
            if not workspace_provider.enabled:
                WorkspaceAIRoute.objects.filter(
                    workspace=workspace_provider.workspace,
                    provider=workspace_provider.provider,
                    enabled=True,
                ).update(enabled=False)

    def perform_destroy(self, instance):
        with transaction.atomic():
            provider = instance.provider
            workspace_id = instance.workspace_id
            WorkspaceAIRoute.objects.filter(
                workspace=instance.workspace,
                provider=instance.provider,
            ).delete()
            instance.delete()
            if provider.owner_workspace_id == workspace_id:
                provider.delete()

    @action(detail=True, methods=['post'], url_path='test')
    def test(self, request, pk=None):
        """Runs the adapter's health check and records the outcome."""
        wp = self.get_object()
        # A health check reaches the provider; a client awaiting approval
        # does not spend on that either.
        from apps.brands.services.approval import approval_gate_response

        approval_error = approval_gate_response(wp.workspace)
        if approval_error:
            return approval_error
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
            adapter = adapter_class_for_provider(provider)
            declared = {str(value) for value in (getattr(adapter, 'capabilities', ()) or ())}
            if (
                provider.owner_workspace_id not in (None, workspace.id)
                or
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
            workspace_provider = WorkspaceAIProvider.objects.filter(
                workspace=workspace, provider=provider
            ).first()
            if workspace_provider is not None and not workspace_provider.supports(capability):
                return APIResponse(
                    success=False,
                    message="Assign this capability to the provider in Admin before routing it.",
                    error={"code": "CAPABILITY_NOT_ASSIGNED", "message": capability},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if workspace_provider is None or not workspace_provider.enabled:
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
        from django.db.models import Avg, Count, Q, Sum

        rows = (
            self.get_queryset()
            .values('provider__key', 'capability')
            .annotate(
                calls=Count('id'),
                successful_calls=Count('id', filter=Q(success=True)),
                failed_calls=Count('id', filter=Q(success=False)),
                spend=Sum('cost'),
                average_latency_ms=Avg('latency_ms'),
            )
            .order_by('-calls')
        )
        data = []
        for row in rows:
            calls = row['calls'] or 0
            row['success_rate_percent'] = round(
                (row['successful_calls'] / calls * 100) if calls else 0,
                2,
            )
            row['average_latency_ms'] = round(float(row['average_latency_ms'] or 0), 2)
            data.append(row)
        return APIResponse(success=True, data=data)
