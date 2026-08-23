import uuid
from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class MarketingWorkspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer_id = models.CharField(max_length=255, help_text="Reference to the customer/tenant in the main system")
    workspace_name = models.CharField(max_length=255)
    timezone = models.CharField(max_length=50, default='UTC')
    default_language = models.CharField(max_length=10, default='en')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'marketing_workspaces'

    def __str__(self):
        return self.workspace_name


class WorkspaceMember(models.Model):
    """
    Links a Django user to a workspace with a role.

    Django's default User model has no notion of a workspace, so this is the
    join that makes tenancy and RBAC enforceable. Every workspace-scoped
    queryset filters on the caller's memberships.
    """

    class Role(models.TextChoices):
        OWNER = 'OWNER', 'Owner'
        ADMIN = 'ADMIN', 'Workspace Admin'
        MANAGER = 'MANAGER', 'Marketing Manager'
        EDITOR = 'EDITOR', 'Marketing Executive'
        VIEWER = 'VIEWER', 'Viewer'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        SUSPENDED = 'SUSPENDED', 'Suspended'

    # Ordered least- to most-privileged. Used by the HasWorkspaceRole
    # permission to express "this role or above" without listing every role.
    ROLE_RANK = {
        Role.VIEWER: 10,
        Role.EDITOR: 20,
        Role.MANAGER: 30,
        Role.ADMIN: 40,
        Role.OWNER: 50,
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.CASCADE, related_name='members'
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='workspace_memberships')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    invited_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='invited_members'
    )
    last_active_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workspace_members'
        unique_together = ('workspace', 'user')
        indexes = [models.Index(fields=['user', 'status'])]

    def __str__(self):
        return f"{self.user} — {self.role} on {self.workspace.workspace_name}"

    @property
    def rank(self) -> int:
        return self.ROLE_RANK.get(self.role, 0)

    def has_at_least(self, role: str) -> bool:
        """True when this member's role is `role` or more privileged."""
        return self.rank >= self.ROLE_RANK.get(role, 999)
