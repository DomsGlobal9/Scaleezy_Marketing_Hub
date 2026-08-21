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


@transaction.atomic
def reinforce_preference(
    *,
    workspace,
    brand,
    category,
    attribute,
    value='',
    weight=None,
    confidence=None,
    scope=LearningScope.BRAND,
    event=None,
):
    """Add one piece of evidence to a leaning, creating it if it is new.

    A preference starts EMERGING and only becomes ESTABLISHED once a second
    distinct event supports it. That threshold is the whole difference between
    a learning system and a system that overfits to whoever reviewed last.
    """
    if brand is None:
        raise LearningError("A preference must belong to a brand.")
    if brand.workspace_id != workspace.id:
        raise LearningError("Brand must belong to the same workspace as the preference.")

    preference, created = BrandPreference.objects.get_or_create(
        workspace=workspace,
        brand=brand,
        category=category,
        attribute=attribute,
        defaults={
            'value': value,
            'scope': scope,
            'weight': 0.5 if weight is None else weight,
            'confidence': 0.0 if confidence is None else confidence,
        },
    )
    if preference.state == BrandPreference.State.RETIRED:
        # A retired leaning is not quietly revived by new evidence; someone
        # decided it no longer applies. New evidence starts a new record.
        raise LearningError(
            "This preference was retired. Create a new one rather than reviving it."
        )

    preference.evidence_count += 1
    if value:
        preference.value = value
    if weight is not None:
        preference.weight = weight
    if confidence is not None:
        preference.confidence = confidence
    if (
        preference.state == BrandPreference.State.EMERGING
        and preference.evidence_count >= BrandPreference.ESTABLISHED_AT_EVIDENCE
    ):
        preference.state = BrandPreference.State.ESTABLISHED

    preference.save()

    if event is not None:
        logger.info(
            "Preference %s reinforced to %s by event %s",
            preference.pk, preference.evidence_count, event.pk,
        )
    return preference


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
def promote_preference_to_rule(*, preference, evidence_events=(), priority=0):
    """Turn an established leaning into a soft rule.

    Refuses on two counts, and both are the PR3 acceptance criteria:

    * not enough evidence — a one-off stays an opinion;
    * the result is always SOFT — an inference never becomes a constraint the
      generator cannot break. A person can promote it to hard afterwards, and
      that is a decision with a name attached.
    """
    events = list(evidence_events)
    if len(events) < BrandRule.MIN_EVIDENCE_FOR_LEARNED_RULE:
        raise LearningError(
            f"A learned rule needs at least {BrandRule.MIN_EVIDENCE_FOR_LEARNED_RULE} "
            f"supporting events; got {len(events)}. One-off feedback is an opinion."
        )
    if preference.state != BrandPreference.State.ESTABLISHED:
        raise LearningError(
            "Only an established preference can back a rule; this one is "
            f"{preference.state}."
        )
    for event in events:
        if event.workspace_id != preference.workspace_id:
            raise LearningError("Evidence must come from the same workspace.")
        if event.brand_id and event.brand_id != preference.brand_id:
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
    """Rows for this brand, plus workspace-wide rows that carry no brand."""
    from django.db.models import Q

    return Q(brand=brand) | Q(brand__isnull=True)
