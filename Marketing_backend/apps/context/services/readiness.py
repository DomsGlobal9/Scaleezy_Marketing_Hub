"""
Brand readiness.

Answers one question a user actually asks: "how well does Scaleezy understand
this brand yet?" Arithmetic, not a model — a score that an LLM invented would
move when nothing about the brand had changed, and nobody could tell you why
it dropped.

Deliberately hard to score highly. A brand row with a name in it is 15% of the
picture, and showing that as anywhere near ready is how a product talks a user
out of the work that actually makes it good.
"""
from django.db.models import CharField, Count, Value

from apps.brands.services.brand_brain import compile_brand_brain
from apps.inspirations.models import BrandInspiration, InspirationSignal
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import BrandPreference, BrandRule

LEVEL_STARTING = 'STARTING'
LEVEL_LEARNING = 'LEARNING'
LEVEL_STRONG = 'STRONG'
LEVEL_READY = 'READY'


def _ratio(count, full_at):
    """0.0 to 1.0, reaching 1.0 at `full_at` items."""
    if full_at <= 0:
        return 1.0
    return min(1.0, count / full_at)


def _filled(*values):
    return sum(1 for value in values if value)


def _count_row(queryset, key):
    """One labelled aggregate that can be UNIONed with other model counts."""
    return (
        queryset.order_by()
        .annotate(_readiness_key=Value(key, output_field=CharField(max_length=32)))
        .values('_readiness_key')
        .annotate(_readiness_count=Count('pk'))
        .values('_readiness_key', '_readiness_count')
    )


def _readiness_counts(querysets):
    """Evaluate all evidence counts in one database round trip.

    Each input is still the established eligibility queryset for its module;
    UNION ALL only combines their scalar results. Missing evidence therefore
    stays zero without weakening provenance or lifecycle filters.
    """
    counts = {key: 0 for key, _queryset in querysets}
    count_rows = [_count_row(queryset, key) for key, queryset in querysets]
    rows = count_rows[0].union(*count_rows[1:], all=True)
    # A combined queryset retains the first model's metadata. Order by a
    # projected union column so no model-level default ordering leaks into the
    # compound SELECT (SQLite rejects such hidden terms; PostgreSQL needlessly
    # sorts them).
    for row in rows.order_by('_readiness_key'):
        counts[row['_readiness_key']] = row['_readiness_count']
    return counts


