"""
The only supported way to write an AI-derived inspiration signal.

PR2 ships no analysis pipeline; PR6 does. This exists now because the
integrity rule it enforces — an inference may never quietly replace something
a human stated — has to be true of the very first inferred row ever written,
not retrofitted once a job exists. It is a narrow contract, not an
implementation of PR6.
"""
import logging

from django.db import transaction

from .models import BrandInspiration, InspirationSignal

logger = logging.getLogger(__name__)


class InspirationSignalError(Exception):
    """The requested AI signal cannot be recorded."""


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
    """Record (or refresh) one inferred signal for an inspiration.

    Idempotent on (inspiration, category, attribute): a retried analysis job
    updates the inferred payload in place rather than accumulating duplicates.

    A user-stated signal about the same attribute is never touched. If the
    inference disagrees with it, the inferred row is linked to the stated one
    through `conflicts_with`, which keeps it out of retrieval until a human
    resolves it. Silence would be the bug here: dropping the inference hides a
    real disagreement, and applying it overrides the user.
    """
    if inspiration.lifecycle_status == BrandInspiration.LifecycleStatus.ARCHIVED:
        raise InspirationSignalError("Archived inspirations cannot receive new signals.")

    user_signal = (
        inspiration.signals.filter(
            category=category, attribute=attribute, origin=InspirationSignal.Origin.USER
        )
        .exclude(user_confirmation=InspirationSignal.UserConfirmation.REJECTED)
        .first()
    )

    # Uniqueness is enforced by `uniq_ai_signal_per_inspiration_attribute`
    # rather than by row locking, so this works on every configured backend.
    signal, created = InspirationSignal.objects.get_or_create(
        inspiration=inspiration,
        category=category,
        attribute=attribute,
        origin=InspirationSignal.Origin.AI,
        defaults={
            'value': value,
            'sentiment': sentiment,
            'weight': weight,
            'confidence': confidence,
            'extracted_by_provider': provider,
            'user_confirmation': InspirationSignal.UserConfirmation.PENDING,
        },
    )

    if not created:
        # Refresh the inferred payload, but leave the human verdict alone:
        # re-running analysis must not un-confirm or un-reject a signal a user
        # has already ruled on.
        signal.value = value
        signal.sentiment = sentiment
        signal.weight = weight
        signal.confidence = confidence
        signal.extracted_by_provider = provider

    conflicting = user_signal if user_signal and user_signal.sentiment != sentiment else None
    signal.conflicts_with = conflicting
    signal.save()

    if conflicting is not None:
        logger.info(
            "AI signal %s contradicts user signal %s on inspiration %s; held for review",
            signal.pk, conflicting.pk, inspiration.pk,
        )

    return signal
