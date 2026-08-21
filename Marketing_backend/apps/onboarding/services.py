"""
Onboarding orchestration, calibration, and the learning loop that closes it.

Nothing in here owns intelligence. Knowledge, inspirations, learning and the
brain all belong to their own apps; this module sequences them and turns a
calibration click into the PR3 write it implies. Stage is derived from what
actually exists rather than advanced by clicks, so progress made anywhere in
the product counts here too.
"""
import logging
import uuid

from django.db import transaction
from django.utils import timezone

from apps.brands.services.brand_brain import rebuild_brand_brain
from apps.context.services.context_gateway import TaskType
from apps.context.services.generation import NoProviderConfigured, generate_with_context
from apps.context.services.readiness import brand_readiness
from apps.inspirations.models import BrandInspiration
from apps.knowledge.models import BrandSource
from apps.learning.models import LearningEvent, SubjectType
from apps.learning.services import record_event, reinforce_preference

from .models import BrandOnboarding, CalibrationDirection

logger = logging.getLogger(__name__)


class CalibrationError(Exception):
    """The requested calibration step cannot be performed."""


# ---------------------------------------------------------------- orchestration

def ensure_onboarding(brand):
    """The orchestration row for a brand, created on first touch."""
    onboarding, _ = BrandOnboarding.objects.get_or_create(
        brand=brand, defaults={'workspace': brand.workspace}
    )
    return onboarding


def refresh_stage(onboarding):
    """Derive stage and status from what actually exists.

    A user who uploaded knowledge from the Knowledge tab has done the
    knowledge stage, whether or not onboarding was open at the time. Skipped
    stages stay behind; completed work can never be un-progressed by a skip.
    """
    brand = onboarding.brand
    skipped = set(onboarding.skipped_steps or [])

    has_basics = bool(brand.name and (brand.industry or brand.tagline))
    has_knowledge = BrandSource.objects.filter(brand=brand).exclude(
        status=BrandSource.SourceStatus.ARCHIVED
    ).exists()
    has_inspirations = (
        BrandInspiration.objects.filter(brand=brand).eligible_for_retrieval().exists()
    )
    has_calibration = CalibrationDirection.objects.filter(brand=brand).exclude(
        verdict=CalibrationDirection.Verdict.PENDING
    ).exists()
    has_generated = brand.content_items.exists()

    stages = [
        (BrandOnboarding.Stage.BASICS, has_basics),
        (BrandOnboarding.Stage.KNOWLEDGE, has_knowledge),
        (BrandOnboarding.Stage.INSPIRATIONS, has_inspirations),
        (BrandOnboarding.Stage.CALIBRATION, has_calibration),
        (BrandOnboarding.Stage.FIRST_GENERATION, has_generated),
    ]

    current = BrandOnboarding.Stage.DONE
    for stage, done in stages:
        if not done and stage not in skipped:
            current = stage
            break

    if has_generated:
        status = BrandOnboarding.Status.COMPLETED
    elif current in (BrandOnboarding.Stage.FIRST_GENERATION, BrandOnboarding.Stage.DONE):
        status = BrandOnboarding.Status.READY_FOR_GENERATION
    elif any(done for _, done in stages):
        status = BrandOnboarding.Status.IN_PROGRESS
    else:
        status = BrandOnboarding.Status.NOT_STARTED

    changed = (
        onboarding.current_stage != current or onboarding.status != status
    )
    onboarding.current_stage = current
    onboarding.status = status
    if status == BrandOnboarding.Status.COMPLETED and onboarding.completed_at is None:
        onboarding.completed_at = timezone.now()
        changed = True
    if changed:
        onboarding.save()
    return onboarding


