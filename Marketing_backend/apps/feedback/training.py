"""
The training engine.

One job: notice when a reviewer objects to the same thing twice, and turn that
into a rule the generator obeys next time.

    embed -> find similar past feedback -> extract the pattern
          -> LEARNED soft rule in the learning fabric -> Brand Brain -> prompt

The last two steps used to be one: the rule was written straight onto
`Brand.creative_brain`. That column is the COMPILED SNAPSHOT owned by
`apps.brands.services.brand_brain`, so every recompile silently deleted
whatever the review loop had learned, and in between recompiles the snapshot's
`brain_version` no longer described its own contents. Rules now go where every
other piece of learned intelligence goes - `learning.BrandRule`, LEARNED and
soft, citing the events it was learned from - and the compiler picks them up
like anything else.

Rules live on the brand, not on the workspace, because taste is a property of
the brand and a workspace can hold several.
"""
import logging
from typing import Any, Dict, List

from .embeddings import cosine, embed
from .models import Feedback, FeedbackElement

logger = logging.getLogger(__name__)

#: Cosine above which two notes are treated as saying the same thing. Tuned
#: for the local hashed embedding, which scores unrelated short notes near 0.
SIMILARITY_THRESHOLD = 0.55

#: How many past items to scan. Bounded so a busy workspace cannot turn one
#: review click into an unbounded query.
SCAN_LIMIT = 500

#: A single complaint is an opinion; the second one is a pattern.
MIN_OCCURRENCES = 2

_NEGATIVE_HINTS = frozenset(
    """not no dont avoid wrong bad poor too never unreadable ugly cluttered off
    missing remove stop hate""".split()
)
_POSITIVE_HINTS = frozenset(
    "good great love perfect nice clean strong exactly".split()
)


def infer_sentiment(verdict: str, text: str) -> str:
    """Cheap lexical read. The verdict dominates; the words break the tie."""
    if verdict == Feedback.Verdict.REJECT:
        return Feedback.Sentiment.NEGATIVE

    words = set((text or '').lower().replace("'", '').split())
    if verdict == Feedback.Verdict.APPROVE:
        return (
            Feedback.Sentiment.NEGATIVE
            if words & _NEGATIVE_HINTS
            else Feedback.Sentiment.POSITIVE
        )
    if words & _NEGATIVE_HINTS:
        return Feedback.Sentiment.NEGATIVE
    if words & _POSITIVE_HINTS:
        return Feedback.Sentiment.POSITIVE
    return Feedback.Sentiment.NEUTRAL


def feedback_text_for_embedding(feedback: Feedback) -> str:
    """
    What actually gets vectorised: the tagged elements plus both free-text
    fields. Including the element keys means two notes worded differently but
    tagged the same still land near each other.
    """
    parts = [
        ' '.join(feedback.element_keys or []),
        feedback.feedback_text or '',
        feedback.fix_request or '',
    ]
    return ' '.join(p for p in parts if p).strip()


def element_labels(keys: List[str]) -> Dict[str, Dict[str, str]]:
    """Maps element keys to their label and group, for readable rule text."""
    rows = FeedbackElement.objects.filter(key__in=list(keys or []))
    return {row.key: {'label': row.label, 'group': row.get_group_display()} for row in rows}


