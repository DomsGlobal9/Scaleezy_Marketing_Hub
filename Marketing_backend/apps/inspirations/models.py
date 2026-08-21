"""
Inspirations: the references a brand wants its creative to feel like.

Kept deliberately separate from `apps.knowledge`. A knowledge source answers
"what is true about this business"; an inspiration answers "what should this
look and sound like". They have different lifecycles, different review
semantics, and — the reason they cannot share a table — different provenance
rules: an inspiration carries BOTH what a human explicitly said about it and
what a model later inferred, and those two must never be mistaken for each
other.

Signals hang off an inspiration and hold no workspace/brand column of their
own. Tenancy is derived through the parent, so a signal cannot drift out of
its inspiration's tenant the way a denormalised copy eventually does.
"""
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.knowledge.models import BrandSource


class SignalCategory(models.TextChoices):
    """What part of a reference a signal talks about.

    Shared by `InspirationSignal.category` and by
    `BrandInspiration.focus_areas`, which is what makes "use only the
    typography from this reference" expressible.
    """

    TYPOGRAPHY = 'TYPOGRAPHY', 'Typography'
    COLOR = 'COLOR', 'Colour'
    LAYOUT = 'LAYOUT', 'Layout'
    COMPOSITION = 'COMPOSITION', 'Composition'
    IMAGERY = 'IMAGERY', 'Imagery'
    PHOTOGRAPHY = 'PHOTOGRAPHY', 'Photography'
    ILLUSTRATION = 'ILLUSTRATION', 'Illustration'
    MOTION = 'MOTION', 'Motion'
    PACING = 'PACING', 'Pacing'
    TONE = 'TONE', 'Tone of voice'
    COPY_STYLE = 'COPY_STYLE', 'Copy style'
    HOOK = 'HOOK', 'Hook'
    CTA = 'CTA', 'Call to action'
    STRUCTURE = 'STRUCTURE', 'Structure'
    MOOD = 'MOOD', 'Mood'
    BRANDING = 'BRANDING', 'Branding'
    OTHER = 'OTHER', 'Other'


class BrandInspirationQuerySet(models.QuerySet):
    def eligible_for_retrieval(self):
        """Rows a future Context Gateway (PR5) may draw on.

        Archiving an inspiration, or archiving the source it came from, takes
        it out of circulation without destroying the record (PR1-010).
        """
        return self.filter(
            lifecycle_status=BrandInspiration.LifecycleStatus.ACTIVE
        ).exclude(source__status=BrandSource.SourceStatus.ARCHIVED)


class BrandInspiration(models.Model):
    class InspirationType(models.TextChoices):
        IMAGE = 'IMAGE', 'Image'
        SCREENSHOT = 'SCREENSHOT', 'Screenshot'
        URL = 'URL', 'URL'
        WEB_PAGE = 'WEB_PAGE', 'Web page'
        POST = 'POST', 'Social post'
        REEL = 'REEL', 'Reel / short video'
        VIDEO = 'VIDEO', 'Video'
        AD = 'AD', 'Advertisement'
        PIN = 'PIN', 'Pinboard pin'
        COMPETITOR = 'COMPETITOR', 'Competitor reference'
        REFERENCE = 'REFERENCE', 'General reference'
        MOODBOARD = 'MOODBOARD', 'Moodboard'
        OTHER = 'OTHER', 'Other'

    class UsageScope(models.TextChoices):
        FULL_REFERENCE = 'FULL_REFERENCE', 'Use the entire reference'
        SPECIFIC_ELEMENTS = 'SPECIFIC_ELEMENTS', 'Use only the named elements'

    class AnalysisStatus(models.TextChoices):
        # PR2 ships no analysis. NOT_ANALYSED is the only state the API can
        # reach; the rest exist so PR6 does not need a schema migration to
        # tell the truth about a job (GLOBAL-001).
        NOT_ANALYSED = 'NOT_ANALYSED', 'Not analysed'
        QUEUED = 'QUEUED', 'Queued'
        PROCESSING = 'PROCESSING', 'Processing'
        NEEDS_REVIEW = 'NEEDS_REVIEW', 'Needs review'
        READY = 'READY', 'Ready'
        FAILED = 'FAILED', 'Failed'

    class LifecycleStatus(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        ARCHIVED = 'ARCHIVED', 'Archived'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'workspaces.MarketingWorkspace',
        on_delete=models.CASCADE,
        related_name='brand_inspirations',
    )
    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.CASCADE, related_name='inspirations'
    )
    # Provenance: where the reference originally entered the system. Optional,
    # because a pasted competitor URL has no uploaded source behind it.
    source = models.ForeignKey(
        BrandSource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inspirations',
    )

    inspiration_type = models.CharField(
        max_length=20, choices=InspirationType.choices, default=InspirationType.REFERENCE
    )
    title = models.CharField(max_length=255)
    # The human's own words about the reference. Never written by a model.
    annotation = models.TextField(blank=True)

    reference_url = models.URLField(max_length=1000, blank=True, null=True)
    storage_path = models.CharField(max_length=1000, blank=True, null=True)
    file_url = models.URLField(max_length=1000, blank=True, null=True)
    mime_type = models.CharField(max_length=100, blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    # Free text on purpose: the platform a reference came from is metadata,
    # not an integration. Hard-coding a provider here would make every new
    # network a migration.
    external_platform = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    usage_scope = models.CharField(
        max_length=20, choices=UsageScope.choices, default=UsageScope.FULL_REFERENCE
    )
    # List of SignalCategory values, meaningful only for SPECIFIC_ELEMENTS.
    focus_areas = models.JSONField(default=list, blank=True)

    analysis_status = models.CharField(
        max_length=20, choices=AnalysisStatus.choices, default=AnalysisStatus.NOT_ANALYSED
    )
    lifecycle_status = models.CharField(
        max_length=20, choices=LifecycleStatus.choices, default=LifecycleStatus.ACTIVE
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inspirations_created',
    )
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inspirations_archived',
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BrandInspirationQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'brand']),
            models.Index(fields=['brand', 'lifecycle_status']),
        ]

    def __str__(self):
        return f"{self.title} ({self.inspiration_type})"

    def retrieval_eligibility(self):
        """Why this reference may or may not be used, in the object's own words.

        Returned by the API so a client never has to infer eligibility from a
        status field it might read differently than the retrieval query does.
        """
        if self.lifecycle_status == self.LifecycleStatus.ARCHIVED:
            return {'eligible': False, 'reason': 'INSPIRATION_ARCHIVED'}
        if self.source_id and self.source.status == BrandSource.SourceStatus.ARCHIVED:
            return {'eligible': False, 'reason': 'SOURCE_ARCHIVED'}
        return {'eligible': True, 'reason': 'ACTIVE'}


