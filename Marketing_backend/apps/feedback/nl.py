"""
Natural-language feedback → vocabulary element keys.

The reviewer types what is wrong the way they would tell a person, and the
machine maps those words onto the training vocabulary. This replaces asking
the reviewer to tap the right chips out of 56 — a vocabulary that includes
'composition balance' and 'Line 7', which no salon owner should need to know.

The words themselves already drive the regeneration verbatim; this parse
exists purely so the training engine keeps receiving the structured element
keys it aggregates. It runs in the worker, after the reviewer's verdict has
landed — a slow or failed parse can never cost a review.
"""
import json
import logging

logger = logging.getLogger(__name__)

MAX_PARSED_ELEMENTS = 6

PARSE_INSTRUCTION = (
    "You map one reviewer's feedback about a marketing creative onto a fixed "
    "vocabulary of feedback elements. Respond with ONLY a JSON array of "
    "element keys (strings) from the vocabulary below that the feedback "
    "clearly refers to, most relevant first, at most {cap}. Respond with [] "
    "if nothing clearly matches. Never invent keys, never explain.\n\n"
    "VOCABULARY (key: meaning):\n{vocab}"
)


def _coerce_keys(payload):
    """Whatever shape the provider returned, out come candidate strings."""
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith('```'):
            text = text.strip('`')
            if text.startswith('json'):
                text = text[4:]
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return []
    if isinstance(payload, dict):
        payload = payload.get('elements') or payload.get('keys') or []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, str)]


def parse_elements(feedback) -> list:
    """Map one feedback row's words onto known element keys. May raise."""
    from apps.ai.models import Capability
    from apps.ai.router import AIRouter

    from .models import FeedbackElement

    text = ' '.join(f"{feedback.feedback_text} {feedback.fix_request}".split())
    if not text:
        return []
    rows = list(
        FeedbackElement.objects.filter(is_active=True).values_list('key', 'label')
    )
    if not rows:
        return []

    vocab = '\n'.join(f"{key}: {label}" for key, label in rows)
    result = AIRouter(feedback.workspace).dispatch(
        Capability.TEXT,
        {
            'task': 'EXTRACT',
            'instruction': PARSE_INSTRUCTION.format(
                cap=MAX_PARSED_ELEMENTS, vocab=vocab
            ),
            'brand_context': [f"Reviewer feedback: {text}"],
            'structured': {'feedback': text},
        },
        internal=True,
    )

    candidates = _coerce_keys(
        result.get('raw') or result.get('headline') or result
        if isinstance(result, dict) else result
    )
    known = {key for key, _ in rows}
    keys = []
    for candidate in candidates:
        cleaned = candidate.strip()
        if cleaned in known and cleaned not in keys:
            keys.append(cleaned)
    return keys[:MAX_PARSED_ELEMENTS]
