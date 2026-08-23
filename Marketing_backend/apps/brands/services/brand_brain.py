"""
The Brand Brain compiler.

`Brand.creative_brain` is a snapshot, never a source of truth. Everything in it
is derived from records that live elsewhere — the brand row, confirmed
memories, active rules, live preferences, authoritative inspiration signals —
so deleting the column and recompiling reconstructs the same brain. That is the
whole contract: if the compiled object were the only copy of anything, losing
it would lose knowledge, and the earlier training engine that appended taste
rules straight into this column had exactly that problem.

Two properties do the work.

*Determinism.* The same authoritative inputs produce the same bytes and the
same fingerprint. Every collection is sorted on a stable key, nothing
non-deterministic enters the fingerprint payload, and `compiled_at` sits
outside it — recompiling an unchanged brand gives a new timestamp and the same
fingerprint, which is what makes "has anything actually changed?" answerable.

*Precedence without silent collapse.* Claims about the same attribute are
ranked: a human's explicit instruction outranks an inference, every time. When
two records at the SAME rank disagree there is no rule to break the tie, so
neither is emitted and the disagreement is recorded. Inventing a winner is how
a brand brain quietly starts asserting something nobody said.

Provider-neutral by construction: no prompt text, no model names, no
provider-specific shapes. Translating this into whatever a provider wants is
the adapter's job, later.
"""
import hashlib
import json
import logging

from django.db import transaction
from django.utils import timezone

from apps.inspirations.models import InspirationSignal, normalize_signal_text
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import BrandPreference, BrandRule, LearningScope

#: Bump when the shape changes in a way a consumer must notice.
logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Precedence, highest authority first. The number is what gets compared, so a
# claim only ever loses to a strictly lower number.
RANK_HARD_EXPLICIT_RULE = 10
RANK_VERIFIED_FACT = 20
RANK_EXPLICIT_PREFERENCE = 30
RANK_LEARNED_SOFT_RULE = 40
RANK_ESTABLISHED_PREFERENCE = 50
RANK_EMERGING_PREFERENCE = 60
RANK_INSPIRATION_SIGNAL = 70

RANK_LABELS = {
    RANK_HARD_EXPLICIT_RULE: 'hard_explicit_rule',
    RANK_VERIFIED_FACT: 'verified_fact',
    RANK_EXPLICIT_PREFERENCE: 'explicit_preference',
    RANK_LEARNED_SOFT_RULE: 'learned_soft_rule',
    RANK_ESTABLISHED_PREFERENCE: 'established_preference',
    RANK_EMERGING_PREFERENCE: 'emerging_preference',
    RANK_INSPIRATION_SIGNAL: 'inspiration_signal',
}

#: Memory types that count as verified product truth rather than colour.
PRODUCT_TRUTH_TYPES = (
    BrandMemory.MemoryType.FACT,
    BrandMemory.MemoryType.PRODUCT_TRUTH,
    BrandMemory.MemoryType.EVIDENCE,
    BrandMemory.MemoryType.BRAND_CANON,
)
POSITIONING_TYPES = (
    BrandMemory.MemoryType.POSITIONING_SIGNAL,
    BrandMemory.MemoryType.FOUNDER_POV,
)
AUDIENCE_TYPES = (
    BrandMemory.MemoryType.BUYER_PAIN,
    BrandMemory.MemoryType.OBJECTION,
)

VISUAL_CATEGORIES = {
    'TYPOGRAPHY', 'COLOR', 'LAYOUT', 'COMPOSITION', 'IMAGERY',
    'PHOTOGRAPHY', 'ILLUSTRATION', 'MOTION', 'BRANDING',
}
VOICE_CATEGORIES = {'TONE', 'COPY_STYLE', 'HOOK', 'CTA', 'PACING', 'MOOD'}


