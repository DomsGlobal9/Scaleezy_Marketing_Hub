"""
Granting and revoking platform authority.

There is one platform role and it is unrestricted, so *granting* it is the
security event — not using it. Both operations therefore live in one audited
service that the console, the management command and any future SSO
provisioning all call, rather than three places that can drift.
"""
import logging

from django.db import transaction
from django.utils import timezone

from .models import PlatformAdmin, record_platform_event

logger = logging.getLogger(__name__)


class PlatformAdminError(Exception):
    """The requested grant or revocation is not allowed."""


@transaction.atomic
def grant_platform_admin(user, *, by=None, note='', request=None):
    """Give `user` platform authority. Idempotent.

    `by=None` is the bootstrap case (the management command), which is the
    only way the first admin can exist. Every other grant carries an actor.
    """
    grant, created = PlatformAdmin.objects.get_or_create(
        user=user, defaults={'note': note, 'granted_by': by}
    )
    if not created and grant.is_active:
        return grant, False

    grant.is_active = True
    grant.revoked_at = None
    grant.revoked_by = None
    grant.granted_by = by
    if note:
        grant.note = note
    grant.save(update_fields=[
        'is_active', 'revoked_at', 'revoked_by', 'granted_by', 'note',
    ])
    record_platform_event(
        actor=by, action='PLATFORM_ADMIN_GRANTED', target=f'user:{user.pk}',
        detail={'username': user.get_username(), 'note': note,
                'bootstrap': by is None},
        request=request,
    )
    logger.warning(
        "Platform admin GRANTED to %s by %s", user.get_username(), by or 'bootstrap'
    )
    return grant, True


@transaction.atomic
def revoke_platform_admin(user, *, by=None, request=None):
    """Take platform authority away. Takes effect on the next request.

    The grant row is kept and flagged, never deleted: the history of who held
    this and when is the point of the table.

    Refuses to remove the last active admin — a platform with nobody able to
    approve a client, and no console route to grant the role back, can only be
    repaired from a shell.
    """
    grant = PlatformAdmin.objects.filter(user=user, is_active=True).first()
    if grant is None:
        return None, False

    if PlatformAdmin.objects.filter(is_active=True).count() <= 1:
        raise PlatformAdminError(
            "This is the last platform admin. Grant the role to somebody else first."
        )

    grant.is_active = False
    grant.revoked_at = timezone.now()
    grant.revoked_by = by
    grant.save(update_fields=['is_active', 'revoked_at', 'revoked_by'])
    record_platform_event(
        actor=by, action='PLATFORM_ADMIN_REVOKED', target=f'user:{user.pk}',
        detail={'username': user.get_username()},
        request=request,
    )
    logger.warning(
        "Platform admin REVOKED from %s by %s", user.get_username(), by or 'bootstrap'
    )
    return grant, True
