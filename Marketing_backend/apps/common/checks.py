"""
Deployment safety checks.

Surfaced by `manage.py check --deploy`, so misconfiguration fails a CI gate
instead of shipping.
"""
import sys

from django.conf import settings
from django.core.checks import Error, Warning, register

# HS256 signs with the raw key; RFC 7518 §3.2 requires at least the hash output
# size (32 bytes for SHA-256).
MIN_SIGNING_KEY_BYTES = 32


def _running_tests() -> bool:
    """
    True while the test runner is active.

    The runner forces settings.DEBUG = False *after* settings are imported, so
    any check comparing DEBUG against a value computed at import time (such as
    CORS_ALLOW_ALL_ORIGINS) would otherwise report a false positive.
    """
    return 'test' in sys.argv or 'pytest' in sys.modules


@register('security')
def check_secret_key_strength(app_configs, **kwargs):
    """SECRET_KEY doubles as the JWT signing key, so a short one weakens auth."""
    if _running_tests():
        return []
    issues = []
    key = settings.SECRET_KEY or ''
    length = len(key.encode('utf-8'))

    if length < MIN_SIGNING_KEY_BYTES:
        message = (
            f"SECRET_KEY is {length} bytes; JWTs are signed with HS256 which "
            f"requires at least {MIN_SIGNING_KEY_BYTES} bytes."
        )
        hint = (
            "Set DJANGO_SECRET_KEY to a long random value, e.g. "
            "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )
        # Only fatal in production — a short dev key must not block local work.
        issues.append(
            Error(message, hint=hint, id='security.E101')
            if not settings.DEBUG
            else Warning(message, hint=hint, id='security.W101')
        )

    if 'insecure' in key.lower() or key.startswith('dev_'):
        issues.append(
            Warning(
                "SECRET_KEY looks like a development placeholder.",
                hint="Generate a unique key for every deployed environment.",
                id='security.W102',
            )
        )
    return issues


@register('security')
def check_cors_not_open_in_production(app_configs, **kwargs):
    """An open CORS policy in front of encrypted OAuth tokens is unacceptable."""
    if _running_tests():
        return []
    if settings.DEBUG:
        return []
    if getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False):
        return [
            Error(
                "CORS_ALLOW_ALL_ORIGINS is enabled outside DEBUG.",
                hint="Set CORS_ALLOWED_ORIGINS to an explicit comma-separated allowlist.",
                id='security.E103',
            )
        ]
    return []


@register('security')
def check_token_encryption_key(app_configs, **kwargs):
    """Without FERNET_SECRET_KEY, stored OAuth tokens cannot be read or written."""
    if _running_tests():
        return []
    import os

    if not os.environ.get('FERNET_SECRET_KEY'):
        return [
            Error(
                "FERNET_SECRET_KEY is not set; social account tokens cannot be "
                "encrypted or decrypted.",
                hint="Generate one with: python -c \"from cryptography.fernet import "
                "Fernet; print(Fernet.generate_key().decode())\"",
                id='security.E104',
            )
        ]
    return []