class TrainingEngine:
    """Learns from one piece of feedback at a time."""

    def __init__(self, feedback: Feedback):
        self.feedback = feedback

    # -- entry point ------------------------------------------------------
    def learn(self) -> Dict[str, Any]:
        """
        Embeds, looks for repetition, and writes any rules earned. Returns the
        extracted pattern and persists it onto the feedback row.
        """
        feedback = self.feedback

        text = feedback_text_for_embedding(feedback)
        vector, model = embed(text, workspace=feedback.workspace)
        feedback.embedding = vector
        feedback.embedding_model = model

        similar = self._similar(vector)
        pattern = self._extract_pattern(similar)
        feedback.pattern_extracted = pattern

        feedback.rules_updated = self._apply_rules(pattern)

        feedback.save(
            update_fields=[
                'embedding', 'embedding_model', 'pattern_extracted', 'rules_updated',
            ]
        )
        return pattern

    # -- similarity -------------------------------------------------------
    def _similar(self, vector: List[float]) -> List[Dict[str, Any]]:
        """
        Past feedback in this workspace that says roughly the same thing.

        Only corrective verdicts are compared: an approval and a rejection can
        be worded almost identically ("the logo") and must not reinforce each
        other into a rule.
        """
        feedback = self.feedback
        if not feedback.is_corrective:
            return []

        candidates = (
            Feedback.objects.filter(
                workspace_id=feedback.workspace_id,
                verdict__in=list(Feedback.CORRECTIVE),
            )
            .exclude(pk=feedback.pk)
            .order_by('-created_at')[:SCAN_LIMIT]
        )

        out = []
        for other in candidates:
            score = cosine(vector, other.embedding or [])
            shared = set(feedback.element_keys or []) & set(other.element_keys or [])
            # Either route counts: near-identical wording, or the same element
            # tagged twice. Tags are the stronger signal but are optional.
            if score >= SIMILARITY_THRESHOLD or shared:
                out.append({
                    'id': str(other.pk),
                    'similarity': round(score, 4),
                    'shared_elements': sorted(shared),
                    'verdict': other.verdict,
                    'created_at': other.created_at.isoformat(),
                })
        return out

    # -- pattern ----------------------------------------------------------
    def _extract_pattern(self, similar: List[Dict[str, Any]]) -> Dict[str, Any]:
        feedback = self.feedback
        occurrences = len(similar) + 1  # this one included

        # An element is "recurring" once it has been raised on a previous
        # piece of content too.
        counts: Dict[str, int] = {key: 1 for key in feedback.element_keys or []}
        for match in similar:
            for key in match['shared_elements']:
                counts[key] = counts.get(key, 0) + 1

        recurring = sorted(k for k, n in counts.items() if n >= MIN_OCCURRENCES)

        return {
            'occurrences': occurrences,
            'recurring_elements': recurring,
            'element_counts': counts,
            'similar_feedback': similar[:10],
            'similarity_source': feedback.embedding_model,
            'is_pattern': bool(recurring),
        }

    # -- rules ------------------------------------------------------------
    def _supporting_feedback(self, pattern: Dict[str, Any], key: str) -> List[Feedback]:
        """This feedback plus the past rows that raised the same element.

        The rows are the evidence; their LearningEvents are what the rule
        actually cites, so "why does this rule exist" resolves to specific
        reviews rather than to a number.
        """
        ids = [
            match['id']
            for match in pattern.get('similar_feedback') or []
            if key in (match.get('shared_elements') or [])
        ]
        rows = [self.feedback]
        if ids:
            rows.extend(
                Feedback.objects.filter(
                    workspace_id=self.feedback.workspace_id, pk__in=ids
                )
            )
        return rows

    def _apply_rules(self, pattern: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Turns a repeated objection into a LEARNED soft rule in the fabric.

        Nothing is written for a first-time complaint -- that is the whole
        point of MIN_OCCURRENCES. Rules are keyed by element, so a third
        rejection sharpens the existing rule instead of adding a duplicate.
        The Brand Brain is recompiled afterwards so the next generation is cut
        from a snapshot that already contains the rule.
        """
        from apps.brands.services.brand_brain import rebuild_brand_brain_safely
        from apps.learning.adapters import events_for_feedback
        from apps.learning.services import LearningError, upsert_learned_rule

        feedback = self.feedback
        brand = feedback.brand
        if brand is None or not feedback.is_corrective or not pattern.get('is_pattern'):
            return []

        recurring = pattern.get('recurring_elements') or []
        if not recurring:
            return []

        labels = element_labels(recurring)
        instruction = (feedback.fix_request or feedback.feedback_text or '').strip()
        written = []

        for key in recurring:
            meta = labels.get(key, {})
            label = meta.get('label') or key.replace('_', ' ')
            group = meta.get('group', '')
            occurrences = max(
                int(pattern['element_counts'].get(key, MIN_OCCURRENCES)), MIN_OCCURRENCES
            )
            text = self._rule_text(label, instruction, occurrences)
            support = self._supporting_feedback(pattern, key)

            try:
                rule = upsert_learned_rule(
                    workspace=feedback.workspace,
                    brand=brand,
                    key=f'review:{key}',
                    text=text,
                    evidence_events=events_for_feedback(support),
                    # Confidence grows with corroboration but never reaches
                    # certainty: this is still an inference.
                    confidence=min(0.9, 0.5 + 0.1 * (occurrences - MIN_OCCURRENCES)),
                    structured={
                        'source': 'review_feedback',
                        'element': key,
                        'label': label,
                        'group': group,
                        'occurrences': occurrences,
                        'category': REVIEW_CLAIM_CATEGORY,
                        'attribute': key,
                        'value': text,
                        'source_feedback_ids': sorted({str(r.pk) for r in support})[:20],
                    },
                )
            except LearningError as exc:
                # Honest silence beats a rule with nothing behind it.
                logger.info(
                    "Training: no rule for %s on brand %s - %s", key, brand.pk, exc
                )
                continue

            written.append({
                'element': key,
                'text': rule.text,
                'occurrences': occurrences,
            })

        if written:
            rebuild_brand_brain_safely(brand)
            logger.info(
                "Training: brand %s learned %d rule(s) from feedback %s",
                brand.pk, len(written), feedback.pk,
            )
        return written

    @staticmethod
    def _rule_text(label: str, instruction: str, occurrences: int) -> str:
        base = f"{label}: reviewers have rejected this {occurrences} times."
        return f"{base} {instruction}".strip() if instruction else base


#: Claim category for a rule inferred from review feedback. Its own category
#: so a review objection about "logo placement" cannot collide with a stated
#: visual preference keyed the same way.
REVIEW_CLAIM_CATEGORY = 'REVIEW'


# -- read side ------------------------------------------------------------
def learned_rules(brand):
    """Active rules this engine has inferred for a brand, freshest first."""
    from apps.learning.models import BrandRule

    if brand is None:
        return []
    return [
        rule
        for rule in BrandRule.objects.filter(
            workspace_id=brand.workspace_id, brand=brand,
            origin=BrandRule.Origin.LEARNED, is_active=True,
        ).order_by('-updated_at')
        if isinstance(rule.structured, dict)
        and rule.structured.get('source') == 'review_feedback'
    ]


def rules_for_prompt(brand, limit: int = 12) -> List[str]:
    """The learned rules, as plain instruction lines.

    Reads the fabric, not the compiled snapshot. Generation itself goes
    through the Context Gateway, which reads the same rules out of the Brand
    Brain; this stays for callers that want the raw lines.
    """
    return [rule.text for rule in learned_rules(brand)[:limit] if rule.text]


def training_report(workspace, brand=None) -> Dict[str, Any]:
    """
    What the engine has learned, for the console: volume, the elements that
    come up most, and the rules currently in force.
    """
    from apps.brands.models import Brand

    totals = {v: 0 for v in Feedback.Verdict.values}
    element_counts: Dict[str, int] = {}

    rows = Feedback.objects.filter(workspace=workspace).values_list('verdict', 'element_keys')
    for verdict, keys in rows:
        totals[verdict] = totals.get(verdict, 0) + 1
        for key in keys or []:
            element_counts[key] = element_counts.get(key, 0) + 1

    if brand is None:
        brand = Brand.objects.filter(workspace=workspace).order_by('-is_default').first()

    labels = element_labels(list(element_counts))
    top = sorted(element_counts.items(), key=lambda kv: -kv[1])[:10]

    inferred = learned_rules(brand)
    rules = [
        {
            'element': rule.structured.get('element', ''),
            'label': rule.structured.get('label', ''),
            'group': rule.structured.get('group', ''),
            'text': rule.text,
            'occurrences': rule.structured.get('occurrences', 0),
            'evidence_event_ids': rule.evidence_event_ids,
        }
        for rule in inferred
    ]
    rules_updated_at = (
        max(rule.updated_at for rule in inferred).isoformat() if inferred else ''
    )

    return {
        'total_feedback': sum(totals.values()),
        'by_verdict': totals,
        'top_elements': [
            {
                'key': key,
                'label': labels.get(key, {}).get('label', key),
                'group': labels.get(key, {}).get('group', ''),
                'count': count,
            }
            for key, count in top
        ],
        'brand': str(brand.pk) if brand else None,
        'brand_name': brand.name if brand else '',
        'rules': rules,
        'rules_updated_at': rules_updated_at,
    }
