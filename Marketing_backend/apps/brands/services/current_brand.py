"""Resolve the brand represented by the workspace-level ``current`` APIs.

Both the Brand endpoint and the Brand Master bootstrap endpoint need exactly
the same lifecycle behaviour.  Keeping that decision here prevents a pending
or rejected client from getting different answers depending on which screen
loads first.
"""
import logging

from ..models import Brand

logger = logging.getLogger(__name__)


def get_current_brand(workspace, user):
    """Return the workspace's current brand, creating one only when allowed.

    This is the established ``BrandViewSet.current`` policy extracted intact:
    pending brands remain current and rejected clients receive their archived
    brand. If no brand exists at all, a new one inherits the workspace's
    approval-aware initial status rather than bypassing the spend gate.
    """
    brand = (
        Brand.objects.filter(workspace=workspace)
        .exclude(status=Brand.Status.ARCHIVED)
        .order_by('-is_default', 'created_at')
        .first()
    )
    if brand is None and not workspace.is_approved:
        brand = (
            Brand.objects.filter(workspace=workspace)
            .order_by('-is_default', '-created_at')
            .first()
        )
    if brand is None:
        from .approval import initial_brand_status
        from apps.common.permissions import get_membership
        from apps.workspaces.models import WorkspaceMember
        from rest_framework.exceptions import PermissionDenied

        membership = get_membership(user, workspace.pk)
        if not workspace.is_active or membership is None or membership.role not in (
            WorkspaceMember.Role.EDITOR, WorkspaceMember.Role.MANAGER,
            WorkspaceMember.Role.ADMIN, WorkspaceMember.Role.OWNER,
        ):
            raise PermissionDenied('This workspace has no available brand. An editor or administrator must initialize it.')

        name = workspace.workspace_name or 'My Brand'
        if Brand.objects.filter(workspace=workspace, name=name).exists():
            name = f"{name} (new)"
        brand = Brand.objects.create(
            workspace=workspace,
            name=name,
            is_default=True,
            status=initial_brand_status(workspace),
            created_by=user,
        )
        logger.info("Created default brand %s for workspace %s", brand.pk, workspace.pk)

    return brand
