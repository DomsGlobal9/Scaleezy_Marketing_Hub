"""
Writing to the learning fabric, and reading back what a brand has learned.

The one rule everything here exists to hold: evidence accumulates before it
becomes an instruction. A single reviewer comment is an opinion. The second
one is a pattern. Only a person can state a hard constraint outright.
"""
import logging

from django.db import transaction
from django.utils import timezone

from .models import (
    BrandPreference,
    BrandRule,
    LearningEvent,
    LearningScope,
    PreferenceEvidence,
    SubjectType,
)

logger = logging.getLogger(__name__)

#: Scopes ordered narrow to wide. Resolution walks this so an asset-level
#: instruction outranks a brand-level one for the asset it names.
SCOPE_ORDER = [
    LearningScope.ASSET,
    LearningScope.CAMPAIGN,
    LearningScope.BRAND,
    LearningScope.TENANT,
]


class LearningError(Exception):
    """The requested learning write cannot be performed."""


def record_event_safely(**kwargs):
    """Record evidence without ever breaking the action that produced it.

    Every caller of this is a human doing something real — confirming a fact,
    retiring a preference, rewriting a headline. That action must land whether
    or not the fabric write succeeds; a ledger that can fail a verdict is
    worse than a ledger with a gap in it. Returns None on failure, loudly.
    """
    try:
        return record_event(**kwargs)
    except Exception:
        logger.exception(
            "Could not record a %s learning event", kwargs.get('event_type')
        )
        return None


@transaction.atomic
def record_event(
    *,
    workspace,
    event_type,
    brand=None,
    outcome=LearningEvent.Outcome.NEUTRAL,
    subject_type=SubjectType.OTHER,
    subject_id=None,
    source_type='',
    source_id=None,
    context=None,
    eligible_for_aggregate=False,
    dedupe_key='',
    created_by=None,
):
    """Record one piece of evidence.

    Idempotent whenever the caller supplies a `dedupe_key`: a replayed webhook
    or a retried job returns the event it already wrote rather than laying
    down a second copy, which would silently double the weight of one thing
    that happened once.
    """
    if brand is not None and brand.workspace_id != workspace.id:
        raise LearningError("Brand must belong to the same workspace as the event.")

    if dedupe_key:
        existing = LearningEvent.objects.filter(
            workspace=workspace, dedupe_key=dedupe_key
        ).first()
        if existing is not None:
            return existing

    return LearningEvent.objects.create(
        workspace=workspace,
        brand=brand,
        event_type=event_type,
        outcome=outcome,
        subject_type=subject_type,
        subject_id=subject_id,
        source_type=source_type or '',
        source_id=source_id,
        context=context or {},
        eligibility_for_aggregate_learning=bool(eligible_for_aggregate),
        dedupe_key=dedupe_key or '',
        created_by=created_by if (created_by and created_by.is_authenticated) else None,
    )


def check_scope_matches_brand(scope, brand):
    """Scope and brand say the same thing, or neither is trustworthy.

    The resolver reads a brandless row as workspace-wide, so a brandless row
    must actually be TENANT-scoped; and a brand-scoped row with no brand
    belongs to nobody. Checked in the writer and again by a CHECK constraint,
    so the two cannot drift.
    """
    if scope == LearningScope.TENANT:
        if brand is not None:
            raise LearningError(
                "TENANT scope is workspace-wide and must not name a brand."
            )
    elif brand is None:
        raise LearningError(f"{scope} scope requires a brand.")


