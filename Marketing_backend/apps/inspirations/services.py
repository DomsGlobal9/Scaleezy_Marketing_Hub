"""
Which preference is true right now, and what happened to the ones that were.

The rule the CTO review turns on: for one inspiration + category + attribute,
the latest active explicit USER signal is authoritative, and nothing else about
that attribute is simultaneously active. Everything in this module exists to
keep that true across every write path.

Two ideas do the work:

*Supersession.* A preference is never edited and never deleted. It is replaced,
and the row that replaced it is recorded on it. So the history of what a brand
believed stays readable, while only one row at a time is the answer.

*Reconciliation.* Whenever authority can have moved, the live inference for that
attribute is re-checked against it. `conflicts_with` is a derived fact, so it is
recomputed rather than remembered — a stale pointer would be a contradiction
that looks resolved.
"""
import logging

from django.db import transaction
from django.utils import timezone

from .models import (
    BrandInspiration,
    InspirationSignal,
    InspirationSignalError,
    SupersessionReason,
    normalize_signal_text,
)

logger = logging.getLogger(__name__)

# Defined on the model so the bulk write paths can raise it too; re-exported
# here because this is where callers expect signal-writing errors to live.
__all__ = [
    'InspirationSignalError',
    'authoritative_user_signal',
    'active_ai_signal',
    'signals_conflict',
    'supersede',
    'reconcile_attribute',
    'record_user_signal',
    'confirm_signal',
    'reject_signal',
    'record_ai_signal',
]


def authoritative_user_signal(inspiration, category, attribute):
    """The stated preference that currently holds for one attribute, if any.

    `uniq_authoritative_user_signal` allows only one, so the ordering is
    belt-and-braces: it states "latest wins" in the code as well as in the
    schema, and keeps the answer deterministic if the constraint is ever
    dropped.
    """
    return (
        InspirationSignal.objects.for_attribute(inspiration, category, attribute)
        .authoritative_user_signals()
        .order_by('-created_at', '-pk')
        .first()
    )


def active_ai_signal(inspiration, category, attribute):
    """The live inference for one attribute, if any."""
    return (
        InspirationSignal.objects.for_attribute(inspiration, category, attribute)
        .filter(origin=InspirationSignal.Origin.AI, superseded_at__isnull=True)
        .order_by('-created_at', '-pk')
        .first()
    )


def signals_conflict(user_signal, ai_signal):
    """Does an inference contradict a stated preference?

    Either half counts. "They like this typeface" and "they dislike this
    typeface" is the obvious contradiction; "they like Condensed Grotesque" and
    "they like Serif Display" is the one that used to slip through, because
    only the sentiments were compared and those matched.

    Compared on the folded values, so casing and spacing cannot manufacture a
    disagreement that is not there.
    """
    if user_signal is None or ai_signal is None:
        return False
    return (
        user_signal.normalized_value != ai_signal.normalized_value
        or user_signal.sentiment != ai_signal.sentiment
    )


def _reject_if_history(signal, verb):
    """A superseded row records what was true; it is not a live verdict.

    Letting it be confirmed or rejected would edit history, and the row would
    stay out of retrieval anyway because supersession outranks confirmation —
    so the call could only ever mislead the caller.
    """
    if signal.superseded_at is not None:
        raise InspirationSignalError(
            f"This signal was superseded on {signal.superseded_at:%Y-%m-%d} and "
            f"cannot be {verb}. State a new signal for this attribute instead."
        )


def supersede(signal, *, by, reason, when=None):
    """Retire a preference in favour of another, keeping the old row.

    `superseded_at` is set first and separately from the pointer: the partial
    unique constraints are conditioned on it, so the replacement cannot be
    inserted until the row it replaces has stepped aside.
    """
    if signal is None:
        return None
    if by is not None and signal.pk == by.pk:
        raise InspirationSignalError("A signal cannot supersede itself.")
    if signal.superseded_at is not None:
        # Already history. Re-stamping it would rewrite when the brand changed
        # its mind.
        return signal

    signal.superseded_at = when or timezone.now()
    signal.superseded_reason = reason
    signal.superseded_by = by
    signal.save(update_fields=['superseded_at', 'superseded_reason', 'superseded_by'])
    logger.info(
        "Signal %s superseded (%s) by %s",
        signal.pk, reason, getattr(by, 'pk', None),
    )
    return signal


def reconcile_attribute(inspiration, category, attribute):
    """Re-derive whether the live inference contradicts the current authority.

    Called after anything that can move authority: a new stated preference, a
    confirmation, a rejection, a fresh inference. Cheap, and it means
    `conflicts_with` is never a fact that used to be true.
    """
    ai_signal = active_ai_signal(inspiration, category, attribute)
    if ai_signal is None:
        return None

    authority = authoritative_user_signal(inspiration, category, attribute)
    conflicting = authority if signals_conflict(authority, ai_signal) else None

    if ai_signal.conflicts_with_id != getattr(conflicting, 'pk', None):
        ai_signal.conflicts_with = conflicting
        ai_signal.save(update_fields=['conflicts_with'])
        if conflicting is not None:
            logger.info(
                "AI signal %s contradicts stated preference %s on inspiration %s; "
                "held for review",
                ai_signal.pk, conflicting.pk, inspiration.pk,
            )
    return ai_signal


