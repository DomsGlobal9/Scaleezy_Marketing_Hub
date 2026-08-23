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

from apps.brands.models import Brand
from apps.brands.services.brand_brain import rebuild_brand_brain
from apps.context.services.context_gateway import (
    MOTION_CATEGORIES,
    VISUAL_CATEGORIES,
)
from apps.context.services.generation import (
    NoProviderConfigured,
    generate_copy_and_image,
)
from apps.context.services.readiness import brand_readiness
from apps.inspirations.models import BrandInspiration
from apps.knowledge.models import BrandSource
from apps.learning.models import LearningEvent, SubjectType
from apps.learning.services import record_event, reinforce_preference

from .models import BrandOnboarding, CalibrationDirection

logger = logging.getLogger(__name__)


class CalibrationError(Exception):
    """The requested calibration step cannot be performed."""


class BrandNotApproved(CalibrationError):
    """Calibration is refused until Scaleezy has approved the brand."""


def require_approved_for_calibration(brand):
    """Raise unless the brand may spend on calibration.

    Lives in the service, not the view, so no other caller can reach the
    provider with a brand that is still awaiting approval: calibration makes
    real provider calls and costs real money, and approval is what says that
    spend is ours to incur.
    """
    if brand.status == Brand.Status.PENDING:
        raise BrandNotApproved(
            "This brand is awaiting Scaleezy approval. Calibration unlocks "
            "once it has been approved."
        )
    if brand.status == Brand.Status.ARCHIVED:
        raise BrandNotApproved("This brand is archived; calibration is unavailable.")


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
    # The latest round is the unit of calibration, and it is complete only
    # when EVERY direction in it has a verdict. One click out of three used
    # to complete the stage, which meant two of the three purposeful
    # directions taught nothing and the stage lied about it. Skipping the
    # remainder is still allowed - through the explicit skip, not through
    # silence.
    latest_round = (
        CalibrationDirection.objects.filter(brand=brand)
        .order_by('-created_at')
        .values_list('round_id', flat=True)
        .first()
    )
    has_calibration = bool(latest_round) and not (
        CalibrationDirection.objects.filter(brand=brand, round_id=latest_round)
        .filter(verdict=CalibrationDirection.Verdict.PENDING)
        .exists()
    )
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


def generate_calibration_round(workspace, brand, *, user=None):
    """Three purposeful directions through the real generation chain.

    Gateway → router → configured provider, per direction — and MULTIMODAL:
    each direction runs copy and imagery together, because a direction that
    claims to test layout density or imagery style while showing only a
    sentence of copy has nothing behind the claim. Whether a visual actually
    exists is recorded per direction (`preview_url`), and the verdict path
    refuses to learn visual attributes a direction never displayed.

    Hard rules and verified facts ride in the context exactly as they do for
    a normal generation, because calibration output a brand rule would forbid
    teaches the wrong thing.

    Provider calls run OUTSIDE the transaction - three generations inside an
    open transaction would hold a connection for the slowest provider's
    latency. The rows are then written atomically, so a half-created round is
    never visible.
    """
    require_approved_for_calibration(brand)

    round_id = uuid.uuid4()
    outcomes = []
    for spec in CALIBRATION_DIRECTIONS:
        outcome = generate_copy_and_image(
            workspace, brand, {}, instruction=spec['instruction'],
        )
        if outcome['text'] is None:
            failure = outcome['trace']['capabilities'].get('TEXT', {})
            raise CalibrationError(
                "Calibration direction could not be generated: "
                + failure.get('error', 'the provider returned nothing.')
            )
        outcomes.append((spec, outcome))

    with transaction.atomic():
        directions = []
        for spec, outcome in outcomes:
            text = outcome['text']
            image = outcome['image'] or {}
            raw = text.get('raw') or {}
            directions.append(CalibrationDirection.objects.create(
                workspace=workspace,
                brand=brand,
                round_id=round_id,
                label=spec['label'],
                tests_dimension=spec['tests_dimension'],
                tested_attributes=spec['tested_attributes'],
                headline=(text.get('headline') or raw.get('postTitle', ''))[:500],
                caption=text.get('caption') or raw.get('postDescription', ''),
                hashtags=text.get('hashtags') or raw.get('postHashtags', ''),
                preview_url=(image.get('image_url') or '')[:1000],
                provider=text.get('provider', ''),
                brain_version=outcome['trace']['brain_version'],
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

    # A verdict on a direction is evidence about the dimensions it tested -
    # but only the dimensions the direction actually DISPLAYED. A direction
    # with no visual never showed its layout or imagery, so a verdict on it
    # says nothing about either; learning LAYOUT from a sentence of copy is
    # how a brain fills up with claims nothing ever exhibited.
    visual = VISUAL_CATEGORIES | MOTION_CATEGORIES
    has_visual = bool(direction.preview_url)

    def evidenced_attributes():
        for key, value in (direction.tested_attributes or {}).items():
            category, _, attribute = key.partition('/')
            category = category or 'OTHER'
            if category in visual and not has_visual:
                logger.info(
                    "Skipping %s on calibration %s: no visual was displayed",
                    key, direction.pk,
                )
                continue
            yield key, category, attribute or key, value

    learned = False
    if verdict in (CalibrationDirection.Verdict.LIKED, CalibrationDirection.Verdict.NOT_US):
        sentiment = 'preferred' if verdict == CalibrationDirection.Verdict.LIKED else 'avoided'
        for key, category, attribute, value in evidenced_attributes():
            try:
                reinforce_preference(
                    workspace=direction.workspace,
                    brand=direction.brand,
                    event=event,
                    category=category,
                    attribute=attribute,
                    value=f'{value} ({sentiment})',
                )
                learned = True
            except Exception:
                logger.exception(
                    "Could not reinforce %s from calibration %s", key, direction.pk
                )
    elif verdict == CalibrationDirection.Verdict.ADJUSTED:
        # The correction becomes a soft, traceable preference: one row per
        # dimension the direction displayed, its value the user's words
        # VERBATIM, so the next context for those dimensions carries exactly
        # what was said. It starts EMERGING - one correction is an opinion,
        # and nothing here can mint a rule, hard or otherwise; that path
        # still requires corroborated evidence and goes through the learning
        # service's own gates. The original note is also kept verbatim on
        # the direction row itself.
        note_verbatim = note.strip()[:500]
        for key, category, attribute, _ in evidenced_attributes():
            try:
                reinforce_preference(
                    workspace=direction.workspace,
                    brand=direction.brand,
                    event=event,
                    category=category,
                    attribute=f'{attribute} adjustment',
                    value=note_verbatim,
                )
                learned = True
            except Exception:
                logger.exception(
                    "Could not record adjustment %s from calibration %s",
                    key, direction.pk,
                )

    direction.verdict = verdict
    direction.adjustment_note = note[:2000]
    direction.decided_by = user if (user and user.is_authenticated) else None
    direction.decided_at = timezone.now()
    direction.learning_event_id = event.pk
    direction.save(update_fields=[
        'verdict', 'adjustment_note', 'decided_by', 'decided_at', 'learning_event_id',
    ])

    if learned:
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
        # The client's approval state, so the product can say "awaiting
        # Scaleezy approval, calibration unlocks once approved" instead of
        # letting them discover it by clicking a button that 403s. There is no
        # mail backend, so this is how approval becomes visible at all.
        'brand_status': brand.status,
        'awaiting_approval': brand.status == Brand.Status.PENDING,
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