@transaction.atomic
def reinforce_preference(
    *,
    workspace,
    event,
    category,
    attribute,
    brand=None,
    value='',
    weight=None,
    confidence=None,
    scope=LearningScope.BRAND,
):
    """Add one event to the evidence behind a leaning.

    `event` is required and is what the strength of a preference is counted
    from. Attaching the same event again is a no-op: `PreferenceEvidence` holds
    the pair under a unique constraint, so a retried job or a redelivered
    webhook cannot make one occurrence look like two and carry a preference
    over the EMERGING → ESTABLISHED line on its own.

    `evidence_count` is recomputed from that table rather than incremented, so
    the number and the lineage can never disagree.
    """
    check_scope_matches_brand(scope, brand)
    if brand is not None and brand.workspace_id != workspace.id:
        raise LearningError("Brand must belong to the same workspace as the preference.")
    if event is None:
        raise LearningError("A preference must be reinforced by a LearningEvent.")
    if event.workspace_id != workspace.id:
        raise LearningError("Evidence must come from the same workspace.")
    if brand is not None and event.brand_id != brand.id:
        raise LearningError("Evidence must come from the same brand as the preference.")
    if brand is None and event.brand_id is not None:
        # A workspace-wide leaning cannot rest on one brand's evidence: it
        # would resolve for every sibling brand on the strength of something
        # only ever observed about one of them. Promotion already refused this
        # evidence, so without the guard a TENANT preference could reach
        # ESTABLISHED and then never be promotable.
        raise LearningError(
            "A TENANT-scoped preference needs workspace-wide evidence; this "
            "event belongs to a single brand."
        )

    # Retired rows are excluded from the lookup on purpose. Someone decided
    # that leaning no longer applies, so new evidence must not revive their
    # row — but it must still be able to start a NEW one, or retiring a
    # preference once would silently discard every future judgment about that
    # attribute forever. `uniq_active_brand_preference` is conditional on
    # NOT RETIRED, so the retired row and its successor coexist legally.
    preference = (
        BrandPreference.objects.filter(
            workspace=workspace,
            brand=brand,
            category=category,
            attribute=attribute,
        )
        .exclude(state=BrandPreference.State.RETIRED)
        .first()
    )
    if preference is None:
        preference = BrandPreference.objects.create(
            workspace=workspace,
            brand=brand,
            category=category,
            attribute=attribute,
            value=value,
            scope=scope,
            weight=0.5 if weight is None else weight,
            confidence=0.0 if confidence is None else confidence,
        )

    # Two events only corroborate each other if they say the same thing.
    # Calibration tests opposing values for one attribute (register "soft" in
    # one direction, "direct" in another); without this, a verdict on each
    # counted as two supporting events for whichever value happened to be
    # stored first, and the preference reached ESTABLISHED on evidence that
    # partly contradicted it.
    incoming = ' '.join(str(value or '').split()).casefold()
    held = ' '.join(str(preference.value or '').split()).casefold()
    if incoming and held and incoming != held:
        raise LearningError(
            f"This evidence says '{value}' but the live preference says "
            f"'{preference.value}'. A contradiction is not corroboration; "
            "state the new position explicitly, or retire the old one."
        )

    _, is_new_evidence = PreferenceEvidence.objects.get_or_create(
        preference=preference, learning_event=event
    )

    if value:
        preference.value = value
    if weight is not None:
        preference.weight = weight
    if confidence is not None:
        preference.confidence = confidence

    preference.evidence_count = preference.evidence.count()
    if (
        preference.state == BrandPreference.State.EMERGING
        and preference.evidence_count >= BrandPreference.ESTABLISHED_AT_EVIDENCE
    ):
        preference.state = BrandPreference.State.ESTABLISHED

    preference.save()

    logger.info(
        "Preference %s now rests on %s distinct event(s); event %s was %s",
        preference.pk,
        preference.evidence_count,
        event.pk,
        "new" if is_new_evidence else "already counted",
    )
    return preference


def recompute_preference_evidence(preference):
    """Re-derive the count and state from the evidence that actually exists.

    Evidence disappears without going through this module: deleting a brand or
    a LearningEvent cascades the rows away. Left alone, a preference keeps
    claiming ESTABLISHED on evidence that is gone, which is precisely the
    fake-completion the rules forbid.
    """
    preference.evidence_count = preference.evidence.count()
    if preference.evidence_count < BrandPreference.ESTABLISHED_AT_EVIDENCE:
        if preference.state == BrandPreference.State.ESTABLISHED:
            preference.state = BrandPreference.State.EMERGING
    preference.save(update_fields=['evidence_count', 'state', 'updated_at'])
    return preference


def preference_evidence_events(preference):
    """The events a leaning rests on, oldest first. The lineage a reviewer
    follows to ask why the brand believes something."""
    return LearningEvent.objects.filter(
        preference_evidence__preference=preference
    ).order_by('created_at')


