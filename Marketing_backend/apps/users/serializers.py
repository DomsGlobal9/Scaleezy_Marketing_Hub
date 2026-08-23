from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.workspaces.models import WorkspaceMember

User = get_user_model()


class WorkspaceMembershipSerializer(serializers.ModelSerializer):
    workspace_id = serializers.UUIDField(source='workspace.id', read_only=True)
    workspace_name = serializers.CharField(source='workspace.workspace_name', read_only=True)

    class Meta:
        model = WorkspaceMember
        fields = ['workspace_id', 'workspace_name', 'role', 'status']


class CurrentUserSerializer(serializers.ModelSerializer):
    """Shape returned by /auth/me/ — identity plus what it can reach."""

    memberships = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_staff', 'memberships']
        read_only_fields = fields

    def get_memberships(self, obj):
        qs = (
            WorkspaceMember.objects.select_related('workspace')
            .filter(user=obj, status=WorkspaceMember.Status.ACTIVE)
            .order_by('workspace__workspace_name')
        )
        return WorkspaceMembershipSerializer(qs, many=True).data


class ScaleezyTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Adds workspace context to the JWT payload so the frontend can route without
    a second round trip. Roles are still re-checked server-side on every
    request — the claim is a convenience, never the authority.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        memberships = list(
            WorkspaceMember.objects.filter(
                user=user, status=WorkspaceMember.Status.ACTIVE
            ).values('workspace_id', 'role')
        )
        token['memberships'] = [
            {'workspace_id': str(m['workspace_id']), 'role': m['role']} for m in memberships
        ]
        token['email'] = user.email
        return token
