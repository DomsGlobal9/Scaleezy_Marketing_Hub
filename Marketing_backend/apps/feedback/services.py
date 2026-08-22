"""
Recording feedback.

One entry point, used both by the review actions on ContentItem and by the
feedback endpoint, so a verdict is captured identically however it arrives.
"""
import logging

from .models import Feedback
from .training import TrainingEngine, infer_sentiment

logger = logging.getLogger(__name__)

#: Maps a ContentItem review status onto the verdict it represents.
VERDICT_FOR_STATUS = {
    'APPROVED': Feedback.Verdict.APPROVE,
    'NEEDS_EDITS': Feedback.Verdict.NEEDS_EDITS,
    'REJECTED': Feedback.Verdict.REJECT,
}


def capture(
    *,
    content_item,
    user=None,
    verdict,
    element_keys=None,
    feedback_text='',
    fix_request='',
    urgency=Feedback.Urgency.NORMAL,
    before_asset=None,
    after_asset=None,
    learn=True,
):
    """
    Stores one verdict and runs the training pass over it.

    Best-effort by design: a reviewer's approval must land even if embedding
    or rule-writing fails, so everything here is caught and logged rather than
    raised back into the review request.
    """
    try:
        feedback = Feedback.objects.create(
            workspace=content_item.workspace,
            content_item=content_item,
            brand=content_item.brand,
            user=user if (user and user.is_authenticated) else None,
            verdict=verdict,
            element_keys=list(element_keys or []),
            feedback_text=feedback_text or '',
            fix_request=fix_request or '',
            sentiment=infer_sentiment(verdict, f"{feedback_text} {fix_request}"),
            urgency=urgency or Feedback.Urgency.NORMAL,
            before_asset=before_asset or content_item.asset,
            after_asset=after_asset,
        )
    except Exception:
        logger.exception("Could not record feedback for content %s", content_item.pk)
        return None

    # The verdict becomes evidence in the learning fabric (PR3) FIRST, because
    # the training pass below cites those events as the support for any rule
    # it infers - a rule whose own evidence had not been written yet could not
    # name what it was learned from. Imported here rather than at module scope
    # to keep the app graph acyclic, and best-effort: a reviewer's verdict must
    # land even if nothing learns from it.
    from apps.learning.adapters import record_feedback_event_safely

    record_feedback_event_safely(feedback)

    if learn:
        try:
            TrainingEngine(feedback).learn()
        except Exception:
            logger.exception("Training pass failed for feedback %s", feedback.pk)

    return feedback
