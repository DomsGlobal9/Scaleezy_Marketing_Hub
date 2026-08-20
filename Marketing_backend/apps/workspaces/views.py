import logging

from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.common.mixins import WorkspaceScopedMixin
from rest_framework.permissions import IsAuthenticated
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse

from .models import MarketingWorkspace, WorkspaceMember
from .serializers import AuditLogSerializer, MarketingWorkspaceSerializer

logger = logging.getLogger(__name__)


class MarketingWorkspaceViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    """
    Workspaces the caller belongs to.

    `workspace_field = 'id'` because the scoping filter is applied to the
    workspace table itself rather than to a foreign key on a child row.
    """

    queryset = MarketingWorkspace.objects.all()
    serializer_class = MarketingWorkspaceSerializer
    workspace_field = 'id'
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    # Renaming or deleting a workspace destroys every child row with it, so it
    # is not something a VIEWER or EDITOR should be able to do.
    required_role = WorkspaceMember.Role.ADMIN
    required_read_role = WorkspaceMember.Role.VIEWER

    def get_permissions(self):
        # Creating a workspace cannot require membership of one.
        if self.action == 'create':
            return [IsAuthenticated()]
        return super().get_permissions()

    def perform_create(self, serializer):
        # Whoever creates a workspace owns it, otherwise the creator would be
        # locked out of the row they just made by the scoping filter.
        workspace = serializer.save()
        WorkspaceMember.objects.get_or_create(
            workspace=workspace,
            user=self.request.user,
            defaults={'role': WorkspaceMember.Role.OWNER},
        )
        logger.info(
            "Workspace %s created by user %s", workspace.pk, self.request.user.pk
        )


class WorkspaceSettingsView(APIView):
    """Workspace settings plus its recent audit trail."""

    permission_classes = [IsWorkspaceMember]

    def get(self, request):
        workspace, error = get_request_workspace(request)
        if error:
            return error

        audit_logs = AuditLog.objects.filter(workspace=workspace).order_by('-date')[:50]
        # Top-level keys, not the envelope: the settings page reads
        # data.workspace and data.audit_logs directly.
        return Response(
            {
                "workspace": MarketingWorkspaceSerializer(workspace).data,
                "audit_logs": AuditLogSerializer(audit_logs, many=True).data,
            }
        )

    def put(self, request):
        workspace, error = get_request_workspace(request)
        if error:
            return error

        membership = getattr(request, 'workspace_membership', None)
        if membership is None or not membership.has_at_least(WorkspaceMember.Role.ADMIN):
            return APIResponse(
                success=False,
                message="Only a workspace admin can change these settings.",
                error={"code": "FORBIDDEN", "message": "Admin role required."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = MarketingWorkspaceSerializer(
            workspace, data=request.data.get('workspace', request.data), partial=True
        )
        if not serializer.is_valid():
            return APIResponse(
                success=False, error=serializer.errors, status=status.HTTP_400_BAD_REQUEST
            )

        serializer.save()
        logger.info("Workspace %s settings updated by user %s", workspace.pk, request.user.pk)
        return Response({"workspace": serializer.data})
