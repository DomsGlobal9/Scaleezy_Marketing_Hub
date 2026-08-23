"""Deterministic PR7 aggregation of every CLIENT workspace's learning.

No consent flag or cohort minimum is consulted. INTERNAL workspaces are the
only exclusion. Patterns remain drafts until a Platform Admin publishes them.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.inspirations.models import normalize_signal_text
from apps.learning.models import BrandPreference, BrandRule, LearningEvent
from apps.workspaces.models import MarketingWorkspace

from .models import LearnedPattern, LifecycleStatus

_UNSAFE_VALUE = re.compile(
    r"(?:https?://|www\.|[\w.+-]+@[\w.-]+\.[a-z]{2,}|\+?\d[\d\s().-]{7,}\d)",
    re.IGNORECASE,
)
_DISTINCTIVE_TOKEN = re.compile(r"[a-z0-9_-]{24,}", re.IGNORECASE)


def _flatten_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _flatten_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten_strings(item)


def _safe_value(raw_value, brand=None):
    """Return a normalized pattern shape, never brand-specific literal copy."""
    raw = str(raw_value or '').strip()
    normalized = normalize_signal_text(raw)
    if not normalized or len(normalized) > 160:
        return ''
    if _UNSAFE_VALUE.search(raw) or _DISTINCTIVE_TOKEN.search(raw):
        return ''

    if brand is not None:
        sensitive = [
            brand.name, brand.tagline, brand.cta_keyword, brand.location,
            brand.contact_phone, brand.website,
            *list(_flatten_strings(brand.products_services)),
        ]
        for value in sensitive:
            folded = normalize_signal_text(value)
            if len(folded) >= 4 and folded in normalized:
                return ''
    return normalized


def _event_counts():
    """Real counts used as a deterministic confidence weight; no eligibility filter."""
    rows = (
        LearningEvent.objects.filter(workspace__kind=MarketingWorkspace.Kind.CLIENT)
        .values('workspace_id', 'brand_id', 'event_type', 'outcome')
        .annotate(total=Count('id'))
    )
    totals = defaultdict(int)
    breakdown = defaultdict(dict)
    for row in rows:
        key = (row['workspace_id'], row['brand_id'])
        count = int(row['total'])
        totals[key] += count
        breakdown[key][f"{row['event_type']}:{row['outcome']}"] = count
    return totals, breakdown


def _candidate_payloads():
    event_totals, _ = _event_counts()
    groups = {}

    def add(*, workspace_id, brand, category, attribute, value, confidence, support):
        safe = _safe_value(value, brand)
        category = str(category or 'OTHER').strip().upper()[:64]
        attribute = normalize_signal_text(attribute)[:255]
        if not safe or not attribute:
            return
        # Brand.industry is free text: this is an exact string cohort, never
        # presented as a taxonomy. Blank means the global cohort.
        industry = str(getattr(brand, 'industry', '') or '').strip()[:100]
        key = (category, attribute, safe, industry.casefold(), '')
        row = groups.setdefault(key, {
            'category': category,
            'attribute': attribute,
            'value': safe,
            'normalized_value': safe,
            'industry': industry,
            'channel': '',
            'workspaces': set(),
            'brands': set(),
            'confidence_total': 0.0,
            'confidence_weight': 0.0,
        })
        row['workspaces'].add(str(workspace_id))
        if brand is not None:
            row['brands'].add(str(brand.pk))
        event_count = event_totals.get((workspace_id, getattr(brand, 'pk', None)), 0)
        evidence_weight = max(1.0, float(support or 0)) * (1.0 + min(event_count, 20) * 0.05)
        bounded_confidence = max(0.0, min(1.0, float(confidence or 0.0)))
        row['confidence_total'] += bounded_confidence * evidence_weight
        row['confidence_weight'] += evidence_weight

    preferences = (
        BrandPreference.objects.filter(workspace__kind=MarketingWorkspace.Kind.CLIENT)
        .active()
        .select_related('brand')
        .order_by('id')
    )
    for preference in preferences:
        add(
            workspace_id=preference.workspace_id,
            brand=preference.brand,
            category=preference.category,
            attribute=preference.attribute,
            value=preference.value,
            confidence=(preference.confidence * 0.7 + preference.weight * 0.3),
            support=preference.evidence_count,
        )

    rules = (
        BrandRule.objects.filter(
            workspace__kind=MarketingWorkspace.Kind.CLIENT,
            origin=BrandRule.Origin.LEARNED,
            is_active=True,
        )
        .select_related('brand')
        .order_by('id')
    )
    for rule in rules:
        structured = rule.structured if isinstance(rule.structured, dict) else {}
        add(
            workspace_id=rule.workspace_id,
            brand=rule.brand,
            category=structured.get('category') or 'RULE',
            attribute=structured.get('attribute') or structured.get('element') or rule.text[:255],
            value=structured.get('value') or rule.text,
            confidence=rule.confidence,
            support=len(set(str(v) for v in (rule.evidence_event_ids or []))),
        )

    payloads = []
    for key in sorted(groups):
        row = groups[key]
        contributors = sorted(row.pop('workspaces'))
        brands = sorted(row.pop('brands'))
        confidence = (
            row.pop('confidence_total') / row.pop('confidence_weight')
            if row['confidence_weight'] else 0.0
        )
        payload = {
            **row,
            'contributor_count': len(contributors),
            'supporting_brand_count': len(brands),
            'confidence': round(confidence, 4),
            'contributing_workspace_ids': contributors,
        }
        version_source = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        payload['pattern_version'] = hashlib.sha256(
            version_source.encode('utf-8')
        ).hexdigest()[:16]
        payloads.append(payload)
    return payloads


def compile_version(payloads):
    stable = json.dumps(payloads, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(stable.encode('utf-8')).hexdigest()[:16]


@transaction.atomic
def compile_learned_patterns(*, dry_run=False):
    """Reconcile the derived table. Same source rows produce the same versions."""
    payloads = _candidate_payloads()
    version = compile_version(payloads)
    if dry_run:
        return {'pattern_version': version, 'pattern_count': len(payloads), 'patterns': payloads}

    now = timezone.now()
    active = list(LearnedPattern.objects.exclude(status=LifecycleStatus.RETIRED).order_by('id'))
    existing = {}
    duplicates = []
    for pattern in active:
        key = (
            pattern.category, pattern.attribute, pattern.normalized_value,
            pattern.industry.casefold(), pattern.channel.casefold(),
        )
        if key in existing:
            duplicates.append(pattern)
        else:
            existing[key] = pattern

    seen = set()
    created = updated = 0
    for payload in payloads:
        key = (
            payload['category'], payload['attribute'], payload['normalized_value'],
            payload['industry'].casefold(), payload['channel'].casefold(),
        )
        seen.add(key)
        pattern = existing.get(key)
        if pattern is None:
            LearnedPattern.objects.create(compiled_at=now, **payload)
            created += 1
            continue
        for field, value in payload.items():
            setattr(pattern, field, value)
        pattern.compiled_at = now
        pattern.save(update_fields=[*payload.keys(), 'compiled_at', 'updated_at'])
        updated += 1

    stale = duplicates + [row for key, row in existing.items() if key not in seen]
    for pattern in stale:
        pattern.status = LifecycleStatus.RETIRED
        pattern.retired_at = now
        pattern.save(update_fields=['status', 'retired_at', 'updated_at'])

    return {
        'pattern_version': version,
        'pattern_count': len(payloads),
        'created': created,
        'updated': updated,
        'retired': len(stale),
    }
