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
import logging

from django.db import transaction
from django.utils import timezone

from .models import (
    RANK_PLATFORM_INSPIRATION,
    ClientUniversalSettings,
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
        detail={'title': inspiration.title, 'url': inspiration.reference_url},
    )
    return inspiration


def gallery_for(workspace, *, industry='', limit=50):
    """What a client may browse. Empty when they opted out."""
    if not settings_for(workspace).inspirations_enabled:
        return []
    rows = PlatformInspiration.objects.filter(status=LifecycleStatus.PUBLISHED)
    if industry:
        rows = rows.filter(industry__iexact=industry)
    return list(rows[:limit])


@transaction.atomic
def adopt_inspiration(platform_inspiration, brand, *, user=None):
    """Copy a curated reference into the client's own inspirations.

    Adopt, never push. A platform reference becomes part of a brand's
    intelligence only when somebody at that brand chooses it, and what is
    copied is the pointer and the annotation — the brand's own
    `BrandInspiration` row then behaves exactly like one they added
    themselves, including its authority rank.

    Provenance is recorded so the client can always see it came from
    Scaleezy's library rather than from their own research.
    """
    from apps.inspirations.models import BrandInspiration

    if platform_inspiration.status != LifecycleStatus.PUBLISHED:
        raise UniversalError("That reference is not published.")

    existing = BrandInspiration.objects.filter(
        brand=brand, reference_url=platform_inspiration.reference_url
    ).first()
    if existing is not None:
        return existing, False

    adopted = BrandInspiration.objects.create(
        workspace=brand.workspace,
        brand=brand,
        inspiration_type=BrandInspiration.InspirationType.REFERENCE,
        title=platform_inspiration.title[:255],
        reference_url=platform_inspiration.reference_url,
        annotation=platform_inspiration.annotation,
        metadata={
            'adopted_from_platform': True,
            'platform_inspiration_id': str(platform_inspiration.pk),
            'adopted_at': timezone.now().isoformat(),
            'authority_note': (
                'Adopted from the Scaleezy library; treated as this brand\'s '
                'own inspiration from here on.'
            ),
        },
        created_by=user,
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