def skip_stage(onboarding, stage):
    """Skipping is allowed everywhere generation stays possible."""
    valid = {choice for choice, _ in BrandOnboarding.Stage.choices}
    if stage not in valid:
        raise CalibrationError(f"Unknown stage: {stage}")
    if stage == BrandOnboarding.Stage.BASICS:
        raise CalibrationError(
            "Brand basics cannot be skipped; generation needs a brand identity."
        )
    skipped = set(onboarding.skipped_steps or [])
    skipped.add(stage)
    onboarding.skipped_steps = sorted(skipped)
    onboarding.save(update_fields=['skipped_steps', 'last_activity_at'])
    return refresh_stage(onboarding)


# ----------------------------------------------------------------- calibration

#: The three directions, and what each deliberately tests. Not random
#: variants: each pushes one creative dimension so a verdict teaches
#: something specific.
CALIBRATION_DIRECTIONS = [
    {
        'label': 'A',
        'tests_dimension': 'minimal_restrained',
        'instruction': (
            'Minimal and restrained: generous white space, short copy, one '
            'quiet call to action.'
        ),
        'tested_attributes': {
            'LAYOUT/density': 'minimal',
            'COPY_STYLE/length': 'short',
            'CTA/register': 'soft',
        },
    },
    {
        'label': 'B',
        'tests_dimension': 'expressive_editorial',
        'instruction': (
            'Expressive and editorial: bold type, rich imagery, a voice with '
            'personality.'
        ),
        'tested_attributes': {
            'LAYOUT/density': 'expressive',
            'TONE/register': 'editorial',
            'IMAGERY/style': 'rich',
        },
    },
    {
        'label': 'C',
        'tests_dimension': 'conversion_focused',
        'instruction': (
            'Conversion-focused: benefit-led headline, clear offer, direct '
            'call to action.'
        ),
        'tested_attributes': {
            'COPY_STYLE/structure': 'benefit-led',
            'CTA/register': 'direct',
            'HOOK/type': 'offer',
        },
    },
]


@transaction.atomic
def generate_calibration_round(workspace, brand, *, user=None):
    """Three purposeful directions through the real generation chain.

    Gateway → router → configured provider, per direction. Hard rules and
    verified facts ride in the context exactly as they do for a normal
    generation, because calibration output a brand rule would forbid teaches
    the wrong thing.
    """
    round_id = uuid.uuid4()
    directions = []
    for spec in CALIBRATION_DIRECTIONS:
        try:
            outcome = generate_with_context(
                workspace, brand, TaskType.COPY, instruction=spec['instruction'],
            )
        except NoProviderConfigured:
            raise
        result = outcome['result']
        raw = result.get('raw') or {}
        directions.append(CalibrationDirection.objects.create(
            workspace=workspace,
            brand=brand,
            round_id=round_id,
            label=spec['label'],
            tests_dimension=spec['tests_dimension'],
            tested_attributes=spec['tested_attributes'],
            headline=(result.get('headline') or raw.get('postTitle', ''))[:500],
            caption=result.get('caption') or raw.get('postDescription', ''),
            hashtags=result.get('hashtags') or raw.get('postHashtags', ''),
            preview_url=(raw.get('posterImageUrl') or result.get('image_url', ''))[:1000],
            provider=result.get('provider', ''),
            brain_version=outcome['brain_version'],
        ))
    return directions


