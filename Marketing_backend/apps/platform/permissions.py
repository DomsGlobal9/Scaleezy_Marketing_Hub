"""
The platform boundary.

One permission class, one rule: the caller holds an active `PlatformAdmin`
row, checked against the database on every request. Never derived from
`is_staff`, never from any workspace membership, never from a token claim.

This is deliberately NOT a mode on `IsWorkspaceMember` or
`WorkspaceScopedMixin`. Those keep behaving exactly as they do today for
every customer request; platform authority lives in its own namespace with
its own gate, so the two can never be confused for each other.
"""
from rest_framework.permissions import BasePermission

from apps.audit.models import is_platform_admin


class IsPlatformAdmin(BasePermission):
    message = "Scaleezy platform authority is required."

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated and is_platform_admin(user))

    def has_object_permission(self, request, view, obj):
        # Platform authority is unrestricted by design; there is no per-object
        # narrowing to apply. Every action is audited instead.
        return True
