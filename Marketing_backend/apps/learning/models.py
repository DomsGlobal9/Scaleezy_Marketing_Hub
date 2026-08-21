"""
The learning fabric.

`apps.feedback` already learns, but only from correction: a reviewer objects,
the training engine notices the objection twice, a rule appears on the brand.
That misses most of what a brand teaches you — an approval, a published post
that did well, a memory someone confirmed, a preference stated against an
inspiration. All of those are evidence, and none of them had anywhere to go.

Three records, with a deliberate gap between them:

* `LearningEvent` — something happened. Append-only, never edited. It is the
  evidence, so a rule can always name what it was learned from.
* `BrandPreference` — a leaning, with a count of how much evidence is behind
  it. Emerging until the evidence accumulates.
* `BrandRule` — an instruction the generator obeys.

The gap matters. One reviewer disliking one headline is an opinion, not a
rule, and the fastest way to poison a brand brain is to let a single event
become a permanent instruction. Evidence accumulates into a preference;
preferences with enough behind them can back a soft rule; only a human stating
one explicitly can create a hard rule.

Nothing here aggregates across tenants. `eligibility_for_aggregate_learning`
records whether a workspace has agreed its evidence may be used that way, and
defaults to no.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class LearningScope(models.TextChoices):
    """How far a rule or preference reaches."""

    ASSET = 'ASSET', 'This asset only'
    CAMPAIGN = 'CAMPAIGN', 'This campaign'
    BRAND = 'BRAND', 'The whole brand'
    TENANT = 'TENANT', 'Every brand in the workspace'


class SubjectType(models.TextChoices):
    """What a learning event is about.

    Soft references by design — a subject can live in any app, and an FK per
    app would make this table a junction of everything. The type/id pair is
    the same seam `docs/ARCHITECTURE.md` already uses for cross-module links.
    """

    CONTENT_ITEM = 'CONTENT_ITEM', 'Content item'
    FEEDBACK = 'FEEDBACK', 'Feedback'
    BRAND = 'BRAND', 'Brand'
    BRAND_SOURCE = 'BRAND_SOURCE', 'Knowledge source'
    BRAND_MEMORY = 'BRAND_MEMORY', 'Brand memory'
    INSPIRATION = 'INSPIRATION', 'Inspiration'
    INSPIRATION_SIGNAL = 'INSPIRATION_SIGNAL', 'Inspiration signal'
    PUBLISHING_JOB = 'PUBLISHING_JOB', 'Publishing job'
    OTHER = 'OTHER', 'Other'


class TenantOwnedModel(models.Model):
    """Workspace + brand, with the invariant enforced for every writer.

    Same guard `apps.inspirations` carries: serializers protect requests, but
    jobs and management commands write through the ORM, and a row whose brand
    belongs to another workspace stops looking like a breach the moment it is
    committed.
    """

    workspace = models.ForeignKey(
        'workspaces.MarketingWorkspace', on_delete=models.CASCADE, related_name='+'
    )
    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.CASCADE, null=True, blank=True, related_name='+'
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.brand_id and self.brand.workspace_id != self.workspace_id:
            raise ValidationError(
                f"{type(self).__name__}.brand must belong to the same workspace."
            )
        return super().save(*args, **kwargs)


class LearningEventQuerySet(models.QuerySet):
    def eligible_for_aggregate(self):
        """Events a workspace has agreed may feed cross-tenant learning.

        Nothing uses this yet — aggregation is a later PR. It exists now so
        the flag is recorded at the moment the evidence is created, rather
        than inferred afterwards from data that never carried consent.
        """
        return self.filter(eligibility_for_aggregate_learning=True)


class LearningEvent(TenantOwnedModel):
    """Something happened that a brand can be learned from.

    Append-only. The API offers no update and no delete, because a rule cites
    its evidence and evidence that can be edited afterwards is not evidence.
    """

    class EventType(models.TextChoices):
        APPROVED = 'APPROVED', 'Approved'
        EDITED = 'EDITED', 'Edited'
        REJECTED = 'REJECTED', 'Rejected'
        REDO = 'REDO', 'Redo requested'
        EXPLICIT_RULE = 'EXPLICIT_RULE', 'Explicit instruction'
        PREFERENCE_SIGNAL = 'PREFERENCE_SIGNAL', 'Preference signal'
        INSPIRATION_SIGNAL = 'INSPIRATION_SIGNAL', 'Inspiration signal'
        PUBLISHED = 'PUBLISHED', 'Published'
        PERFORMANCE_OBSERVED = 'PERFORMANCE_OBSERVED', 'Performance observed'
        MEMORY_CONFIRMED = 'MEMORY_CONFIRMED', 'Memory confirmed'
        MEMORY_REJECTED = 'MEMORY_REJECTED', 'Memory rejected'

    class Outcome(models.TextChoices):
        POSITIVE = 'POSITIVE', 'Positive'
        NEGATIVE = 'NEGATIVE', 'Negative'
        NEUTRAL = 'NEUTRAL', 'Neutral'
        MIXED = 'MIXED', 'Mixed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event_type = models.CharField(max_length=32, choices=EventType.choices)
    outcome = models.CharField(
        max_length=16, choices=Outcome.choices, default=Outcome.NEUTRAL
    )

    subject_type = models.CharField(
        max_length=32, choices=SubjectType.choices, default=SubjectType.OTHER
    )
    subject_id = models.UUIDField(null=True, blank=True)
    # Where the event came from, as opposed to what it is about: a rejection
    # is ABOUT a content item and comes FROM a feedback row.
    source_type = models.CharField(
        max_length=32, choices=SubjectType.choices, blank=True, default=''
    )
    source_id = models.UUIDField(null=True, blank=True)

    context = models.JSONField(default=dict, blank=True)

    # Explicit, and off by default. Consent to pool a tenant's evidence is not
    # something to infer later from rows that never recorded it.
    eligibility_for_aggregate_learning = models.BooleanField(default=False)

    # Lets a retried job or a replayed webhook re-run without laying down a
    # second copy of the same evidence, which would double its weight.
    dedupe_key = models.CharField(max_length=255, blank=True, default='')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='learning_events',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = LearningEventQuerySet.as_manager()

    class Meta:
        db_table = 'learning_events'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['brand', 'event_type']),
            models.Index(fields=['subject_type', 'subject_id']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'dedupe_key'],
                condition=~models.Q(dedupe_key=''),
                name='uniq_learning_event_dedupe_key',
            )
        ]

    def __str__(self):
        return f"{self.event_type} ({self.outcome}) on {self.subject_type}"


class BrandPreferenceQuerySet(models.QuerySet):
    def active(self):
        return self.exclude(state=BrandPreference.State.RETIRED)


class BrandPreference(TenantOwnedModel):
    """A leaning, and how much evidence stands behind it.

    Separate from `BrandRule` on purpose. A preference is allowed to be weak
    and to change; a rule is an instruction. Keeping them in one table would
    mean either treating a single data point as law, or having no way to say
    "we think this, tentatively".
    """

    class State(models.TextChoices):
        EMERGING = 'EMERGING', 'Emerging'
        ESTABLISHED = 'ESTABLISHED', 'Established'
        RETIRED = 'RETIRED', 'Retired'

    #: Distinct events before a leaning is treated as settled. A second
    #: occurrence is what separates a pattern from an opinion — the same
    #: threshold `apps.feedback.training` already uses.
    ESTABLISHED_AT_EVIDENCE = 2

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    category = models.CharField(max_length=64)
    attribute = models.CharField(max_length=255)
    value = models.TextField(blank=True)

    weight = models.FloatField(
        default=0.5, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    confidence = models.FloatField(
        default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    evidence_count = models.PositiveIntegerField(default=0)
    state = models.CharField(
        max_length=16, choices=State.choices, default=State.EMERGING
    )
    scope = models.CharField(
        max_length=16, choices=LearningScope.choices, default=LearningScope.BRAND
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BrandPreferenceQuerySet.as_manager()

    class Meta:
        db_table = 'learning_brand_preferences'
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['brand', 'category', 'attribute'])]
        constraints = [
            # One live leaning per attribute. Two rows disagreeing about the
            # same thing is the defect PR2 spent a review cycle removing from
            # inspiration signals; there is no reason to reintroduce it here.
            models.UniqueConstraint(
                fields=['workspace', 'brand', 'category', 'attribute'],
                condition=~models.Q(state='RETIRED'),
                name='uniq_active_brand_preference',
            )
        ]

    def __str__(self):
        return f"{self.category}/{self.attribute} = {self.value} ({self.state})"


class BrandRuleQuerySet(models.QuerySet):
    def in_force(self):
        """Rules the generator must obey, hardest and highest priority first.

        Ranked explicitly rather than by ordering on `hardness`: that column
        holds 'HARD' and 'SOFT', and sorting it descending puts SOFT first,
        which would hand the generator its preferences ahead of its
        constraints.
        """
        return (
            self.filter(is_active=True)
            .annotate(
                _hardness_rank=models.Case(
                    models.When(hardness=BrandRule.Hardness.HARD, then=models.Value(0)),
                    default=models.Value(1),
                    output_field=models.IntegerField(),
                )
            )
            .order_by('_hardness_rank', '-priority', 'created_at')
        )


class BrandRule(TenantOwnedModel):
    """An instruction the generator obeys.

    Two things guard this table, and they are the acceptance criteria for
    PR3. A learned rule needs corroborating evidence — one reviewer comment
    does not become law. And a learned rule is always soft: only a person
    stating an instruction outright can make it hard, because a hard rule
    overrides the model's judgement everywhere and that authority has to be
    granted, not inferred.
    """

    class Hardness(models.TextChoices):
        SOFT = 'SOFT', 'Preference the generator should follow'
        HARD = 'HARD', 'Constraint the generator must not break'

    class Origin(models.TextChoices):
        EXPLICIT = 'EXPLICIT', 'Stated by a user'
        LEARNED = 'LEARNED', 'Inferred from evidence'

    #: Distinct supporting events before evidence may back a learned rule.
    MIN_EVIDENCE_FOR_LEARNED_RULE = 2

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    text = models.TextField()
    structured = models.JSONField(default=dict, blank=True)

    hardness = models.CharField(
        max_length=8, choices=Hardness.choices, default=Hardness.SOFT
    )
    origin = models.CharField(
        max_length=16, choices=Origin.choices, default=Origin.EXPLICIT
    )
    priority = models.IntegerField(default=0)
    scope = models.CharField(
        max_length=16, choices=LearningScope.choices, default=LearningScope.BRAND
    )

    # Which events this was learned from. Soft ids rather than an M2M: the
    # list is read whole when explaining a rule and never joined on.
    evidence_event_ids = models.JSONField(default=list, blank=True)
    confidence = models.FloatField(
        default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )

    is_active = models.BooleanField(default=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deactivated_brand_rules',
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='brand_rules_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BrandRuleQuerySet.as_manager()

    class Meta:
        db_table = 'learning_brand_rules'
        ordering = ['-priority', '-created_at']
        indexes = [
            models.Index(fields=['brand', 'is_active']),
            models.Index(fields=['workspace', 'hardness']),
        ]
        constraints = [
            # The acceptance criterion, in the schema rather than only in the
            # service: nothing inferred can be a hard constraint.
            models.CheckConstraint(
                condition=~models.Q(origin='LEARNED', hardness='HARD'),
                name='learned_rules_are_never_hard',
            )
        ]

    def __str__(self):
        return f"[{self.hardness}/{self.origin}] {self.text[:60]}"
