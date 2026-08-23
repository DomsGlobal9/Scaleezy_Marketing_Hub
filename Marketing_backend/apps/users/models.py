import uuid

from django.conf import settings
from django.db import models


class AuthAuditLog(models.Model):
    """
    Authentication event trail.

    Kept separate from apps.audit.AuditLog because that model requires a
    workspace, and auth events are cross-workspace by nature — a failed login
    has neither a workspace nor, necessarily, a known user.
    """

    class Event(models.TextChoices):
        LOGIN_SUCCESS = 'LOGIN_SUCCESS', 'Login succeeded'
        LOGIN_FAILED = 'LOGIN_FAILED', 'Login failed'
        TOKEN_REFRESH = 'TOKEN_REFRESH', 'Token refreshed'
        TOKEN_REFRESH_FAILED = 'TOKEN_REFRESH_FAILED', 'Token refresh failed'
        LOGOUT = 'LOGOUT', 'Logged out'
        ACCESS_DENIED = 'ACCESS_DENIED', 'Access denied'
        SIGNUP = 'SIGNUP', 'Signed up'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Null when the login attempt used an address with no matching account.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='auth_audit_logs',
    )
    # Always recorded, so failed attempts on unknown accounts are still traceable.
    attempted_username = models.CharField(max_length=255, blank=True)

    event = models.CharField(max_length=32, choices=Event.choices)
    succeeded = models.BooleanField(default=True)
    reason = models.CharField(max_length=255, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'auth_audit_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['event', '-created_at']),
        ]

    def __str__(self):
        who = self.user or self.attempted_username or 'anonymous'
        return f"{self.event} — {who} @ {self.created_at:%Y-%m-%d %H:%M:%S}"


class SignupWebsiteClaim(models.Model):
    """One company, one enrolment — enforced by the database.

    The signup serializer refuses a website that already belongs to a client,
    but two simultaneous signups can both pass that read before either
    writes. This row is created inside the signup transaction with a UNIQUE
    host, so the second of two racing signups fails at commit and is told so.

    Released when the signup is rejected or the client archived, so a dead
    enrolment never blocks a real one. Kept as its own table rather than a
    unique index on Brand.website so that pre-existing brands sharing a site
    (two brands of one company, test data) never break a migration.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    #: Registrable host, lowercase, no leading www. — see users.serializers.normalised_host
    website_host = models.CharField(max_length=253, unique=True)
    workspace = models.ForeignKey(
        'workspaces.MarketingWorkspace', on_delete=models.CASCADE,
        related_name='signup_website_claims',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'signup_website_claims'

    def __str__(self):
        return f"{self.website_host} -> {self.workspace_id}"


def client_ip(request):
    """Client IP, honouring one level of proxy via X-Forwarded-For."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def record_auth_event(request, event, *, user=None, username='', succeeded=True, reason=''):
    """
    Writes an auth audit row. Never raises — an audit failure must not block or
    break the request it is describing.
    """
    try:
        return AuthAuditLog.objects.create(
            user=user if getattr(user, 'is_authenticated', False) else None,
            attempted_username=(username or '')[:255],
            event=event,
            succeeded=succeeded,
            reason=(reason or '')[:255],
            ip_address=client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:1000],
        )
    except Exception:  # pragma: no cover - defensive
        import logging

        logging.getLogger(__name__).exception("Failed to write auth audit log")
        return None
