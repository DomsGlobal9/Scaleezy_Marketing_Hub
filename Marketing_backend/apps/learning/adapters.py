"""
Bridging the existing feedback engine into the learning fabric.

`apps.feedback.capture()` keeps doing exactly what it did — write a Feedback
row, run the training pass. This adds one more thing alongside it: the same
verdict recorded as a `LearningEvent`, so the fabric sees corrective feedback
from day one instead of starting empty and waiting for new sources.

Deliberately additive. Nothing on the feedback read side changes, the training
engine is untouched, and a failure here is logged rather than raised — a
reviewer's approval must land even if the fabric write does not.
"""
import logging

from .models import LearningEvent, SubjectType
from .services import record_event

logger = logging.getLogger(__name__)


def _verdict_map():
    """Verdict -> (event type, outcome). Imported lazily to keep the app graph
    acyclic: feedback calls into learning, so learning must not need feedback
    at import time."""
    from apps.feedback.models import Feedback

    return {
        Feedback.Verdict.APPROVE: (
            LearningEvent.EventType.APPROVED,
            LearningEvent.Outcome.POSITIVE,
        ),
        Feedback.Verdict.NEEDS_EDITS: (
            LearningEvent.EventType.EDITED,
            LearningEvent.Outcome.NEGATIVE,
        ),
        Feedback.Verdict.REJECT: (
            LearningEvent.EventType.REJECTED,
            LearningEvent.Outcome.NEGATIVE,
        ),
    }


def record_feedback_event(feedback):
    """Mirror one Feedback row into the fabric.

    Positive verdicts are captured too. The old engine only learned from
    complaints, which is why a brand could be told a hundred times what to
    stop doing and never once what to keep doing.

    Idempotent on the feedback id, so a retry cannot double-count one review.
    """
    event_type, outcome = _verdict_map().get(
        feedback.verdict,
        (LearningEvent.EventType.EDITED, LearningEvent.Outcome.NEUTRAL),
    )

    return record_event(
        workspace=feedback.workspace,
        brand=feedback.brand,
        event_type=event_type,
        outcome=outcome,
        subject_type=SubjectType.CONTENT_ITEM,
        subject_id=feedback.content_item_id,
        source_type=SubjectType.FEEDBACK,
        source_id=feedback.pk,
        context={
            'verdict': feedback.verdict,
            'element_keys': list(feedback.element_keys or []),
            'sentiment': feedback.sentiment,
            'urgency': feedback.urgency,
            'has_fix_request': bool(feedback.fix_request),
        },
        dedupe_key=f'feedback:{feedback.pk}',
        created_by=feedback.user,
    )


def record_feedback_event_safely(feedback):
    """Best-effort wrapper for the review path.

    Same contract the training pass already has in `apps.feedback.services`:
    the verdict is the thing that must land, and everything learned from it is
    secondary.
    """
    try:
        return record_feedback_event(feedback)
    except Exception:
        logger.exception(
            "Could not record a learning event for feedback %s", feedback.pk
        )
        return None


def events_for_feedback(feedback_rows):
    """The LearningEvents behind a set of Feedback rows, creating any missing.

    `record_feedback_event` is idempotent on the feedback id, so this is safe
    to call for rows that already have an event — and it means feedback
    written before the fabric existed can still stand as evidence rather than
    silently counting for nothing.
    """
    events = []
    for feedback in feedback_rows:
        existing = LearningEvent.objects.filter(
            workspace_id=feedback.workspace_id, dedupe_key=f'feedback:{feedback.pk}'
        ).first()
        if existing is None:
            existing = record_feedback_event_safely(feedback)
        if existing is not None:
            events.append(existing)
    return events
