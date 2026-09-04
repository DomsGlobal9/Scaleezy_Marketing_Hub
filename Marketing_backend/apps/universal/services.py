"""
Compiling the universal layer, and adopting a platform inspiration.

The one rule everything here serves: universal intelligence is the weakest
thing in the room. It fills gaps a brand has not spoken about, and it loses
every argument with something the brand stated, confirmed, or was learned from
its own behaviour.

That is enforced structurally rather than by convention — `standards_for()`
drops any standard whose (category, attribute) the brand already has a claim
about, so a universal standard never even reaches the resolver as a rival to
brand-specific intelligence.
"""
import hashlib
import json
import logging

from django.db import transaction
from django.utils import timezone

from .models import (
    RANK_LEARNED_PATTERN,
    RANK_PLATFORM_INSPIRATION,
    UPLOAD_KINDS,
    ClientQualitySettings,
    ClientUniversalSettings,
    EntryKind,
    LearnedPattern,
    LifecycleStatus,
    PlatformInspiration,
    UniversalStandard,
    universal_version,
)

logger = logging.getLogger(__name__)


class UniversalError(Exception):
    """The requested authoring action is not allowed."""


# ─────────────────────────────────────────────────────── client preferences

def settings_for(workspace):
    """This client's universal-layer switches. Never creates a row on read."""
    return (
        ClientUniversalSettings.objects.filter(workspace=workspace).first()
        or ClientUniversalSettings(workspace=workspace)
    )


def set_client_universal(workspace, *, standards=None, inspirations=None, by=None):
    """Turn the universal layer on or off for one client. Audited."""
    from apps.audit.models import record_platform_event

    row, _ = ClientUniversalSettings.objects.get_or_create(workspace=workspace)
    before = {'standards': row.standards_enabled, 'inspirations': row.inspirations_enabled}
    if standards is not None:
        row.standards_enabled = bool(standards)
    if inspirations is not None:
        row.inspirations_enabled = bool(inspirations)
    row.save(update_fields=['standards_enabled', 'inspirations_enabled', 'updated_at'])

    record_platform_event(
        actor=by, action='CLIENT_UNIVERSAL_TOGGLED', workspace=workspace,
        target=f'workspace:{workspace.pk}',
        detail={'before': before, 'after': {
            'standards': row.standards_enabled,
            'inspirations': row.inspirations_enabled,
        }},
    )
    return row


def quality_settings_for(workspace):
    """This client's quality-engine switches. Never creates a row on read."""
    return (
        ClientQualitySettings.objects.filter(workspace=workspace).first()
        or ClientQualitySettings(workspace=workspace)
    )


def set_client_quality(workspace, *, critique_enabled=None, focus_crop_enabled=None,
                       variety_enabled=None, by=None):
    """Turn quality-engine passes on or off for one client. Audited."""
    from apps.audit.models import record_platform_event

    row, _ = ClientQualitySettings.objects.get_or_create(workspace=workspace)
    before = {
        'critique': row.critique_enabled,
        'focus_crop': row.focus_crop_enabled,
        'variety': row.variety_enabled,
    }
    if critique_enabled is not None:
        row.critique_enabled = bool(critique_enabled)
    if focus_crop_enabled is not None:
        row.focus_crop_enabled = bool(focus_crop_enabled)
    if variety_enabled is not None:
        row.variety_enabled = bool(variety_enabled)
    row.save(update_fields=[
        'critique_enabled', 'focus_crop_enabled', 'variety_enabled', 'updated_at',
    ])

    record_platform_event(
        actor=by, action='CLIENT_QUALITY_TOGGLED', workspace=workspace,
        target=f'workspace:{workspace.pk}',
        detail={'before': before, 'after': {
            'critique': row.critique_enabled,
            'focus_crop': row.focus_crop_enabled,
            'variety': row.variety_enabled,
        }},
    )
    return row


# ──────────────────────────────────────────────────────────── the standards

def brand_claimed_keys(brand):
    """(category, attribute) pairs the brand already has a position on.

    Read from the compiled brain rather than from the source tables: the brain
    is what a generation actually reads, so it is the honest definition of
    "this brand has already spoken about that".
    """
    brain = brand.creative_brain or {}
    keys = set()
    for claim in brain.get('preferences', []) or []:
        category = str(claim.get('category', '')).strip().casefold()
        attribute = str(claim.get('attribute', '')).strip().casefold()
        if category and attribute:
            keys.add((category, attribute))
    return keys


