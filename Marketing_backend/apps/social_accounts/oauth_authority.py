"""Bind a public OAuth callback to the admin who initiated it.

The existing append-only OAuth audit stores only a digest of state. A row
lock and a separate consumption event make replay fail across web workers;
provider state/PKCE validation still runs independently in each adapter.
"""
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.db import transaction
from django.utils import timezone

from apps.workspaces.models import WorkspaceMember
from .integrations.exceptions import SocialPlatformError
from .models import SocialAccountAuditLog


def _invalid():
    return SocialPlatformError(
        'OAuth authority is absent, expired, consumed, or no longer permitted.',
        safe_message='This connection session is no longer valid. An active workspace admin must reconnect.',
        error_code='OAUTH_AUTHORITY_INVALID',
    )


def bind_authority(*, authorization_url, workspace, user, platform):
    platform = 'META' if platform in ('FACEBOOK', 'INSTAGRAM') else platform
    values = parse_qs(urlsplit(authorization_url).query).get('state', [])
    if len(values) != 1 or not values[0]:
        raise _invalid()
    return SocialAccountAuditLog.objects.create(
        workspace=workspace, user=user,
        action=SocialAccountAuditLog.Action.OAUTH_AUTHORIZATION,
        old_value=hashlib.sha256(values[0].encode()).hexdigest(),
        new_value=f'{platform}:initiated',
    )


def current_authority(authority, workspace_id):
    if authority is None or str(authority.workspace_id) != str(workspace_id):
        raise _invalid()
    membership = WorkspaceMember.objects.select_related('workspace').filter(
        user_id=authority.user_id, user__is_active=True,
        workspace_id=workspace_id, status=WorkspaceMember.Status.ACTIVE,
        role__in=[WorkspaceMember.Role.ADMIN, WorkspaceMember.Role.OWNER],
    ).first()
    if membership is None or not membership.workspace.is_active:
        raise _invalid()
    return membership.workspace


@transaction.atomic
def consume_authority(*, state, platform):
    # Facebook and Instagram intentionally share the same Meta callback.
    platform = 'META' if platform in ('FACEBOOK', 'INSTAGRAM') else platform
    if not isinstance(state, str) or not state or len(state) > 2048:
        raise _invalid()
    digest = hashlib.sha256(state.encode()).hexdigest()
    authority = SocialAccountAuditLog.objects.select_for_update().filter(
        action=SocialAccountAuditLog.Action.OAUTH_AUTHORIZATION,
        old_value=digest, new_value=f'{platform}:initiated',
        created_at__gte=timezone.now() - timedelta(minutes=15),
    ).first()
    if authority is None or SocialAccountAuditLog.objects.filter(
        action=SocialAccountAuditLog.Action.OAUTH_AUTHORIZATION,
        old_value=digest, new_value=f'{platform}:consumed',
    ).exists():
        raise _invalid()
    current_authority(authority, authority.workspace_id)
    SocialAccountAuditLog.objects.create(
        workspace_id=authority.workspace_id, user_id=authority.user_id,
        action=SocialAccountAuditLog.Action.OAUTH_AUTHORIZATION,
        old_value=digest, new_value=f'{platform}:consumed',
    )
    return authority