@transaction.atomic
def record_calibration_verdict(direction, verdict, *, user=None, note=''):
    """One verdict, idempotently, and the learning it implies.

    A repeated click returns what already happened rather than doubling the
    evidence — the LearningEvent dedupe key is the direction id, and the
    preference layer already refuses to count one event twice.

    Returns (direction, learned) where `learned` says whether persistent
    learning actually occurred — the UI only says "Scaleezy learned from your
    choice" when it did.
    """
    if verdict not in (
        CalibrationDirection.Verdict.LIKED,
        CalibrationDirection.Verdict.NOT_US,
        CalibrationDirection.Verdict.ADJUSTED,
    ):
        raise CalibrationError(f"Unknown verdict: {verdict}")
    if verdict == CalibrationDirection.Verdict.ADJUSTED and not note.strip():
        raise CalibrationError("Adjust needs a short note saying what to change.")

    if direction.verdict != CalibrationDirection.Verdict.PENDING:
        # Already decided. Retries and double-clicks land here.
        return direction, False

    outcome = {
        CalibrationDirection.Verdict.LIKED: LearningEvent.Outcome.POSITIVE,
        CalibrationDirection.Verdict.NOT_US: LearningEvent.Outcome.NEGATIVE,
        CalibrationDirection.Verdict.ADJUSTED: LearningEvent.Outcome.MIXED,
    }[verdict]

    event = record_event(
        workspace=direction.workspace,
        brand=direction.brand,
        event_type=LearningEvent.EventType.PREFERENCE_SIGNAL,
        outcome=outcome,
        subject_type=SubjectType.OTHER,
        subject_id=direction.pk,
        context={
            'calibration_round': str(direction.round_id),
            'direction': direction.label,
            'tests_dimension': direction.tests_dimension,
            'verdict': verdict,
            'note': note[:500],
        },
        dedupe_key=f'calibration:{direction.pk}',
        created_by=user,
    )

    # A verdict on a direction is evidence about the dimensions it tested.
    # LIKED reinforces them as stated; NOT_US reinforces the aversion; ADJUST
    # records the event with the correction and reinforces nothing on its own
    # (the note is a instruction to a person or a later pass, not a preference
    # the system can safely invert).
    learned = False
    if verdict in (CalibrationDirection.Verdict.LIKED, CalibrationDirection.Verdict.NOT_US):
        sentiment = 'preferred' if verdict == CalibrationDirection.Verdict.LIKED else 'avoided'
        for key, value in (direction.tested_attributes or {}).items():
            category, _, attribute = key.partition('/')
            try:
                reinforce_preference(
                    workspace=direction.workspace,
                    brand=direction.brand,
                    event=event,
                    category=category or 'OTHER',
                    attribute=attribute or key,
                    value=f'{value} ({sentiment})',
                )
                learned = True
            except Exception:
                logger.exception(
                    "Could not reinforce %s from calibration %s", key, direction.pk
                )

    direction.verdict = verdict
    direction.adjustment_note = note[:2000]
    direction.decided_by = user if (user and user.is_authenticated) else None
    direction.decided_at = timezone.now()
    direction.learning_event_id = event.pk
    direction.save(update_fields=[
        'verdict', 'adjustment_note', 'decided_by', 'decided_at', 'learning_event_id',
    ])

    if learned or verdict == CalibrationDirection.Verdict.ADJUSTED:
        # The brain and readiness must reflect the new evidence immediately —
        # this is the before/after the user is shown.
        rebuild_brand_brain(direction.brand)

    return direction, learned


def onboarding_summary(brand):
    """Everything the onboarding screen needs in one payload."""
    onboarding = refresh_stage(ensure_onboarding(brand))
    readiness = brand_readiness(brand)
    latest_round = (
        CalibrationDirection.objects.filter(brand=brand)
        .order_by('-created_at')
        .values_list('round_id', flat=True)
        .first()
    )
    directions = (
        CalibrationDirection.objects.filter(brand=brand, round_id=latest_round)
        if latest_round else CalibrationDirection.objects.none()
    )
    return {
        'onboarding': {
            'current_stage': onboarding.current_stage,
            'status': onboarding.status,
            'skipped_steps': onboarding.skipped_steps,
            'started_at': onboarding.started_at.isoformat(),
            'completed_at': (
                onboarding.completed_at.isoformat() if onboarding.completed_at else None
            ),
        },
        'readiness': readiness,
        'calibration': [
            {
                'id': str(d.pk),
                'label': d.label,
                'tests_dimension': d.tests_dimension,
                'headline': d.headline,
                'caption': d.caption,
                'preview_url': d.preview_url,
                'verdict': d.verdict,
                'adjustment_note': d.adjustment_note,
            }
            for d in directions
        ],
    }