@transaction.atomic
def supersede_user_preference_for(inspiration, category, attribute, *, reason):
    """Step the current stated preference aside, returning it.

    Returns the retired row so the caller can point it at whatever replaced it
    once that row exists. Split in two because the replacement cannot be
    inserted while the old row still satisfies the uniqueness condition.
    """
    authority = authoritative_user_signal(inspiration, category, attribute)
    if authority is None:
        return None
    return supersede(authority, by=None, reason=reason)


def link_supersession(previous, successor):
    """Record which row replaced a retired one."""
    if previous is None or successor is None:
        return
    if previous.pk == successor.pk:
        raise InspirationSignalError("A signal cannot supersede itself.")
    previous.superseded_by = successor
    previous.save(update_fields=['superseded_by'])


@transaction.atomic
def _outcome_for(signal):
    """Liking a thing and disliking it are opposite evidence, not the same
    evidence twice. NEUTRAL is real too: it means somebody looked and had no
    strong view, which should not be counted either way."""
    from apps.learning.models import LearningEvent

    return {
        InspirationSignal.Sentiment.LIKED: LearningEvent.Outcome.POSITIVE,
        InspirationSignal.Sentiment.DISLIKED: LearningEvent.Outcome.NEGATIVE,
    }.get(signal.sentiment, LearningEvent.Outcome.NEUTRAL)


def _record_signal_evidence(signal, *, user, outcome, action):
    """A person stating, confirming or withdrawing a taste is a judgment.

    Emitted from the service rather than the view so every writer is covered.
    Without it, a client could state the same preference across a dozen
    references and none of it ever reached the learning fabric — the signal
    lived only on its own inspiration, so nothing could notice the pattern.
    """
    from apps.learning.models import LearningEvent, SubjectType
    from apps.learning.services import record_event_safely

    inspiration = signal.inspiration
    return record_event_safely(
        workspace=inspiration.workspace,
        brand=inspiration.brand,
        event_type=LearningEvent.EventType.INSPIRATION_SIGNAL,
        outcome=outcome,
        subject_type=SubjectType.INSPIRATION_SIGNAL,
        subject_id=signal.pk,
        source_type=SubjectType.INSPIRATION,
        source_id=inspiration.pk,
        context={
            'action': action,
            'category': signal.category,
            'attribute': signal.attribute,
            'value': (signal.value or '')[:300],
            'sentiment': signal.sentiment,
            'origin': signal.origin,
        },
        dedupe_key=f'signal:{signal.pk}:{action}',
        created_by=user,
    )


def record_user_signal(serializer, *, user):
    """Persist a stated preference, retiring the one it replaces.

    A person changing their mind about an attribute produces a new row, not an
    edit: the previous statement stays readable, marked with what replaced it
    and why. That is what makes "multiple historical USER signals" auditable
    while only one of them is ever the answer.
    """
    data = serializer.validated_data
    inspiration = data['inspiration']
    category = data['category']
    attribute = data['attribute']

    previous = supersede_user_preference_for(
        inspiration, category, attribute,
        reason=SupersessionReason.NEWER_USER_SIGNAL,
    )

    signal = serializer.save(
        origin=InspirationSignal.Origin.USER,
        user_confirmation=InspirationSignal.UserConfirmation.CONFIRMED,
        created_by=user,
        confirmed_by=user,
        confirmed_at=timezone.now(),
    )

    link_supersession(previous, signal)
    reconcile_attribute(inspiration, category, attribute)
    signal.refresh_from_db()
    _record_signal_evidence(
        signal, user=user, outcome=_outcome_for(signal), action='STATED'
    )
    return signal


@transaction.atomic
def confirm_signal(signal, *, user):
    """A human agrees with a signal.

    For an inference that contradicts a stated preference, agreeing with it is
    a decision about the preference, not only about the inference: the old
    statement is explicitly superseded, so the brand is not left holding two
    contradictory active truths. The inference keeps `origin=AI` — a human
    accepted it, they did not author it.

    Authority is recomputed here rather than read from `conflicts_with`,
    because the stated preference may have moved since the inference was
    filed.
    """
    _reject_if_history(signal, 'confirmed')

    if signal.origin == InspirationSignal.Origin.USER:
        # Re-confirming a withdrawn preference must not jump the queue. If
        # something newer has since become authoritative, confirming this row
        # would either violate the uniqueness rule outright or — worse, if the
        # rule were ever relaxed — make an OLDER preference authoritative,
        # which is the opposite of "latest wins".
        authority = authoritative_user_signal(
            signal.inspiration, signal.category, signal.attribute
        )
        if authority is not None and authority.pk != signal.pk:
            raise InspirationSignalError(
                "A newer stated preference is authoritative for "
                f"{signal.category}/{signal.attribute}. State a new preference "
                "rather than re-confirming a withdrawn one."
            )

    if signal.origin == InspirationSignal.Origin.AI:
        authority = authoritative_user_signal(
            signal.inspiration, signal.category, signal.attribute
        )
        if signals_conflict(authority, signal):
            supersede(
                authority,
                by=signal,
                reason=SupersessionReason.CONFIRMED_AI_DIRECTION,
            )

    signal.user_confirmation = InspirationSignal.UserConfirmation.CONFIRMED
    signal.confirmed_by = user
    signal.confirmed_at = timezone.now()
    signal.conflicts_with = None
    signal.save(
        update_fields=[
            'user_confirmation', 'confirmed_by', 'confirmed_at', 'conflicts_with',
        ]
    )

    reconcile_attribute(signal.inspiration, signal.category, signal.attribute)
    signal.refresh_from_db()
    _record_signal_evidence(
        signal, user=user, outcome=_outcome_for(signal), action='CONFIRMED'
    )
    return signal