@transaction.atomic
def create_explicit_rule(
    *,
    workspace,
    brand,
    text,
    hardness=BrandRule.Hardness.SOFT,
    priority=0,
    scope=LearningScope.BRAND,
    structured=None,
    created_by=None,
    evidence_event_ids=None,
):
    """A person stating an instruction.

    Explicit rules take effect immediately and may be hard — someone said
    "never do this" and meant it. The provenance is what makes that safe:
    origin is EXPLICIT, and `created_by` records who granted the authority.
    """
    check_scope_matches_brand(scope, brand)
    if brand is not None and brand.workspace_id != workspace.id:
        raise LearningError("Brand must belong to the same workspace as the rule.")

    return BrandRule.objects.create(
        workspace=workspace,
        brand=brand,
        text=text,
        structured=structured or {},
        hardness=hardness,
        origin=BrandRule.Origin.EXPLICIT,
        priority=priority,
        scope=scope,
        evidence_event_ids=[str(i) for i in (evidence_event_ids or [])],
        confidence=1.0,
        created_by=created_by if (created_by and created_by.is_authenticated) else None,
    )


@transaction.atomic
def promote_preference_to_rule(*, preference, priority=0):
    """Turn an established leaning into a soft rule.

    The evidence is read from `PreferenceEvidence`, never taken from the
    caller. It used to be a list argument whose LENGTH was checked, so
    `evidence_events=[e, e]` cleared a two-event threshold with one event, and
    the ids a rule cited did not have to be the ones its preference actually
    rested on. That is the same defect the CTO rework removed from
    `reinforce_preference`, one layer up.

    Refuses on two counts, both PR3 acceptance criteria:

    * not enough DISTINCT evidence — a one-off stays an opinion;
    * the result is always SOFT — an inference never becomes a constraint the
      generator cannot break. A person can promote it to hard afterwards, and
      that is a decision with a name attached.
    """
    if preference.state != BrandPreference.State.ESTABLISHED:
        raise LearningError(
            "Only an established preference can back a rule; this one is "
            f"{preference.state}."
        )

    events = list(preference_evidence_events(preference))
    if len(events) < BrandRule.MIN_EVIDENCE_FOR_LEARNED_RULE:
        raise LearningError(
            f"A learned rule needs at least {BrandRule.MIN_EVIDENCE_FOR_LEARNED_RULE} "
            f"distinct supporting events; this preference rests on {len(events)}. "
            "One-off feedback is an opinion."
        )
    for event in events:
        if event.workspace_id != preference.workspace_id:
            raise LearningError("Evidence must come from the same workspace.")
        if preference.brand_id and event.brand_id != preference.brand_id:
            raise LearningError("Evidence must come from the same brand.")

    return BrandRule.objects.create(
        workspace=preference.workspace,
        brand=preference.brand,
        text=f"{preference.category}/{preference.attribute}: {preference.value}".strip(),
        structured={
            'category': preference.category,
            'attribute': preference.attribute,
            'value': preference.value,
        },
        hardness=BrandRule.Hardness.SOFT,
        origin=BrandRule.Origin.LEARNED,
        priority=priority,
        scope=preference.scope,
        evidence_event_ids=[str(e.pk) for e in events],
        confidence=preference.confidence,
    )


@transaction.atomic
def deactivate_rule(*, rule, user=None):
    """Rules are switched off, never deleted — a rule cited in a generation's
    lineage has to remain readable afterwards."""
    rule.is_active = False
    rule.deactivated_at = timezone.now()
    rule.deactivated_by = user if (user and user.is_authenticated) else None
    rule.save(update_fields=['is_active', 'deactivated_at', 'deactivated_by'])
    return rule


def resolve_rules(*, workspace, brand=None, scopes=None):
    """The rules in force for a brand, narrowest scope first.

    The read side PR5's context gateway will call. Tenant-scoped rules apply
    to every brand in the workspace; brand-scoped ones only to their own.
    """
    wanted = list(scopes) if scopes else SCOPE_ORDER
    queryset = BrandRule.objects.filter(workspace=workspace, scope__in=wanted)
    if brand is not None:
        queryset = queryset.filter(models_brand_filter(brand))
    return queryset.in_force()


def resolve_preferences(*, workspace, brand=None, scopes=None):
    """The leanings in force for a brand. Emerging ones are included and
    carry their evidence count, so a caller can weigh them itself rather than
    being handed a confident-looking fact built on one data point."""
    wanted = list(scopes) if scopes else SCOPE_ORDER
    queryset = BrandPreference.objects.filter(
        workspace=workspace, scope__in=wanted
    ).active()
    if brand is not None:
        queryset = queryset.filter(models_brand_filter(brand))
    return queryset.order_by('-evidence_count', '-updated_at')


def models_brand_filter(brand):
    """Rows for this brand, plus genuinely workspace-wide ones.

    The scope is checked, not just the null brand, so the resolver agrees with
    what the writer allows: brandless means TENANT and nothing else.
    """
    from django.db.models import Q

    return Q(brand=brand) | Q(brand__isnull=True, scope=LearningScope.TENANT)


