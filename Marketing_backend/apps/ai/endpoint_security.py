"""Validation for administrator-configured AI endpoints.

Custom providers are deliberately limited to public HTTPS destinations.  The
check runs when the integration is created and again immediately before an
outbound request so a saved hostname cannot later resolve to an internal
address unnoticed.
"""
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ValidationError


def _public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not any((
        address.is_private,
        address.is_loopback,
        address.is_link_local,
        address.is_multicast,
        address.is_reserved,
        address.is_unspecified,
    ))


def validate_public_https_endpoint(value: str) -> str:
    """Return a normalized public HTTPS base URL or raise ValidationError."""
    raw = (value or '').strip()
    parsed = urlsplit(raw)
    if parsed.scheme.lower() != 'https' or not parsed.hostname:
        raise ValidationError('Enter a public HTTPS API base URL.')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError(
            'The API base URL cannot contain credentials, a query, or a fragment.'
        )

    hostname = parsed.hostname.rstrip('.').casefold()
    if hostname == 'localhost' or hostname.endswith('.localhost') or hostname.endswith('.local'):
        raise ValidationError('Private or local AI endpoints are not allowed.')

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None and not _public_address(str(literal)):
        raise ValidationError('Private or local AI endpoints are not allowed.')

    try:
        addresses = {
            row[4][0]
            for row in socket.getaddrinfo(
                hostname,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, ValueError) as exc:
        raise ValidationError('The AI endpoint hostname could not be resolved.') from exc
    if not addresses or any(not _public_address(address) for address in addresses):
        raise ValidationError('The AI endpoint must resolve only to public addresses.')

    path = parsed.path.rstrip('/')
    return urlunsplit(('https', parsed.netloc, path, '', ''))