class Claim:
    """One assertion about one attribute, and where its authority comes from."""

    __slots__ = ('category', 'attribute', 'value', 'sentiment', 'rank', 'source_type',
                 'source_id', 'confidence', 'weight')

    def __init__(self, *, category, attribute, value, rank, source_type, source_id,
                 sentiment='NEUTRAL', confidence=0.0, weight=0.5):
        self.category = category or 'OTHER'
        self.attribute = attribute or ''
        self.value = value or ''
        self.sentiment = sentiment or 'NEUTRAL'
        self.rank = rank
        self.source_type = source_type
        self.source_id = str(source_id)
        self.confidence = float(confidence or 0.0)
        self.weight = float(weight or 0.0)

    @property
    def key(self):
        return (
            normalize_signal_text(self.category),
            normalize_signal_text(self.attribute),
        )

    @property
    def normalized_value(self):
        return normalize_signal_text(self.value)

    def as_dict(self):
        return {
            'category': self.category,
            'attribute': self.attribute,
            'value': self.value,
            'sentiment': self.sentiment,
            'authority': RANK_LABELS[self.rank],
            'source_type': self.source_type,
            'source_id': self.source_id,
            'confidence': round(self.confidence, 4),
            'weight': round(self.weight, 4),
        }


def _sorted_claims(claims):
    """Stable order that does not depend on how rows were inserted."""
    return sorted(
        claims,
        key=lambda c: (c.rank, c.key[0], c.key[1], c.normalized_value, c.source_id),
    )


def resolve_claims(claims):
    """Apply precedence, and refuse to break a tie that has no rule.

    Returns (resolved, overridden, conflicts).

    A claim beaten by a higher authority is `overridden` — that is precedence
    working, and it stays visible so a reviewer can see what was outranked.
    Two claims of EQUAL authority disagreeing is a `conflict`: nothing decides
    it, so neither is emitted.
    """
    by_key = {}
    for claim in _sorted_claims(claims):
        by_key.setdefault(claim.key, []).append(claim)

    resolved, overridden, conflicts = [], [], []

    for key in sorted(by_key):
        group = by_key[key]
        best_rank = min(c.rank for c in group)
        top = [c for c in group if c.rank == best_rank]
        lost = [c for c in group if c.rank != best_rank]

        distinct = {(c.normalized_value, c.sentiment) for c in top}
        if len(distinct) > 1:
            conflicts.append({
                'category': group[0].category,
                'attribute': group[0].attribute,
                'authority': RANK_LABELS[best_rank],
                'reason': 'EQUAL_AUTHORITY_DISAGREEMENT',
                'claims': [c.as_dict() for c in top],
            })
            # Everything about this attribute is withheld: emitting the
            # outranked claim would present a losing answer as the brand's
            # position just because the winners cancelled out.
            overridden.extend(lost)
            continue

        winner = top[0]
        resolved.append(winner)
        overridden.extend(lost)
        overridden.extend(top[1:])

    return resolved, overridden, conflicts


def _memories(brand):
    """Confirmed memories whose source is still eligible.

    A revoked source stops influencing the brain on the next compile (PR1-010),
    while the memory row itself stays for audit.
    """
    return (
        BrandMemory.objects.filter(
            workspace_id=brand.workspace_id,
            brand=brand,
            status=BrandMemory.MemoryStatus.CONFIRMED,
        )
        .exclude(source__status=BrandSource.SourceStatus.ARCHIVED)
        .order_by('id')
    )


def _rules(brand):
    """Active rules for this brand, plus genuinely workspace-wide ones."""
    from django.db.models import Q

    return (
        BrandRule.objects.filter(workspace_id=brand.workspace_id, is_active=True)
        .filter(Q(brand=brand) | Q(brand__isnull=True, scope=LearningScope.TENANT))
        .order_by('id')
    )


def _preferences(brand):
    from django.db.models import Q

    return (
        BrandPreference.objects.filter(workspace_id=brand.workspace_id)
        .active()
        .filter(Q(brand=brand) | Q(brand__isnull=True, scope=LearningScope.TENANT))
        .order_by('id')
    )


def _signals(brand):
    """Signals that survive PR2's authority rules: not superseded, not
    rejected, not contradicting a stated preference, parent not archived."""
    return (
        InspirationSignal.objects.filter(inspiration__brand=brand)
        .eligible_for_retrieval()
        .order_by('id')
    )