@transaction.atomic
def reject_signal(signal, *, user):
    """A human withdraws a signal.

    Rejecting the current stated preference does not bring the previous one
    back. Supersession is a one-way door: a preference that was replaced stays
    replaced, and the attribute is simply left without a stated preference
    until someone states one. Resurrection would mean the active truth depends
    on the order of past rejections, which is exactly the non-determinism this
    rework removes.
    """
    _reject_if_history(signal, 'rejected')

    signal.user_confirmation = InspirationSignal.UserConfirmation.REJECTED
    signal.confirmed_by = user
    signal.confirmed_at = timezone.now()
    signal.save(update_fields=['user_confirmation', 'confirmed_by', 'confirmed_at'])

    reconcile_attribute(signal.inspiration, signal.category, signal.attribute)
    signal.refresh_from_db()
    # Withdrawing a taste is a judgment about the brand too, and always
    # negative regardless of the sentiment the signal carried.
    from apps.learning.models import LearningEvent

    _record_signal_evidence(
        signal, user=user, outcome=LearningEvent.Outcome.NEGATIVE, action='REJECTED'
    )
    return signal


@transaction.atomic
def record_ai_signal(
    *,
    inspiration,
    category,
    attribute,
    value='',
    sentiment=InspirationSignal.Sentiment.NEUTRAL,
    weight=0.5,
    confidence=0.0,
    provider='',
):
    """Record (or refresh) the inference for one attribute.

    The only writer of `origin=AI`. PR2 ships no analysis; this exists so that
    the integrity rules hold for the first inferred row ever written rather
    than being retrofitted once PR6 has a job.

    Three cases, and the third is the one that matters:

    * The inference has not changed — refresh the incidentals, leave the human
      verdict alone. This is what makes a retried job idempotent.
    * It changed and nobody has ruled on it — rewrite it in place. There is no
      audit value in a trail of unreviewed machine churn.
    * It changed and a human HAS ruled on it — file a new row and supersede the
      old one. Rewriting would leave a CONFIRMED or REJECTED verdict attached
      to content the person never saw, which is the same defect as an
      inference overwriting a preference, one level down.

    A stated preference is never touched on any path.
    """
    if inspiration.lifecycle_status == BrandInspiration.LifecycleStatus.ARCHIVED:
        raise InspirationSignalError("Archived inspirations cannot receive new signals.")

    normalized_value = normalize_signal_text(value)
    existing = active_ai_signal(inspiration, category, attribute)

    if existing is None:
        signal = InspirationSignal.objects.create(
            inspiration=inspiration,
            category=category,
            attribute=attribute,
            value=value,
            sentiment=sentiment,
            weight=weight,
            confidence=confidence,
            origin=InspirationSignal.Origin.AI,
            user_confirmation=InspirationSignal.UserConfirmation.PENDING,
            extracted_by_provider=provider,
        )
    else:
        unchanged = (
            existing.normalized_value == normalized_value
            and existing.sentiment == sentiment
        )
        ruled_on = existing.user_confirmation != InspirationSignal.UserConfirmation.PENDING

        if unchanged or not ruled_on:
            existing.value = value
            existing.sentiment = sentiment
            existing.weight = weight
            existing.confidence = confidence
            existing.extracted_by_provider = provider
            existing.save()
            signal = existing
        else:
            supersede(
                existing,
                by=None,
                reason=SupersessionReason.NEWER_AI_INFERENCE,
            )
            signal = InspirationSignal.objects.create(
                inspiration=inspiration,
                category=category,
                attribute=attribute,
                value=value,
                sentiment=sentiment,
                weight=weight,
                confidence=confidence,
                origin=InspirationSignal.Origin.AI,
                user_confirmation=InspirationSignal.UserConfirmation.PENDING,
                extracted_by_provider=provider,
            )
            link_supersession(existing, signal)

    reconcile_attribute(inspiration, category, attribute)
    signal.refresh_from_db()
    return signal