def live_standards(brand=None, *, channel='', content_type=''):
    """Published standards in scope, cheapest possible query."""
    rows = UniversalStandard.objects.filter(status=LifecycleStatus.PUBLISHED)
    if brand is None:
        return list(rows)
    return [
        s for s in rows
        if s.applies_to(brand, channel=channel, content_type=content_type)
    ]


def standards_for(workspace, brand, *, channel='', content_type='',
                  content_format_or_type=''):
    """The standards one generation should carry, already filtered.

    Returns (standards, version). Empty when the client opted out — and the
    version changes with it, so switching the layer off invalidates their
    cached context instead of serving the old cut.
    """
    if not settings_for(workspace).standards_enabled:
        return [], 'off'

    in_scope = live_standards(
        brand, channel=channel,
        content_type=content_type or content_format_or_type,
    )

    # The structural guarantee: a standard about something the brand has
    # already spoken about is dropped here, before precedence is ever
    # consulted. Nothing weaker can then be mistaken for a rival to the
    # brand's own position.
    owned = brand_claimed_keys(brand)
    kept = [
        s for s in in_scope
        if (s.category.strip().casefold(), s.attribute.strip().casefold()) not in owned
    ]
    return kept, universal_version(kept)


def standards_as_context(standards):
    """The attributable shape a brief carries.

    Every entry names its origin, so a client can always see that a suggestion
    came from platform-wide craft rather than from their own brand.
    """
    return [
        {
            'guidance': s.guidance,
            'category': s.category,
            'attribute': s.attribute,
            'value': s.value,
            'authority': 'universal_standard',
            'rank': s.as_claim()['rank'],
            'source': 'Scaleezy craft standard',
            'standard_id': str(s.pk),
            'title': s.title,
        }
        for s in standards
    ]


# ───────────────────────────────────────────────────── learned patterns

def live_patterns(brand, *, channel=''):
    return [
        pattern
        for pattern in LearnedPattern.objects.filter(status=LifecycleStatus.PUBLISHED)
        if pattern.applies_to(brand, channel=channel)
    ]


