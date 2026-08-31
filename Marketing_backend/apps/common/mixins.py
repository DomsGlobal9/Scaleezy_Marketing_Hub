"""
Queryset scoping.

Permissions alone are not enough: a list endpoint with a correct permission
class will still return every tenant's rows if the queryset is unfiltered. This
mixin makes scoping the default rather than something each view remembers.
"""
import logging

from apps.common.permissions import (
    WorkspaceMismatch,
    cached_membership_for_workspace,
    get_membership,
    resolve_workspace_id,
)

logger = logging.getLogger(__name__)


class WorkspaceScopedMixin:
    """
    Restricts `get_queryset()` to workspaces the caller is an active member of.

    Set `workspace_field` when the path to the workspace is not `workspace`,
    e.g. `workspace_field = 'publishing_job__workspace'`.
    """

    workspace_field = 'workspace'

    def accessible_workspace_ids(self):
        """Return only the workspace this request explicitly addresses.

        Membership is authorization, not selection. A multi-client user may
        legitimately belong to A and B, but a page addressed to A must never
        enumerate B's rows. ``resolve_workspace_id`` keeps the established
        single-membership fallback while failing closed for ambiguous or
        mismatched requests.
        """
        user = self.request.user
        if not user or not user.is_authenticated:
            return []
        try:
            workspace_id = resolve_workspace_id(self.request, self)
        except WorkspaceMismatch:
            return []
        if not workspace_id:
            return []

        membership = cached_membership_for_workspace(self.request, workspace_id)
        if membership is None:
            membership = get_membership(user, workspace_id)
        if membership is None:
            return []
        return [workspace_id]

    def get_queryset(self):
        queryset = super().get_queryset()

        workspace_ids = self.accessible_workspace_ids()
        if not workspace_ids:
            return queryset.none()

        return queryset.filter(**{f'{self.workspace_field}__in': workspace_ids})
