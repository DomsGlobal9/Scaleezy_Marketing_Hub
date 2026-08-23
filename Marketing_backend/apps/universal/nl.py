"""
Natural-language input — proposals, never silent writes.

Somebody types "we never discount, and our tone is warm but not cutesy".
Today that has nowhere to go except three separate forms. This turns it into
typed *proposal cards* the person then confirms, and only the confirmation
writes anything.

Two rules make this safe rather than magic:

1. **The raw text is kept verbatim, first.** Before any parse, the sentence is
   stored as a note. If the parse is wrong, misses something, or the provider
   is down, what the person said is still there and can be re-parsed later.
   A parser that loses the input is worse than no parser.

2. **Nothing persists without a human tap.** A parse proposes; a person
   accepts. In particular a parse may never mint a HARD rule, because a hard
   rule is the one thing that silently blocks generation, and a
   misunderstanding that blocks generation is indistinguishable from an outage.

Parsing is a provider call, so it is subject to the approval gate and the
quota like everything else.
"""
import json
import logging
import re

from django.db import transaction

logger = logging.getLogger(__name__)

MAX_NOTE_CHARS = 4000
MAX_PROPOSALS = 12


class NLError(Exception):
    """The note could not be turned into proposals."""


#: What a proposal may become. Deliberately excludes a hard rule — see above.
PROPOSAL_KINDS = ('FACT', 'PREFERENCE', 'SOFT_RULE', 'AUDIENCE', 'TONE')


def capture_note(brand, text, *, user=None):
    """Store what the person said, verbatim, before anything interprets it.

    A `BrandSource` of type NOTE rather than a new table: it already carries
    provenance, archival and the brand/workspace scoping, and it means a note
    can later be revoked exactly like an uploaded document — with everything
    derived from it recompiled without it.
    """
    from apps.knowledge.models import BrandSource

    cleaned = (text or '').strip()[:MAX_NOTE_CHARS]
    if not cleaned:
        raise NLError("There is nothing to record.")

    return BrandSource.objects.create(
        workspace=brand.workspace,
        brand=brand,
        source_type=BrandSource.SourceType.OTHER,
        title=(cleaned[:60] + ('…' if len(cleaned) > 60 else '')),
        raw_text=cleaned,
        status=BrandSource.SourceStatus.READY,
        metadata={'origin': 'NATURAL_LANGUAGE_NOTE'},
        created_by=user,
    )


PARSE_INSTRUCTION = (
    "Extract discrete brand facts and preferences from the user's note. "
    "Return STRICT JSON: {\"proposals\":[{\"kind\":\"FACT|PREFERENCE|SOFT_RULE|"
    "AUDIENCE|TONE\",\"category\":\"\",\"attribute\":\"\",\"value\":\"\","
    "\"text\":\"\",\"quote\":\"\"}]}. "
    "`quote` MUST be the exact substring of the note this came from. "
    "Extract nothing that is not stated. Never invent. If the note states "
    "nothing extractable, return an empty list."
)


def _coerce(payload):
    """Accept the provider's answer only in the shape we asked for."""
    if isinstance(payload, str):
        # Providers wrap JSON in prose or fences more often than not.
        match = re.search(r'\{.*\}', payload, re.S)
        if not match:
            return []
        try:
            payload = json.loads(match.group(0))
        except ValueError:
            return []
    if not isinstance(payload, dict):
        return []
    raw = payload.get('proposals')
    return raw if isinstance(raw, list) else []


def propose_from_note(workspace, brand, note, *, user=None):
    """Parse one note into proposal cards. Writes nothing but the note.

    Every proposal carries the exact quote it came from, and a quote that is
    not actually in the note is dropped — the cheapest available guard against
    a provider inventing a fact and attributing it to the user.
    """
    from apps.ai.models import Capability
    from apps.ai.router import AIRouter, NoProviderAvailable

    text = note.raw_text or ''
    try:
        result = AIRouter(workspace).dispatch(
            Capability.TEXT,
            {
                'task': 'EXTRACT',
                'instruction': PARSE_INSTRUCTION,
                'brand_context': [f"Note: {text}"],
                'structured': {'note': text},
            },
        )
    except NoProviderAvailable as exc:
        raise NLError(str(exc)) from exc

    candidates = _coerce(result.get('raw') or result.get('headline') or result)

    haystack = text.casefold()
    proposals = []
    for item in candidates[:MAX_PROPOSALS]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get('kind', '')).upper()
        if kind not in PROPOSAL_KINDS:
            continue
        quote = str(item.get('quote', '')).strip()
        # Refuse anything the note does not actually say.
        if not quote or quote.casefold() not in haystack:
            logger.info("Dropped ungrounded NL proposal for brand %s", brand.pk)
            continue
        proposals.append({
            'kind': kind,
            'category': str(item.get('category', ''))[:64],
            'attribute': str(item.get('attribute', ''))[:64],
            'value': str(item.get('value', ''))[:255],
            'text': str(item.get('text', ''))[:500],
            'quote': quote[:500],
            # Nothing is written yet. The client taps to accept.
            'accepted': False,
        })

    return {
        'note_id': str(note.pk),
        'note_text': text,
        'proposals': proposals,
        'provider': result.get('provider', ''),
        'note': (
            'Nothing has been saved to your brand yet. Accept the cards you '
            'agree with.'
        ),
    }


@transaction.atomic
def accept_proposal(workspace, brand, proposal, *, note=None, user=None):
    """Turn one confirmed card into the real record it implies.

    Routed to the service that already owns each kind, so a proposal accepted
    here is indistinguishable from the same thing typed into its own form —
    including its authority rank and its provenance.
    """
    from apps.knowledge.models import BrandMemory
    from apps.learning.models import BrandRule
    from apps.learning.services import create_explicit_rule

    kind = str(proposal.get('kind', '')).upper()
    if kind not in PROPOSAL_KINDS:
        raise NLError(f"Unknown proposal kind: {kind}")

    if kind in ('FACT', 'AUDIENCE'):
        return BrandMemory.objects.create(
            workspace=workspace,
            brand=brand,
            source=note,
            memory_type=BrandMemory.MemoryType.FACT,
            content=proposal.get('text') or proposal.get('value', ''),
            # CONFIRMED, because a person just read it and tapped accept —
            # that is exactly what confirmation means here.
            status=BrandMemory.MemoryStatus.CONFIRMED,
            confidence=1.0,
        )

    if kind in ('PREFERENCE', 'TONE', 'SOFT_RULE'):
        # SOFT, never HARD. A hard rule blocks generation, and a parse is not
        # allowed to do that on somebody's behalf.
        return create_explicit_rule(
            workspace=workspace,
            brand=brand,
            text=proposal.get('text') or proposal.get('value', ''),
            hardness=BrandRule.Hardness.SOFT,
            created_by=user,
        )

    raise NLError(f"Nothing to write for kind {kind}")
