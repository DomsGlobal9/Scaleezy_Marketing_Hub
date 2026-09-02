"""
Wire shapes for the universal layer.

Plain functions rather than DRF serializers: the rows are read and written
through the services in `apps.universal.services`, and the only thing a view
needs is a JSON-safe dict. One place defines the shape so the platform console
and the client library cannot drift apart — the client just never sees who
curated a reference, which is platform-side provenance, not client
information.
"""
from .services import adoption_count


def _iso(value):
    return value.isoformat() if value else None


def standard_payload(standard):
    """One `UniversalStandard`, every field the console edits or shows."""
    return {
        'id': str(standard.pk),
        'title': standard.title,
        'rationale': standard.rationale,
        'category': standard.category,
        'attribute': standard.attribute,
        'value': standard.value,
        'guidance': standard.guidance,
        'scope': standard.scope,
        'scope_value': standard.scope_value,
        'status': standard.status,
        'published_at': _iso(standard.published_at),
        'retired_at': _iso(standard.retired_at),
        'authored_by': (
            standard.authored_by.get_username() if standard.authored_by_id else ''
        ),
        'supersedes': str(standard.supersedes_id) if standard.supersedes_id else None,
        'created_at': _iso(standard.created_at),
    }


def inspiration_payload(inspiration, *, include_curator=True, adoptions=None):
    """One `PlatformInspiration`. `adoption_count` is a live query, never a
    stored counter, so it is exactly as current as the brands' own rows.

    `adoptions` is that same number precomputed (services.adoption_counts) so
    a listing pays one grouped query, not one COUNT per row. None — not 0 —
    means "not precomputed, query it here"."""
    payload = {
        'id': str(inspiration.pk),
        'title': inspiration.title,
        'kind': inspiration.kind,
        'reference_url': inspiration.reference_url,
        'body': inspiration.body,
        # The storage path stays server-side: a client renders the public URL
        # and nothing else needs the bucket coordinates.
        'file_url': inspiration.file_url,
        'mime_type': inspiration.mime_type,
        'file_name': inspiration.file_name,
        'annotation': inspiration.annotation,
        'tags': list(inspiration.tags or []),
        'industry': inspiration.industry,
        'channel': inspiration.channel,
        'status': inspiration.status,
        'published_at': _iso(inspiration.published_at),
        'adoption_count': adoption_count(inspiration) if adoptions is None else adoptions,
        'created_at': _iso(inspiration.created_at),
    }
    if include_curator:
        payload['curated_by'] = (
            inspiration.curated_by.get_username() if inspiration.curated_by_id else ''
        )
    return payload