@transaction.atomic
def upsert_learned_rule(
    *,
    workspace,
    brand,
    key,
    text,
    evidence_events,
    confidence=0.5,
    priority=0,
    structured=None,
    scope=LearningScope.BRAND,
):
    """A rule inferred from repeated evidence, keyed so it sharpens rather
    than duplicates.

    The entry point for anything that learns from a pattern rather than from a
    person stating an instruction — today, the review/training engine. It
    exists so that path writes into the fabric the Brand Brain compiles from,
    instead of into the compiled snapshot itself, where the next compile would
    silently overwrite it.

    Guarantees the PR3 authority model, whoever calls it:

    * always LEARNED and always SOFT — inference never becomes a constraint
      the generator cannot break;
    * at least `MIN_EVIDENCE_FOR_LEARNED_RULE` DISTINCT supporting events,
      each of which must belong to this workspace and brand;
    * one active rule per `key`, whose text and evidence are updated in place,
      so the third occurrence sharpens the rule rather than adding a second.
    """
    check_scope_matches_brand(scope, brand)
    if brand is not None and brand.workspace_id != workspace.id:
        raise LearningError("Brand must belong to the same workspace as the rule.")
    if not str(key or '').strip():
        raise LearningError("A learned rule needs a key so it can be sharpened later.")

    events = list(evidence_events or [])
    for event in events:
        if event.workspace_id != workspace.id:
            raise LearningError("Evidence must come from the same workspace.")
        if brand is not None and event.brand_id and event.brand_id != brand.pk:
            raise LearningError("Evidence must come from the same brand.")

    event_ids = sorted({str(event.pk) for event in events})
    if len(event_ids) < BrandRule.MIN_EVIDENCE_FOR_LEARNED_RULE:
        raise LearningError(
            f"A learned rule needs at least {BrandRule.MIN_EVIDENCE_FOR_LEARNED_RULE} "
            f"distinct supporting events; this one rests on {len(event_ids)}. "
            "One-off feedback is an opinion."
        )

    payload = {
        **(structured or {}),
        'key': str(key),
        'evidence_count': len(event_ids),
    }

    # Matched in Python rather than with a JSON lookup: the set of active
    # learned rules for one brand is small, and this behaves identically on
    # every database backend.
    # Deliberately NOT filtered to is_active: a deactivated rule with this
    # key has to be visible here, or the lookup misses it, a fresh rule is
    # created under a new id, and the person who switched it off is overruled
    # by the very engine they were correcting.
    existing = next(
        (
            rule
            for rule in BrandRule.objects.filter(
                workspace=workspace, brand=brand,
                origin=BrandRule.Origin.LEARNED,
            ).order_by('created_at')
            if isinstance(rule.structured, dict) and rule.structured.get('key') == str(key)
        ),
        None,
    )

    if existing is not None and not existing.is_active:
        # A person judged this inference wrong. More of the same evidence is
        # not an argument against them — it is the same evidence that produced
        # it in the first place. The caller logs and moves on; a human can
        # still state it outright as an explicit rule.
        raise LearningError(
            "This learned rule was switched off by a person; the pattern is not "
            "re-learned. State it explicitly if it should apply again."
        )

    if existing is not None:
        # Union, not replace. The rule's own claim is "this happened N times",
        # and its lineage is the list it cites — if the newest batch overwrote
        # the list, a rule built on five reviews would cite two and the claim
        # and the evidence behind it would disagree.
        merged = sorted({*(existing.evidence_event_ids or []), *event_ids})
        payload['evidence_count'] = len(merged)
        existing.text = text
        existing.structured = payload
        existing.evidence_event_ids = merged
        existing.confidence = min(1.0, max(0.0, float(confidence)))
        existing.priority = priority
        # Hardness and origin are deliberately never touched here: a learned
        # rule cannot be promoted into a constraint by being seen again.
        existing.save(update_fields=[
            'text', 'structured', 'evidence_event_ids', 'confidence', 'priority',
            'updated_at',
        ])
        return existing

    return BrandRule.objects.create(
        workspace=workspace,
        brand=brand,
        text=text,
        structured=payload,
        hardness=BrandRule.Hardness.SOFT,
        origin=BrandRule.Origin.LEARNED,
        priority=priority,
        scope=scope,
        evidence_event_ids=event_ids,
        confidence=min(1.0, max(0.0, float(confidence))),
    )