class InspirationSignalQuerySet(models.QuerySet):
    def eligible_for_retrieval(self):
        return self.filter(
            inspiration__in=BrandInspiration.objects.eligible_for_retrieval(),
            conflicts_with__isnull=True,
        ).exclude(user_confirmation=InspirationSignal.UserConfirmation.REJECTED)


class InspirationSignal(models.Model):
    """One extracted or stated preference about one inspiration.

    `origin` and `user_confirmation` are two axes, not one. A model may infer
    something (origin=AI) and a human may later agree with it
    (user_confirmation=CONFIRMED) — but the row never stops being AI-derived,
    so nothing downstream can mistake an inference for a stated preference.
    """

    class Sentiment(models.TextChoices):
        LIKED = 'LIKED', 'Liked'
        DISLIKED = 'DISLIKED', 'Disliked'
        NEUTRAL = 'NEUTRAL', 'Neutral'

    class Origin(models.TextChoices):
        USER = 'USER', 'Stated by a user'
        AI = 'AI', 'Inferred by a model'

    class UserConfirmation(models.TextChoices):
        CONFIRMED = 'CONFIRMED', 'Confirmed by a user'
        PENDING = 'PENDING', 'Awaiting user review'
        REJECTED = 'REJECTED', 'Rejected by a user'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inspiration = models.ForeignKey(
        BrandInspiration, on_delete=models.CASCADE, related_name='signals'
    )

    category = models.CharField(max_length=20, choices=SignalCategory.choices)
    attribute = models.CharField(max_length=255)
    value = models.TextField(blank=True)

    # Explicit, and independent of weight. A weight of 0.9 says "this matters
    # a lot", not "they liked it" (PR2 integrity rule).
    sentiment = models.CharField(
        max_length=10, choices=Sentiment.choices, default=Sentiment.NEUTRAL
    )
    weight = models.FloatField(
        default=0.5, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    confidence = models.FloatField(
        default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )

    origin = models.CharField(max_length=10, choices=Origin.choices, default=Origin.USER)
    user_confirmation = models.CharField(
        max_length=10, choices=UserConfirmation.choices, default=UserConfirmation.PENDING
    )
    # An AI signal that contradicts a stated user preference points at it here
    # instead of replacing it, and stays out of retrieval while it does.
    conflicts_with = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contradicted_by',
    )
    extracted_by_provider = models.CharField(max_length=100, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inspiration_signals_created',
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inspiration_signals_confirmed',
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = InspirationSignalQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['inspiration', 'category']),
            models.Index(fields=['inspiration', 'origin']),
        ]
        constraints = [
            # One inferred signal per (inspiration, category, attribute) so a
            # retried PR6 analysis job cannot pile up duplicates. Users may
            # state several signals about the same attribute.
            models.UniqueConstraint(
                fields=['inspiration', 'category', 'attribute'],
                condition=models.Q(origin='AI'),
                name='uniq_ai_signal_per_inspiration_attribute',
            )
        ]

    def __str__(self):
        return f"{self.category}/{self.attribute} {self.sentiment} ({self.origin})"

    # Tenancy is read through the parent rather than copied onto the row, so
    # there is no second value to keep in sync. `_workspace_id_of` in
    # apps.common.permissions picks `workspace_id` up automatically.
    @property
    def workspace_id(self):
        return self.inspiration.workspace_id

    @property
    def brand_id(self):
        return self.inspiration.brand_id

    def retrieval_eligibility(self):
        if self.user_confirmation == self.UserConfirmation.REJECTED:
            return {'eligible': False, 'reason': 'REJECTED_BY_USER'}
        if self.conflicts_with_id:
            return {'eligible': False, 'reason': 'CONFLICTS_WITH_USER_SIGNAL'}
        parent = self.inspiration.retrieval_eligibility()
        if not parent['eligible']:
            return {'eligible': False, 'reason': parent['reason']}
        return {'eligible': True, 'reason': 'ACTIVE'}
