from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import HasWorkspaceRole, IsWorkspaceMember, get_request_workspace
from apps.common.responses import APIResponse
from apps.workspaces.models import WorkspaceMember

from .models import AutopilotPolicy, AutopilotRun
from .serializers import AutopilotPolicySerializer, AutopilotRunSerializer
from .services import AutopilotQueueUnavailable, emergency_stop, queue_run


class AutopilotPolicyViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    queryset = AutopilotPolicy.objects.select_related('workspace', 'brand', 'created_by').prefetch_related(
        'social_connections'
    )
    serializer_class = AutopilotPolicySerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    required_role = WorkspaceMember.Role.ADMIN
    required_read_role = WorkspaceMember.Role.VIEWER
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        queryset = super().get_queryset()
        brand_id = self.request.query_params.get('brand_id')
        return queryset.filter(brand_id=brand_id) if brand_id else queryset

    def perform_create(self, serializer):
        workspace, error = get_request_workspace(self.request)
        if error:
            raise ValidationError('No accessible workspace selected.')
        serializer.save(workspace=workspace, created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def trigger(self, request, pk=None):
        policy = self.get_object()
        if not policy.enabled or policy.paused or policy.emergency_stop:
            return APIResponse(
                success=False, message='Enable and resume this policy before running it.',
                status=status.HTTP_409_CONFLICT,
            )
        try:
            run = queue_run(policy, initiated_by=request.user)
        except AutopilotQueueUnavailable as exc:
            run = exc.run
            return APIResponse(
                success=False,
                data=AutopilotRunSerializer(run).data,
                error={'code': run.error_code, 'message': run.error},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return APIResponse(
            success=True, data=AutopilotRunSerializer(run).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'], url_path='emergency-stop')
    def emergency(self, request, pk=None):
        policy = emergency_stop(self.get_object(), by=request.user)
        return APIResponse(
            success=True, message='Autopilot stopped. No new generation will start.',
            data=self.get_serializer(policy).data,
        )

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        policy = self.get_object()
        policy.emergency_stop = False
        policy.paused = False
        policy.save(update_fields=['emergency_stop', 'paused', 'updated_at'])
        return APIResponse(success=True, data=self.get_serializer(policy).data)


class AutopilotRunViewSet(WorkspaceScopedMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AutopilotRun.objects.select_related(
        'workspace', 'policy', 'generation_request', 'content_item'
    ).prefetch_related('steps')
    serializer_class = AutopilotRunSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    required_read_role = WorkspaceMember.Role.VIEWER

    def get_queryset(self):
        queryset = super().get_queryset()
        policy_id = self.request.query_params.get('policy_id')
        return queryset.filter(policy_id=policy_id) if policy_id else queryset
