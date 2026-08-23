"""
Client Admin — team and roles, and nothing else.

Everything else a client administers already lives somewhere: brand
intelligence in Brand Master, providers and plan in Settings. Duplicating any
of it here would create a second place to change one thing.

There is deliberately no invite endpoint. Adding a brand-new person crosses
the tenant boundary and is a platform action, so this surface says so plainly
instead of shipping a disabled Invite button.
"""
import logging

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse

from .models import WorkspaceMember
from .services.team import (
    TeamError,
    change_member_role,
    permission_matrix,
    remove_member,
    set_member_status,
)

logger = logging.getLogger(__name__)


class WorkspaceMemberSerializer(serializers.ModelSerializer):
    """Read-only by design: every mutation goes through a service that
    enforces the authority rules, never through a bare PATCH."""

    user_id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    full_name = serializers.SerializerMethodField()
    invited_by_username = serializers.SerializerMethodField()
    rank = serializers.IntegerField(read_only=True)

    class Meta:
        model = WorkspaceMember
        fields = [
            'id', 'user_id', 'username', 'email', 'full_name',
            'role', 'rank', 'status', 'last_active_at',
            'invited_by_username', 'created_at',
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return (obj.user.get_full_name() or '').strip()

    def get_invited_by_username(self, obj):
        return obj.invited_by.get_username() if obj.invited_by_id else ''


class TeamViewSet(WorkspaceScopedMixin, viewsets.ReadOnlyModelViewSet):
    """`/api/marketing/team/` — the client's own people."""

    queryset = WorkspaceMember.objects.select_related('user', 'invited_by', 'workspace')
    serializer_class = WorkspaceMemberSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    # Anyone on the team may see who else is on it; only an admin may change it.
    required_read_role = WorkspaceMember.Role.VIEWER
    required_role = WorkspaceMember.Role.ADMIN

    def get_queryset(self):
        return super().get_queryset().order_by('-role', 'user__username')

    def _actor(self):
        membership = getattr(self.request, 'workspace_membership', None)
        if membership is not None:
            return membership
        workspace, error = get_request_workspace(self.request)
        if error:
            return None
        return WorkspaceMember.objects.filter(
            workspace=workspace, user=self.request.user,
            status=WorkspaceMember.Status.ACTIVE,
        ).first()

    def _refused(self, exc):
        return APIResponse(
            success=False,
            message=str(exc),
            error={'code': 'TEAM_CHANGE_REFUSED', 'message': str(exc)},
            status=status.HTTP_403_FORBIDDEN,
        )

    def list(self, request, *args, **kwargs):
        members = self.get_queryset()
        return APIResponse(success=True, data={
            'members': WorkspaceMemberSerializer(members, many=True).data,
            'permissions': permission_matrix(),
            # Stated, not implied by a disabled button.
            'can_invite': False,
            'invite_note': (
                'Scaleezy adds new people to a client. Ask your Scaleezy '
                'contact to attach a colleague to this account.'
            ),
        })

    @action(detail=True, methods=['post'], url_path='role')
    def set_role(self, request, pk=None):
        target = self.get_object()
        try:
            member = change_member_role(
                self._actor(), target, str(request.data.get('role', ''))
            )
        except TeamError as exc:
            return self._refused(exc)
        return APIResponse(
            success=True, message=f"Role updated to {member.role}.",
            data=WorkspaceMemberSerializer(member).data,
        )

    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        try:
            member = set_member_status(
                self._actor(), self.get_object(), WorkspaceMember.Status.SUSPENDED
            )
        except TeamError as exc:
            return self._refused(exc)
        return APIResponse(
            success=True, message="Access suspended.",
            data=WorkspaceMemberSerializer(member).data,
        )

    @action(detail=True, methods=['post'])
    def reactivate(self, request, pk=None):
        try:
            member = set_member_status(
                self._actor(), self.get_object(), WorkspaceMember.Status.ACTIVE
            )
        except TeamError as exc:
            return self._refused(exc)
        return APIResponse(
            success=True, message="Access restored.",
            data=WorkspaceMemberSerializer(member).data,
        )

    def destroy(self, request, *args, **kwargs):
        try:
            remove_member(self._actor(), self.get_object())
        except TeamError as exc:
            return self._refused(exc)
        return APIResponse(success=True, message="Removed from this client.")