def _collect_claims(rules, preferences, signals):
    claims = []

    for rule in rules:
        structured = rule.structured if isinstance(rule.structured, dict) else {}
        rank = (
            RANK_HARD_EXPLICIT_RULE
            if rule.hardness == BrandRule.Hardness.HARD
            else RANK_EXPLICIT_PREFERENCE
            if rule.origin == BrandRule.Origin.EXPLICIT
            else RANK_LEARNED_SOFT_RULE
        )
        claims.append(Claim(
            category=structured.get('category') or 'RULE',
            attribute=structured.get('attribute') or rule.text[:120],
            value=structured.get('value') or rule.text,
            rank=rank,
            source_type='brand_rule',
            source_id=rule.pk,
            confidence=rule.confidence,
            weight=1.0 if rule.hardness == BrandRule.Hardness.HARD else 0.6,
        ))

    for preference in preferences:
        claims.append(Claim(
            category=preference.category,
            attribute=preference.attribute,
            value=preference.value,
            rank=(
                RANK_ESTABLISHED_PREFERENCE
                if preference.state == BrandPreference.State.ESTABLISHED
                else RANK_EMERGING_PREFERENCE
            ),
            source_type='brand_preference',
            source_id=preference.pk,
            confidence=preference.confidence,
            weight=preference.weight,
        ))

    for signal in signals:
        # A stated human preference is not an inference, and must outrank one
        # even when both arrive through the same table (PR2 semantics).
        rank = (
            RANK_EXPLICIT_PREFERENCE
            if signal.origin == InspirationSignal.Origin.USER
            else RANK_INSPIRATION_SIGNAL
        )
        claims.append(Claim(
            category=signal.category,
            attribute=signal.attribute,
            value=signal.value,
            sentiment=signal.sentiment,
            rank=rank,
            source_type='inspiration_signal',
            source_id=signal.pk,
            confidence=signal.confidence,
            weight=signal.weight,
        ))

    return claims


#: Claim category for a keyed memory that does not name one itself. A
#: `normalized_key` of "COLOR/accent" claims under COLOR; a bare
#: "roast_freshness" claims under FACT.
MEMORY_CLAIM_CATEGORY = 'FACT'


def _memory_claims(memories):
    """Keyed confirmed memories, as claims in the same contest as everything else.

    A memory with a `normalized_key` is asserting something specific about a
    named thing, which is exactly what a rule or a preference does — so it has
    to be ranked against them rather than sitting in a separate list where a
    softer claim about the same key could quietly become the answer.

    Unkeyed memories are narrative. They stay in their semantic sections and
    are not forced into invented keys, because a key nobody chose would
    collide by accident.
    """
    claims = []
    for memory in memories:
        key = (memory.normalized_key or '').strip()
        if not key:
            continue
        category, _, attribute = key.rpartition('/')
        claims.append(Claim(
            category=category or MEMORY_CLAIM_CATEGORY,
            attribute=attribute,
            value=memory.content,
            rank=RANK_VERIFIED_FACT,
            source_type='brand_memory',
            source_id=memory.pk,
            confidence=memory.confidence,
            weight=1.0,
        ))
    return claims


def _memories_blocked_by_conflict(conflicts):
    """Memories withheld because an equally authoritative one disagrees."""
    return {
        claim['source_id']
        for conflict in conflicts
        for claim in conflict['claims']
        if claim.get('source_type') == 'brand_memory'
    }


def _memory_texts(memories, types, blocked):
    return sorted(
        {
            m.content.strip()
            for m in memories
            if m.memory_type in types and str(m.pk) not in blocked and m.content.strip()
        }
    )


