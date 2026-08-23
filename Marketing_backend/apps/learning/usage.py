"""
What a brand has learned, and whether any of it is actually reaching work.

The learning tab could already show what exists — rules, preferences, the
events behind them. What nobody could answer was the question that matters:
*is this reaching generation, or is it sitting in a table being ignored?*

Three separate facts answer it, and they are kept separate on purpose because
they fail independently:

* **In force** — the row's id appears in the compiled Brand Brain's
  `sources`. The brain is precisely what the Context Gateway hands to a
  generation, so membership there is not a proxy for "is it used", it is the
  thing itself. A rule that is active but absent from the brain is not
  reaching anything, and that gap is worth seeing.
* **Used** — how many recorded generations named this row in their trace.
  Only generations produced after tracing shipped can be counted, so the
  payload says how far back it can actually see rather than implying "never"
  for anything older.
* **Evidence** — how many distinct events support it and when the most recent
  arrived. A learned rule with stale evidence is a different problem from one
  with none.

Read-only. Nothing here writes, and nothing here recompiles the brain: a
report that changed what it measured would be measuring itself.
"""
from django.db.models import Q
from django.utils import timezone

from apps.content.models import ContentItem

from .models import BrandPreference, BrandRule, LearningEvent, LearningScope

#: How many recent content items to read traces from. Bounded because this is
#: a page render, not a report job; the payload states the bound so a count is
#: never mistaken for the whole history.
TRACE_SCAN_LIMIT = 500


def _iso(value):
    return value.isoformat() if value else None


def _trace_index(brand, limit=TRACE_SCAN_LIMIT):
    """(usage-by-id, generations-scanned, oldest-scanned) from stored traces.

    One pass over the brand's recent content items rather than a query per
    rule: the ids live inside a JSON blob, and JSON containment lookups are
    not portable across the databases this runs on (SQLite under test,
    PostgreSQL in production). A bounded scan behaves identically on both.
    """
    usage = {}
    scanned = 0
    oldest = None

    rows = (
        ContentItem.objects.filter(brand=brand)
        .order_by('-created_at')
        .values_list('layout_config', 'created_at')[:limit]
    )
    for layout_config, created_at in rows:
        trace = (layout_config or {}).get('generation_trace') or {}
        ids = list(trace.get('rule_ids') or []) + list(trace.get('preference_ids') or [])
        if not ids:
            # A generation from before tracing existed. Counted as scanned so
            # the window is honest, but it can attribute nothing.
            scanned += 1
            oldest = created_at
            continue
        scanned += 1
        oldest = created_at
        for row_id in ids:
            entry = usage.setdefault(str(row_id), {'count': 0, 'last_used_at': None})
            entry['count'] += 1
            if entry['last_used_at'] is None or created_at > entry['last_used_at']:
                entry['last_used_at'] = created_at
    return usage, scanned, oldest


def _evidence_index(workspace, brand):
    """When each learning event happened, so evidence can be dated."""
    events = LearningEvent.objects.filter(workspace=workspace)
    if brand is not None:
        events = events.filter(brand=brand)
    return dict(events.values_list('id', 'created_at'))


def _not_in_force_reason(is_active, in_brain):
    if not is_active:
        return 'DEACTIVATED'
    if not in_brain:
        # Active but absent from the compiled brain: it lost a precedence
        # contest, or the brain has not been recompiled since it was written.
        return 'NOT_IN_COMPILED_BRAIN'
    return ''


def learning_usage_report(workspace, brand):
    """Every learned instruction for one brand, with whether it is reaching work."""
    brain = getattr(brand, 'creative_brain', None) or {}
    sources = brain.get('sources') or {}
    brain_rule_ids = {str(i) for i in (sources.get('rule_ids') or [])}
    brain_preference_ids = {str(i) for i in (sources.get('preference_ids') or [])}

    usage, scanned, oldest = _trace_index(brand)
    evidence_at = _evidence_index(workspace, brand)

    rules = []
    # Same reach as the brain compiler: this brand's rows plus genuinely
    # workspace-wide ones, so the report cannot show a row the generator
    # never sees, or hide one it does.
    rule_rows = BrandRule.objects.filter(workspace=workspace).filter(
        Q(brand=brand) | Q(brand__isnull=True, scope=LearningScope.TENANT)
    )
    for rule in rule_rows:
        row_id = str(rule.pk)
        in_brain = row_id in brain_rule_ids
        evidence_ids = [e for e in (rule.evidence_event_ids or [])]
        dates = [evidence_at[e] for e in evidence_ids if e in evidence_at]
        seen = usage.get(row_id, {})
        rules.append({
            'id': row_id,
            'kind': 'RULE',
            'text': rule.text,
            'origin': rule.origin,
            'hardness': rule.hardness,
            'scope': rule.scope,
            'priority': rule.priority,
            'is_active': rule.is_active,
            'in_force': bool(rule.is_active and in_brain),
            'not_in_force_reason': _not_in_force_reason(rule.is_active, in_brain),
            'evidence_count': len(evidence_ids),
            'last_evidence_at': _iso(max(dates)) if dates else None,
            'generations_used': seen.get('count', 0),
            'last_used_at': _iso(seen.get('last_used_at')),
            'created_at': _iso(rule.created_at),
        })

    preferences = []
    preference_rows = BrandPreference.objects.filter(workspace=workspace).filter(
        Q(brand=brand) | Q(brand__isnull=True, scope=LearningScope.TENANT)
    )
    for preference in preference_rows:
        row_id = str(preference.pk)
        in_brain = row_id in brain_preference_ids
        is_active = preference.state != BrandPreference.State.RETIRED
        seen = usage.get(row_id, {})
        preferences.append({
            'id': row_id,
            'kind': 'PREFERENCE',
            'text': f'{preference.category}/{preference.attribute}: {preference.value}'.strip(),
            'category': preference.category,
            'attribute': preference.attribute,
            'value': preference.value,
            'state': preference.state,
            'scope': preference.scope,
            'is_active': is_active,
            'in_force': bool(is_active and in_brain),
            'not_in_force_reason': (
                'RETIRED' if not is_active
                else _not_in_force_reason(True, in_brain)
            ),
            'evidence_count': preference.evidence_count,
            'last_evidence_at': None,
            'generations_used': seen.get('count', 0),
            'last_used_at': _iso(seen.get('last_used_at')),
            'created_at': _iso(preference.created_at),
        })

    rows = sorted(
        rules + preferences,
        key=lambda r: (-r['generations_used'], not r['in_force'], r['text'][:80]),
    )
    learned = [r for r in rows if r.get('origin') != BrandRule.Origin.EXPLICIT]

    return {
        'brand_id': str(brand.pk),
        'brand_name': brand.name,
        'brain_version': brain.get('brain_version', ''),
        'brain_compiled_at': brain.get('compiled_at') or None,
        'generated_at': timezone.now().isoformat(),
        'totals': {
            'in_force': sum(1 for r in rows if r['in_force']),
            'not_in_force': sum(1 for r in rows if not r['in_force']),
            'learned': len(learned),
            'never_used': sum(1 for r in rows if r['in_force'] and not r['generations_used']),
        },
        # What the "used" numbers can and cannot see, stated rather than implied.
        'attribution': {
            'generations_scanned': scanned,
            'scan_limit': TRACE_SCAN_LIMIT,
            'oldest_scanned_at': _iso(oldest),
            'note': (
                'Counts come from generation traces. Content generated before '
                'tracing shipped carries no attribution, so a zero means "not '
                'seen in the scanned window", never "never used".'
            ),
        },
        'rows': rows,
    }
