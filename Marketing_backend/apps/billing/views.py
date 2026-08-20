import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.workspaces.models import WorkspaceMember

from . import quota
from .models import Plan
from .serializers import PlanSerializer

logger = logging.getLogger(__name__)


class BillingViewSet(viewsets.ViewSet):
    """
    What the workspace is entitled to, and how much of it is left.

    Read-only on purpose. Changing a plan is a commercial decision made in the
    admin, not a button in the product — an endpoint that let a customer
    upgrade themselves would be an endpoint that let them raise their own
    spend cap.
    """

    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_read_role = WorkspaceMember.Role.VIEWER

    def list(self, request):
        workspace, error = get_request_workspace(request)
        if error:
            return error
        return APIResponse(success=True, data=quota.summary(workspace))

    @action(detail=False, methods=['get'])
    def plans(self, request):
        return APIResponse(
            success=True, data=PlanSerializer(Plan.objects.all(), many=True).data
        )