def learned_pattern_version(patterns):
    payload = json.dumps(
        sorted([
            [str(p.pk), p.pattern_version, p.category, p.attribute, p.value]
            for p in patterns
        ]),
        separators=(',', ':'),
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


def patterns_for(workspace, brand, *, channel=''):
    """Published patterns for a generation; there is deliberately no opt-out."""
    owned = brand_claimed_keys(brand)
    kept = [
        pattern for pattern in live_patterns(brand, channel=channel)
        if (
            pattern.category.strip().casefold(),
            pattern.attribute.strip().casefold(),
        ) not in owned
    ]
    return kept, learned_pattern_version(kept)


def patterns_as_context(patterns):
    """Provider-safe claim shape; contributor identities never leave platform APIs."""
    return [
        {
            'category': p.category,
            'attribute': p.attribute,
            'value': p.value,
            'authority': 'learned_pattern',
            'rank': RANK_LEARNED_PATTERN,
            'source': 'Learned across Scaleezy clients',
            'pattern_id': str(p.pk),
            'contributor_count': p.contributor_count,
            'supporting_brand_count': p.supporting_brand_count,
        }
        for p in patterns
    ]


@transaction.atomic
def publish_pattern(pattern, *, by=None):
    if pattern.status == LifecycleStatus.PUBLISHED:
        return pattern
    pattern.status = LifecycleStatus.PUBLISHED
    pattern.published_at = timezone.now()
    pattern.retired_at = None
    pattern.save(update_fields=['status', 'published_at', 'retired_at', 'updated_at'])
    from apps.audit.models import record_platform_event
    record_platform_event(
        actor=by, action='LEARNED_PATTERN_PUBLISHED',
        target=f'pattern:{pattern.pk}',
        detail={'pattern_version': pattern.pattern_version,
                'contributor_count': pattern.contributor_count},
    )
    return pattern


@transaction.atomic
def retire_pattern(pattern, *, by=None, reason=''):
    if pattern.status == LifecycleStatus.RETIRED:
        return pattern
    pattern.status = LifecycleStatus.RETIRED
    pattern.retired_at = timezone.now()
    pattern.save(update_fields=['status', 'retired_at', 'updated_at'])
    from apps.audit.models import record_platform_event
    record_platform_event(
        actor=by, action='LEARNED_PATTERN_RETIRED',
        target=f'pattern:{pattern.pk}',
        detail={'pattern_version': pattern.pattern_version, 'reason': reason},
    )
    return pattern


# ───────────────────────────────────────────────────────────── authoring

@transaction.atomic
def publish_standard(standard, *, by=None):
    """DRAFT/RETIRED -> PUBLISHED. Retires whatever it supersedes."""
    if standard.status == LifecycleStatus.PUBLISHED:
        return standard
    standard.status = LifecycleStatus.PUBLISHED
    standard.published_at = timezone.now()
    standard.retired_at = None
    standard.save(update_fields=['status', 'published_at', 'retired_at', 'updated_at'])

    if standard.supersedes_id and standard.supersedes.status == LifecycleStatus.PUBLISHED:
        retire_standard(standard.supersedes, by=by, reason=f'superseded by {standard.pk}')

    from apps.audit.models import record_platform_event

    record_platform_event(
        actor=by, action='UNIVERSAL_STANDARD_PUBLISHED',
        target=f'standard:{standard.pk}',
        detail={'title': standard.title, 'category': standard.category,
                'attribute': standard.attribute, 'scope': standard.scope},
    )
    return standard


@transaction.atomic
def retire_standard(standard, *, by=None, reason=''):
    """PUBLISHED -> RETIRED. Stops reaching generations on the next request.

    Retire rather than delete: a generation trace that names this standard has
    to stay explainable after the fact.
    """
    if standard.status == LifecycleStatus.RETIRED:
        return standard
    standard.status = LifecycleStatus.RETIRED
    standard.retired_at = timezone.now()
    standard.save(update_fields=['status', 'retired_at', 'updated_at'])

    from apps.audit.models import record_platform_event

    record_platform_event(
        actor=by, action='UNIVERSAL_STANDARD_RETIRED',
        target=f'standard:{standard.pk}',
        detail={'title': standard.title, 'reason': reason},
    )
    return standard


def preview_affected(standard):
    """Which clients a standard would touch, before it is published.

    Honest about its own limits: for an INDUSTRY-scoped standard this matches
    `Brand.industry`, which is free text, so the count is "brands whose
    industry string matches exactly", not "brands in that industry". Stated in
    the payload rather than presented as certainty.
    """
    from apps.brands.models import Brand

    candidates = Brand.objects.filter(status=Brand.Status.ACTIVE).only(
        'id', 'name', 'industry', 'workspace_id'
    )
    matched = [b for b in candidates if standard.applies_to(b)]
    return {
        'matched_brand_count': len(matched),
        'total_active_brands': candidates.count(),
        'brands': [
            {'id': str(b.pk), 'name': b.name, 'industry': b.industry}
            for b in matched[:50]
        ],
        'exact_match_only': standard.scope != 'GLOBAL',
        'note': (
            ''
            if standard.scope == 'GLOBAL'
            else 'Industry is free text, so this matches the string exactly.'
        ),
    }


# ─────────────────────────────────────────────────── platform inspirations

@transaction.atomic
def publish_inspiration(inspiration, *, by=None):
    if inspiration.status == LifecycleStatus.PUBLISHED:
        return inspiration
    inspiration.status = LifecycleStatus.PUBLISHED
    inspiration.published_at = timezone.now()
    inspiration.save(update_fields=['status', 'published_at', 'updated_at'])

    from apps.audit.models import record_platform_event

    record_platform_event(
        actor=by, action='PLATFORM_INSPIRATION_PUBLISHED',
        target=f'inspiration:{inspiration.pk}',
        detail={'title': inspiration.title, 'kind': inspiration.kind,
                'url': inspiration.reference_url, 'file_name': inspiration.file_name},
    )
    return inspiration


def gallery_for(workspace, *, industry='', kind='', limit=50, offset=0):
    """What a client may browse. Empty when they opted out."""
    if not settings_for(workspace).inspirations_enabled:
        return []
    rows = PlatformInspiration.objects.filter(status=LifecycleStatus.PUBLISHED)
    if industry:
        rows = rows.filter(industry__iexact=industry)
    if kind:
        rows = rows.filter(kind=str(kind).upper())
    safe_offset = max(0, int(offset or 0))
    safe_limit = max(1, min(int(limit or 50), 101))
    return list(rows[safe_offset:safe_offset + safe_limit])


def _adopted_fields(platform_inspiration):
    """How each kind of library entry lands in a brand's own inspirations.

    A LINK stays a general reference to the URL. An upload becomes an
    inspiration of the matching type that points at the platform-hosted file
    — the brand row carries the public URL only, not the storage path, because
    the object is the platform's and must not look like the brand's to delete.
    A TEXT entry has no pointer at all: its words go into the annotation, with
    the team's note after them, so the client reads both where they read
    everything else.
    """
    from apps.inspirations.models import BrandInspiration

    kind = platform_inspiration.kind
    Type = BrandInspiration.InspirationType
    fields = {
        'inspiration_type': {
            EntryKind.IMAGE: Type.IMAGE,
            EntryKind.VIDEO: Type.VIDEO,
            EntryKind.TEXT: Type.TEXT,
        }.get(kind, Type.REFERENCE),
        'reference_url': platform_inspiration.reference_url or None,
        'annotation': platform_inspiration.annotation,
    }
    if kind in UPLOAD_KINDS:
        fields.update(
            file_url=platform_inspiration.file_url or None,
            mime_type=platform_inspiration.mime_type or None,
            file_name=platform_inspiration.file_name or None,
        )
    elif kind == EntryKind.TEXT:
        fields['annotation'] = '\n\n'.join(
            part for part in (platform_inspiration.body, platform_inspiration.annotation)
            if part
        )
    return fields


@transaction.atomic
def adopt_inspiration(platform_inspiration, brand, *, user=None):
    """Copy a curated reference into the client's own inspirations.

    Adopt, never push. A platform reference becomes part of a brand's
    intelligence only when somebody at that brand chooses it, and what is
    copied is the pointer (or the words) and the annotation — the brand's own
    `BrandInspiration` row then behaves exactly like one they added
    themselves, including its authority rank.

    Provenance is recorded so the client can always see it came from
    Scaleezy's library rather than from their own research.
    """
    from apps.inspirations.models import BrandInspiration

    if platform_inspiration.status != LifecycleStatus.PUBLISHED:
        raise UniversalError("That reference is not published.")

    # Adopting twice is a no-op whatever the kind; and a link the brand already
    # keeps on its own is not added a second time either.
    existing = BrandInspiration.objects.filter(
        brand=brand, metadata__platform_inspiration_id=str(platform_inspiration.pk)
    ).first()
    if existing is None and platform_inspiration.kind == EntryKind.LINK:
        existing = BrandInspiration.objects.filter(
            brand=brand, reference_url=platform_inspiration.reference_url
        ).first()
    if existing is not None:
        return existing, False

    adopted = BrandInspiration.objects.create(
        workspace=brand.workspace,
        brand=brand,
        title=platform_inspiration.title[:255],
        metadata={
            'adopted_from_platform': True,
            'platform_inspiration_id': str(platform_inspiration.pk),
            'platform_kind': platform_inspiration.kind,
            'adopted_at': timezone.now().isoformat(),
            'authority_note': (
                'Adopted from the Scaleezy library; treated as this brand\'s '
                'own inspiration from here on.'
            ),
        },
        created_by=user,
        **_adopted_fields(platform_inspiration),
    )
    logger.info(
        "Brand %s adopted platform inspiration %s", brand.pk, platform_inspiration.pk
    )
    return adopted, True


def adoption_count(platform_inspiration) -> int:
    """How many brands took it. A real query, never a stored counter."""
    from apps.inspirations.models import BrandInspiration

    return BrandInspiration.objects.filter(
        metadata__platform_inspiration_id=str(platform_inspiration.pk)
    ).count()


def adoption_counts(platform_inspirations) -> dict:
    """`adoption_count` for a whole page in ONE grouped query.

    Returns {str(pk): count}; an entry nobody adopted is simply absent, so
    callers read it with `.get(..., 0)`. Same live rows as `adoption_count`,
    grouped instead of counted one COUNT(*) per entry.
    """
    from django.db.models import Count

    from apps.inspirations.models import BrandInspiration

    ids = [str(entry.pk) for entry in platform_inspirations]
    if not ids:
        return {}
    return {
        row['metadata__platform_inspiration_id']: row['n']
        for row in (
            BrandInspiration.objects
            .filter(metadata__platform_inspiration_id__in=ids)
            .values('metadata__platform_inspiration_id')
            .annotate(n=Count('id'))
        )
    }
