import logging

from django.tasks import task

logger = logging.getLogger(__name__)


@task
def parse_feedback_elements_task(feedback_id: str):
    """Fill a feedback row's element keys from its words, then learn.

    Runs the training pass that `capture()` deferred: with the keys parsed
    here it fires exactly once per feedback, never twice. Every failure mode
    degrades to "training learns a little less from this one verdict" — the
    verdict itself, the reviewer's words and the queued regeneration all
    landed long before this task ran.
    """
    from .models import Feedback
    from .nl import parse_elements
    from .training import TrainingEngine

    feedback = Feedback.objects.filter(pk=feedback_id).first()
    if feedback is None:
        return {'skipped': 'feedback row is gone'}
    if feedback.element_keys:
        return {'skipped': 'already tagged'}

    try:
        keys = parse_elements(feedback)
    except Exception as exc:
        logger.warning('Feedback %s parse failed: %s', feedback_id, exc)
        keys = []

    if keys:
        feedback.element_keys = keys
        feedback.save(update_fields=['element_keys'])

    try:
        TrainingEngine(feedback).learn()
    except Exception:
        logger.exception('Training pass failed for feedback %s', feedback_id)

    return {'parsed': len(keys), 'elements': keys}