def brand_readiness(brand, *, brain=None):
    """Deterministic completeness score for one brand.

    Returns the score, the level, which dimensions are done, which are not,
    and the single most useful thing to do next.
    """
    brain = brain if brain is not None else (brand.creative_brain or compile_brand_brain(brand))

    sources = BrandSource.objects.filter(brand=brand).exclude(
        status=BrandSource.SourceStatus.ARCHIVED
    )
    memories = BrandMemory.objects.filter(
        brand=brand, status=BrandMemory.MemoryStatus.CONFIRMED
    ).exclude(source__status=BrandSource.SourceStatus.ARCHIVED)
    inspirations = BrandInspiration.objects.filter(brand=brand).eligible_for_retrieval()
    signals = InspirationSignal.objects.filter(
        inspiration__brand=brand
    ).eligible_for_retrieval()
    preferences = BrandPreference.objects.filter(brand=brand).active()
    rules = BrandRule.objects.filter(brand=brand, is_active=True)
    counts = _readiness_counts((
        ('sources', sources),
        ('memories', memories),
        ('inspirations', inspirations),
        ('inspiration_signals', signals),
        ('preferences', preferences),
        ('rules', rules),
    ))

    visual = brain.get('visual_language', {})
    voice = brain.get('voice', {})
    positioning = brain.get('positioning', {})
    audiences = brain.get('audiences', {})

    dimensions = [
        {
            'key': 'identity',
            'label': 'Brand identity',
            'weight': 15,
            'score': _filled(
                brand.name, brand.industry, brand.tagline, brand.logo_url,
                brand.cta_keyword,
            ) / 5,
            'hint': 'Add your industry, tagline and logo.',
        },
        {
            'key': 'knowledge',
            'label': 'Brand knowledge',
            'weight': 20,
            'score': (
                _ratio(counts['sources'], 2) * 0.4
                + _ratio(counts['memories'], 5) * 0.6
            ),
            'hint': 'Upload a brand document, deck or transcript.',
        },
        {
            'key': 'voice',
            'label': 'Voice',
            'weight': 15,
            'score': (
                (1.0 if brand.brand_tone else 0.0) * 0.5
                + _ratio(len(voice.get('claims', [])), 3) * 0.5
            ),
            'hint': 'Describe the brand tone and confirm a few voice preferences.',
        },
        {
            'key': 'visual_language',
            'label': 'Visual language',
            'weight': 15,
            'score': (
                (1.0 if brand.logo_url else 0.0) * 0.3
                + _ratio(len(visual.get('claims', [])), 4) * 0.7
            ),
            'hint': 'Teach Scaleezy your visual taste with a few inspirations.',
        },
        {
            'key': 'positioning',
            'label': 'Audience and positioning',
            'weight': 15,
            'score': (
                _ratio(len(positioning.get('statements', [])), 2) * 0.5
                + _ratio(
                    len(audiences.get('pains', [])) + len(audiences.get('objections', [])),
                    3,
                ) * 0.5
            ),
            'hint': 'Add positioning notes and who you are selling to.',
        },
        {
            'key': 'inspirations',
            'label': 'Inspirations',
            'weight': 10,
            'score': (
                _ratio(counts['inspirations'], 3) * 0.5
                + _ratio(counts['inspiration_signals'], 5) * 0.5
            ),
            'hint': 'Add references and say what you like about them.',
        },
        {
            'key': 'learning',
            'label': 'Learning',
            'weight': 10,
            'score': (
                _ratio(counts['preferences'], 3) * 0.6
                + _ratio(counts['rules'], 2) * 0.4
            ),
            'hint': 'Review a few generations so Scaleezy can learn your taste.',
        },
    ]

    for dimension in dimensions:
        dimension['score'] = round(min(1.0, max(0.0, dimension['score'])), 4)
        dimension['earned'] = round(dimension['score'] * dimension['weight'], 2)
        dimension['complete'] = dimension['score'] >= 0.999

    total = round(sum(d['earned'] for d in dimensions))
    conflicts = brain.get('unresolved_conflict_count', 0)

    if total >= 85:
        level = LEVEL_READY
    elif total >= 60:
        level = LEVEL_STRONG
    elif total >= 30:
        level = LEVEL_LEARNING
    else:
        level = LEVEL_STARTING

    incomplete = [d for d in dimensions if not d['complete']]
    # The most valuable next step is the one with the most weight still on the
    # table, not simply the emptiest.
    weakest = max(
        incomplete, key=lambda d: (d['weight'] * (1 - d['score']), d['key']), default=None
    )

    if conflicts:
        next_action = {
            'key': 'resolve_conflicts',
            'label': (
                f"Resolve {conflicts} brand conflict{'s' if conflicts != 1 else ''}"
            ),
            'detail': 'Two equally trusted sources disagree. Scaleezy will not guess.',
        }
    elif weakest is not None:
        next_action = {
            'key': weakest['key'],
            'label': weakest['hint'],
            'detail': f"{weakest['label']} is {round(weakest['score'] * 100)}% complete.",
        }
    else:
        next_action = {
            'key': 'generate',
            'label': 'Start generating — Scaleezy knows this brand.',
            'detail': 'Every readiness dimension is complete.',
        }

    return {
        'readiness_score': total,
        'readiness_level': level,
        'completed_dimensions': [d['key'] for d in dimensions if d['complete']],
        'missing_dimensions': [d['key'] for d in incomplete],
        'dimensions': [
            {
                'key': d['key'], 'label': d['label'], 'weight': d['weight'],
                'score': d['score'], 'earned': d['earned'], 'complete': d['complete'],
                'hint': d['hint'],
            }
            for d in dimensions
        ],
        'recommended_next_action': next_action,
        'counts': {**counts, 'unresolved_conflicts': conflicts},
    }
