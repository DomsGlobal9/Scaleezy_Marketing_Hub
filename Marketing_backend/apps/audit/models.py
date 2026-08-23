import uuid

from django.conf import settings
from django.db import models

from apps.workspaces.models import MarketingWorkspace


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(MarketingWorkspace, on_delete=models.CASCADE, related_name='audit_logs')
    date = models.DateTimeField(auto_now_add=True)
    user = models.CharField(max_length=255)
    platform = models.CharField(max_length=100)
    account = models.CharField(max_length=255)
    action = models.CharField(max_length=255)
    previous_state = models.CharField(max_length=100, blank=True, null=True)
    next_state = models.CharField(max_length=100, blank=True, null=True)
    result = models.CharField(max_length=50) # 'Success', 'Failed'
    error = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'audit_logs'


class PlatformAdmin(models.Model):
    """Who holds Scaleezy platform authority.

    A row, deliberately separate from `is_staff` and from `WorkspaceMember`:
    the CTO review requires that platform access be impossible to obtain by
    joining a workspace, and `is_staff` is granted for Django-admin access,
    which is a different decision.

    Checked live on every request. NEVER carried in a JWT claim: access tokens
    live 60 minutes, so a claim would mean up to an hour of authority after a
    revocation — the one property a revocable capability must not have.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='platform_admin'
    )
    #: Revoked rather than deleted, so the grant history survives the revoke.
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True)

    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='platform_admin_grants',
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='platform_admin_revocations',
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'platform_admins'
        ordering = ['-granted_at']

    def __str__(self):
        return f"{self.user} ({'active' if self.is_active else 'revoked'})"


def is_platform_admin(user) -> bool:
    """Live check. One indexed lookup; never cached on the request or token."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return PlatformAdmin.objects.filter(user=user, is_active=True).exists()


class PlatformAuditLog(models.Model):
    """Append-only record of everything done with platform authority.

    Separate from `AuditLog`, which requires a workspace: a platform-admin
    grant, a provider kill switch and a plan change have no tenant, so they
    are unloggable there. This is the control that makes an unrestricted role
    acceptable, so it is written first and never updated.

    Grain is one row per platform action, with the affected ids in `detail` —
    not one row per entity touched, which would drown the log the first time
    somebody lists the portfolio.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    #: Null only when the actor's account was later deleted; the username is
    #: copied into `actor_username` so the row still names somebody.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='platform_audit_entries',
    )
    actor_username = models.CharField(max_length=255, blank=True)

    action = models.CharField(max_length=64, db_index=True)
    #: Nullable: platform-wide actions (grant, provider kill switch) have no
    #: tenant. SET_NULL rather than CASCADE — deleting a client must never
    #: erase the record of what was done to it.
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='platform_audit_entries',
    )
    #: Free-form "type:id" of what was acted on, e.g. "brand:<uuid>".
    target = models.CharField(max_length=255, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'platform_audit_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['actor', '-created_at']),
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]

    def __str__(self):
        return f"{self.action} by {self.actor_username or self.actor_id}"

    def save(self, *args, **kwargs):
        if self.pk and PlatformAuditLog.objects.filter(pk=self.pk).exists():
            # Append-only. A log that can be edited is not evidence.
            raise ValueError("PlatformAuditLog rows are immutable.")
        if self.actor_id and not self.actor_username:
            self.actor_username = str(self.actor)[:255]
        return super().save(*args, **kwargs)


def record_platform_event(*, actor, action, workspace=None, target='', detail=None,
                          request=None):
    """Write one platform audit row. Never raises.

    An audit failure must not roll back or break the action it describes — but
    it is logged loudly, because a silent gap in this table is the one thing
    that makes the unrestricted role indefensible.
    """
    import logging

    try:
        ip = None
        if request is not None:
            from apps.users.models import client_ip

            ip = client_ip(request)
        return PlatformAuditLog.objects.create(
            actor=actor if getattr(actor, 'is_authenticated', False) else None,
            actor_username=str(actor)[:255] if actor else '',
            action=action,
            workspace=workspace,
            target=str(target)[:255],
            detail=detail or {},
            ip_address=ip,
        )
    except Exception:  # pragma: no cover - defensive
        logging.getLogger(__name__).exception(
            "Failed to write platform audit row: action=%s target=%s", action, target
        )
        return None
