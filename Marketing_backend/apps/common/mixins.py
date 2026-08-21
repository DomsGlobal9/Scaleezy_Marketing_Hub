"""
Queryset scoping.

Permissions alone are not enough: a list endpoint with a correct permission
class will still return every tenant's rows if the queryset is unfiltered. This
mixin makes scoping the default rather than something each view remembers.
"""
import logging

from apps.workspaces.models import WorkspaceMember

logger = logging.getLogger(__name__)


class WorkspaceScopedMixin:
    """
    Restricts `get_queryset()` to workspaces the caller is an active member of.

    Set `workspace_field` when the path to the workspace is not `workspace`,
    e.g. `workspace_field = 'publishing_job__workspace'`.
    """

    workspace_field = 'workspace'

    def accessible_workspace_ids(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return []
        return list(
            WorkspaceMember.objects.filter(
                user=user, status=WorkspaceMember.Status.ACTIVE
            ).values_list('workspace_id', flat=True)
        )

    def get_queryset(self):
        queryset = super().get_queryset()

        workspace_ids = self.accessible_workspace_ids()
        if not workspace_ids:
            return queryset.none()

        return queryset.filter(**{f'{self.workspace_field}__in': workspace_ids})
