"""
Workspace-aware permissions.

Every business object in this project hangs off a MarketingWorkspace. These
classes turn that into an enforced boundary: a caller may only touch data in a
workspace they are an active member of, and only if their role is high enough.
"""
import logging

from django.core.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.workspaces.models import WorkspaceMember

logger = logging.getLogger(__name__)


def get_membership(user, workspace_id):
    """
    Returns the caller's active membership for a workspace, or None.

    Returns None rather than raising so callers can decide between 403 and 404.
    """
    if not user or not user.is_authenticated or not workspace_id:
        return None
    return (
        WorkspaceMember.objects.select_related('workspace')
        .filter(
            user=user,
            workspace_id=workspace_id,
            status=WorkspaceMember.Status.ACTIVE,
        )
        .first()
    )


def resolve_workspace_id(request, view=None):
    """
    Finds the workspace the request is acting on.

    Checked in order: explicit X-Workspace-Id header, then a workspace_id in the
    body or query string. Falls back to the caller's sole membership when they
    belong to exactly one workspace, which keeps the existing single-workspace
    frontend working without sending the header everywhere.
    """
    header = request.headers.get('X-Workspace-Id')
    if header:
        return header

    for source in (getattr(request, 'data', None), getattr(request, 'query_params', None)):
        if isinstance(source, dict) or hasattr(source, 'get'):
            value = source.get('workspace_id') if source is not None else None
            if value:
                return value

    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        memberships = list(
            WorkspaceMember.objects.filter(
                user=user, status=WorkspaceMember.Status.ACTIVE
            ).values_list('workspace_id', flat=True)[:2]
        )
        if len(memberships) == 1:
            return str(memberships[0])
    return None


class IsWorkspaceMember(BasePermission):
    """Caller must be an active member of the workspace being acted on."""

    message = "You do not have access to this workspace."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        workspace_id = resolve_workspace_id(request, view)
        if not workspace_id:
            # No workspace resolved. Allow through so the view can 400 with a
            # useful message rather than a bare 403 — object-level checks and
            # queryset scoping still prevent any cross-workspace read.
            return True

        membership = get_membership(user, workspace_id)
        if membership is None:
            logger.warning(
                "Denied workspace access: user=%s workspace=%s", user.pk, workspace_id
            )
            return False

        # Cache for the view and for HasWorkspaceRole, which runs after this.
        request.workspace_membership = membership
        return True

    def has_object_permission(self, request, view, obj):
        workspace_id = _workspace_id_of(obj)
        if workspace_id is None:
            return True
        return get_membership(request.user, workspace_id) is not None


class HasWorkspaceRole(BasePermission):
    """
    Requires a minimum role. Set `required_role` on the view; safe methods fall
    back to `required_read_role` (default VIEWER) so reads stay open to the team.

        class BrandViewSet(ModelViewSet):
            permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
            required_role = WorkspaceMember.Role.MANAGER
    """

    message = "Your role does not allow this action."

    def has_permission(self, request, view):
        required = (
            getattr(view, 'required_read_role', WorkspaceMember.Role.VIEWER)
            if request.method in SAFE_METHODS
            else getattr(view, 'required_role', WorkspaceMember.Role.EDITOR)
        )

        membership = getattr(request, 'workspace_membership', None)
        if membership is None:
            workspace_id = resolve_workspace_id(request, view)
            membership = get_membership(request.user, workspace_id)
        if membership is None:
            return False

        allowed = membership.has_at_least(required)
        if not allowed:
            logger.warning(
                "Denied by role: user=%s role=%s required=%s",
                request.user.pk, membership.role, required,
            )
        return allowed


def get_request_workspace(request):
    """
    Resolves the workspace for a plain APIView and verifies membership.

    Returns (workspace, None) on success or (None, error_response) so the view
    can `return error` directly. Replaces `MarketingWorkspace.objects.first()`,
    which handed whichever workspace the database returned first to whoever
    asked — across tenants.
    """
    from rest_framework import status

    from apps.common.responses import APIResponse
    from apps.workspaces.models import MarketingWorkspace

    workspace_id = resolve_workspace_id(request)
    if not workspace_id:
        return None, APIResponse(
            success=False,
            message="No workspace selected. Send an X-Workspace-Id header.",
            error={"code": "NO_WORKSPACE", "message": "No workspace selected."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if get_membership(request.user, workspace_id) is None:
        # 404 rather than 403: revealing that a workspace exists but is barred
        # tells an attacker their guessed id was real.
        logger.warning(
            "Workspace access denied: user=%s workspace=%s",
            getattr(request.user, 'pk', None), workspace_id,
        )
        return None, APIResponse(
            success=False,
            message="Workspace not found.",
            error={"code": "WORKSPACE_NOT_FOUND", "message": "Workspace not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        return MarketingWorkspace.objects.get(id=workspace_id), None
    except (MarketingWorkspace.DoesNotExist, ValueError, ValidationError):
        return None, APIResponse(
            success=False,
            message="Workspace not found.",
            error={"code": "WORKSPACE_NOT_FOUND", "message": "Workspace not found."},
            status=status.HTTP_404_NOT_FOUND,
        )


def _workspace_id_of(obj):
    """Best-effort workspace id for an arbitrary model instance."""
    if hasattr(obj, 'workspace_id'):
        return obj.workspace_id
    if hasattr(obj, 'workspace'):
        return getattr(obj.workspace, 'id', None)
    # The object *is* a workspace
    if obj.__class__.__name__ == 'MarketingWorkspace':
        return obj.pk
    return None
