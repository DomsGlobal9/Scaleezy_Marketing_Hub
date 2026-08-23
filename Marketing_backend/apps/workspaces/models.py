import uuid
from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()

#: Ambiguity-free alphabet for the human-facing client code: no O/0, I/1, S/5.
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRTUVWXYZ2346789'
CODE_LENGTH = 8


def generate_client_code():
    """A short, unique, speakable client identifier, e.g. SCZ-K4M2R9TB.

    The UUID primary key is already unique, but nobody reads one out on a
    support call. This is the id a person quotes.
    """
    import secrets

    return 'SCZ-' + ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


class MarketingWorkspace(models.Model):
    """One client. The tenant boundary every other table hangs off."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        ARCHIVED = 'ARCHIVED', 'Archived'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer_id = models.CharField(max_length=255, help_text="Reference to the customer/tenant in the main system")
    #: The one id a human quotes. Unique across the platform and never reused,
    #: including by archived clients — an identifier that can be handed to a
    #: second client is not an identifier.
    client_code = models.CharField(
        max_length=32, unique=True, blank=True, db_index=True,
        help_text="Unique client identifier, e.g. SCZ-K4M2R9TB. Assigned automatically.",
    )
    workspace_name = models.CharField(max_length=255)
    timezone = models.CharField(max_length=50, default='UTC')
    default_language = models.CharField(max_length=10, default='en')

    #: Lifecycle. SUSPENDED and ARCHIVED both stop writes and stop scheduled
    #: work from firing; only ARCHIVED also tears down routing and billing.
    #: Reads stay open in both, so a client can still see their own data and
    #: Super Admin can still investigate.
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    status_reason = models.CharField(max_length=255, blank=True)
    status_changed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'marketing_workspaces'

    def __str__(self):
        return self.workspace_name

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    def save(self, *args, **kwargs):
        # Assigned here rather than as a field default so the collision retry
        # has somewhere to live. Eight characters of a 30-symbol alphabet is
        # ~6.5e11 codes; the loop is for correctness, not for load.
        if not self.client_code:
            for _ in range(10):
                candidate = generate_client_code()
                if not MarketingWorkspace.objects.filter(client_code=candidate).exists():
                    self.client_code = candidate
                    break
            else:  # pragma: no cover - astronomically unlikely
                self.client_code = f'SCZ-{uuid.uuid4().hex[:12].upper()}'
            if 'update_fields' in kwargs and kwargs['update_fields'] is not None:
                kwargs['update_fields'] = list(kwargs['update_fields']) + ['client_code']
        return super().save(*args, **kwargs)


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