def brain_fingerprint(content):
    """Content hash. Deterministic across processes and insertion orders."""
    canonical = json.dumps(content, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def compile_brand_brain(brand):
    """Build the snapshot. Pure — reads authoritative records, writes nothing."""
    memories = list(_memories(brand))
    rules = list(_rules(brand))
    preferences = list(_preferences(brand))
    signals = list(_signals(brand))

    resolved, overridden, conflicts = resolve_claims(
        _collect_claims(rules, preferences, signals) + _memory_claims(memories)
    )
    blocked_memories = _memories_blocked_by_conflict(conflicts)

    hard_rules = sorted(
        (
            {'id': str(r.pk), 'text': r.text, 'priority': r.priority,
             'scope': r.scope, 'origin': r.origin}
            for r in rules if r.hardness == BrandRule.Hardness.HARD
        ),
        key=lambda r: (-r['priority'], r['id']),
    )
    soft_rules = sorted(
        (
            {'id': str(r.pk), 'text': r.text, 'priority': r.priority,
             'scope': r.scope, 'origin': r.origin}
            for r in rules if r.hardness == BrandRule.Hardness.SOFT
        ),
        key=lambda r: (-r['priority'], r['id']),
    )

    resolved_dicts = [c.as_dict() for c in resolved]
    visual = [c for c in resolved_dicts if c['category'] in VISUAL_CATEGORIES]
    voice_claims = [c for c in resolved_dicts if c['category'] in VOICE_CATEGORIES]

    content = {
        'schema_version': SCHEMA_VERSION,
        'workspace_id': str(brand.workspace_id),
        'brand_id': str(brand.pk),

        'identity': {
            'name': brand.name,
            'industry': brand.industry,
            'description': brand.description,
            'tagline': brand.tagline,
            'cta_keyword': brand.cta_keyword,
            'has_logo': bool(brand.logo_url),
            'canon': _memory_texts(
                memories, (BrandMemory.MemoryType.BRAND_CANON,), blocked_memories
            ),
        },
        'positioning': {
            'statements': _memory_texts(memories, POSITIONING_TYPES, blocked_memories),
            'competitors': sorted(str(c) for c in (brand.competitors or [])),
        },
        'audiences': {
            # Who the brand says it serves, kept beside — never instead of —
            # the pains and objections confirmed from evidence. It is a
            # first-party statement, so it enters no precedence contest: there
            # is nothing for it to contradict.
            'stated': brand.audience,
            'pains': _memory_texts(
                memories, (BrandMemory.MemoryType.BUYER_PAIN,), blocked_memories
            ),
            'objections': _memory_texts(
                memories, (BrandMemory.MemoryType.OBJECTION,), blocked_memories
            ),
        },
        'voice': {
            'tone': brand.brand_tone,
            'claims': voice_claims,
        },
        'visual_language': {
            'palette': brand.palette or {},
            'fonts': brand.fonts or {},
            'layout_preference': brand.layout_preference,
            'claims': visual,
        },
        'verified_product_truth': _memory_texts(
            memories, PRODUCT_TRUTH_TYPES, blocked_memories
        ),

        'hard_rules': hard_rules,
        'soft_rules': soft_rules,
        'preferences': resolved_dicts,
        'inspiration_signals': sorted(
            (
                {'id': str(s.pk), 'category': s.category, 'attribute': s.attribute,
                 'value': s.value, 'sentiment': s.sentiment, 'origin': s.origin,
                 'weight': round(s.weight, 4), 'confidence': round(s.confidence, 4)}
                for s in signals
            ),
            key=lambda s: (s['category'], s['attribute'], s['id']),
        ),

        'win_patterns': sorted(
            {c['value'] for c in resolved_dicts if c['sentiment'] == 'LIKED' and c['value']}
        ),
        'avoid_patterns': sorted(
            {c['value'] for c in resolved_dicts if c['sentiment'] == 'DISLIKED' and c['value']}
        ),

        'unresolved_conflict_count': len(conflicts),
        'conflicts': conflicts,
        'overridden': sorted(
            (c.as_dict() for c in overridden),
            key=lambda c: (c['authority'], c['category'], c['attribute'], c['source_id']),
        ),

        # Enough to explain any line back to the row it came from.
        'sources': {
            'memory_ids': sorted(str(m.pk) for m in memories),
            'rule_ids': sorted(str(r.pk) for r in rules),
            'preference_ids': sorted(str(p.pk) for p in preferences),
            'inspiration_signal_ids': sorted(str(s.pk) for s in signals),
        },
    }

    fingerprint = brain_fingerprint(content)
    # compiled_at sits OUTSIDE the hashed payload: recompiling an unchanged
    # brand must give a new timestamp and the same fingerprint, or "did
    # anything change?" cannot be answered by comparing versions.
    return {**content, 'brain_version': fingerprint, 'compiled_at': timezone.now().isoformat()}


@transaction.atomic
def rebuild_brand_brain(brand):
    """Compile and persist. Source records are read only."""
    brain = compile_brand_brain(brand)
    brand.creative_brain = brain
    brand.save(update_fields=['creative_brain', 'updated_at'])
    return brain


def rebuild_brand_brain_safely(brand):
    """Recompile after an intelligence change, without letting the recompile
    cost the user the change itself.

    Confirming a fact, stating a preference, archiving a source or stating a
    rule all alter what the brain should say; this keeps the persisted
    snapshot - the one generation reads and readiness scores - current the
    moment they land. Best-effort on purpose: the record is the truth and the
    snapshot can always be rebuilt, so a compile failure is logged, never
    raised back into the request that made the change.
    """
    if brand is None:
        return None
    try:
        return rebuild_brand_brain(brand)
    except Exception:
        logger.exception(
            "Could not rebuild Brand Brain for brand %s", getattr(brand, 'pk', None)
        )
        return None
