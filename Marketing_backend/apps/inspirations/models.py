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
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Exists, OuterRef, Q

from apps.knowledge.models import BrandSource


class InspirationSignalError(Exception):
    """A signal write cannot be performed as asked.

    Lives here rather than in `services` because the model layer raises it too
    — the bulk write paths below reject writes that would desynchronise the
    folded columns — and services imports models, not the other way round.
    """


def normalize_signal_text(text):
    """Fold the incidental differences out of a signal key or value.

    "Condensed  Grotesque " and "condensed grotesque" are the same preference
    typed twice; if they compare as different, two contradictory records can
    both be authoritative for one attribute and nothing downstream can say
    which one a human meant.

    Deliberately simple — case and whitespace only. Anything cleverer
    (stemming, synonyms, unit parsing) would start deciding that two genuinely
    different preferences are the same, which is a worse failure than missing
    a duplicate.
    """
    if not text:
        return ''
    return ' '.join(str(text).split()).casefold()


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

    def save(self, *args, **kwargs):
        """Enforce the tenancy invariant for every writer, not just the API.

        The serializers already reject a mismatched brand or source, but they
        only guard requests. Ingestion jobs, management commands and future
        services write through the ORM, and a row whose brand belongs to
        another workspace is not a validation failure there — it is a tenant
        breach that would look like ordinary data forever after.
        """
        self._assert_tenant_invariants()
        return super().save(*args, **kwargs)

    def _assert_tenant_invariants(self):
        if self.brand_id and self.brand.workspace_id != self.workspace_id:
            raise ValidationError(
                "BrandInspiration.brand must belong to the same workspace as "
                "the inspiration."
            )
        if self.source_id:
            if self.source.workspace_id != self.workspace_id:
                raise ValidationError(
                    "BrandInspiration.source must belong to the same workspace "
                    "as the inspiration."
                )
            if self.source.brand_id != self.brand_id:
                raise ValidationError(
                    "BrandInspiration.source must belong to the same brand as "
                    "the inspiration."
                )

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


class SupersessionReason(models.TextChoices):
    """Why a preference stopped being the active one.

    Kept as data rather than inferred from the shape of the chain: an auditor
    reading a superseded row a year later needs to know whether the human
    changed their mind or accepted a machine's suggestion.
    """

    NEWER_USER_SIGNAL = (
        'SUPERSEDED_BY_NEWER_USER_SIGNAL',
        'Replaced by a newer stated preference',
    )
    CONFIRMED_AI_DIRECTION = (
        'SUPERSEDED_BY_CONFIRMED_AI_DIRECTION',
        'A user accepted a contradicting inference',
    )
    NEWER_AI_INFERENCE = (
        'SUPERSEDED_BY_NEWER_AI_INFERENCE',
        'Replaced by a newer inference after a human had ruled on this one',
    )


class InspirationSignalQuerySet(models.QuerySet):
    # `attribute` and `value` have folded twins that identity and equality are
    # decided on. Anything that writes the raw column without the twin leaves
    # a row that is no longer findable by its own attribute and that the
    # uniqueness rule silently stops guarding — so the bulk paths, which do not
    # call save(), are handled explicitly rather than left to be discovered.
    _FOLDED_SOURCES = ('attribute', 'value')

    def update(self, **kwargs):
        conflicting = sorted(set(kwargs) & set(self._FOLDED_SOURCES))
        if conflicting:
            raise InspirationSignalError(
                f"{', '.join(conflicting)} cannot be changed with queryset.update(): "
                "it would leave the normalized column stale. Use save() on the "
                "instance, or state a new signal."
            )
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        conflicting = sorted(set(fields) & set(self._FOLDED_SOURCES))
        if conflicting:
            raise InspirationSignalError(
                f"{', '.join(conflicting)} cannot be changed with bulk_update(): "
                "include the matching normalized_* fields, or use save()."
            )
        return super().bulk_update(objs, fields, **kwargs)

    def bulk_create(self, objs, *args, **kwargs):
        for obj in objs:
            obj.normalized_attribute = normalize_signal_text(obj.attribute)
            obj.normalized_value = normalize_signal_text(obj.value)
        return super().bulk_create(objs, *args, **kwargs)

    def active(self):
        """Rows that still assert something.

        Superseded rows are kept for audit but have stopped being true;
        rejected rows were withdrawn by a human.
        """
        return self.filter(superseded_at__isnull=True).exclude(
            user_confirmation=InspirationSignal.UserConfirmation.REJECTED
        )

    def for_attribute(self, inspiration, category, attribute):
        """Everything ever recorded about one attribute, history included."""
        return self.filter(
            inspiration=inspiration,
            category=category,
            normalized_attribute=normalize_signal_text(attribute),
        )

    def authoritative_user_signals(self):
        """The stated preferences that currently hold.

        The partial unique constraint allows only one per attribute, so this
        is at most one row per (inspiration, category, normalized_attribute).
        """
        return self.filter(
            origin=InspirationSignal.Origin.USER,
            user_confirmation=InspirationSignal.UserConfirmation.CONFIRMED,
            superseded_at__isnull=True,
        )

    def eligible_for_retrieval(self):
        """The single active preference per attribute.

        Four things take a row out: its reference was archived, it was
        superseded, a human rejected it, or it is an inference that
        contradicts a stated preference.

        The fifth is the one the CTO review turns on: when a human HAS stated
        a preference for an attribute, an inference about that same attribute
        is not retrievable even when it agrees. Two rows saying the same thing
        would be counted twice by anything that weighs signals, and "agrees"
        is only ever true until the next re-analysis. The stated preference is
        the authority; the inference is kept as provenance.
        """
        user_authority = InspirationSignal.objects.filter(
            inspiration_id=OuterRef('inspiration_id'),
            category=OuterRef('category'),
            normalized_attribute=OuterRef('normalized_attribute'),
            origin=InspirationSignal.Origin.USER,
            user_confirmation=InspirationSignal.UserConfirmation.CONFIRMED,
            superseded_at__isnull=True,
        )
        return (
            self.active()
            .filter(
                inspiration__in=BrandInspiration.objects.eligible_for_retrieval(),
                conflicts_with__isnull=True,
            )
            .annotate(_under_user_authority=Exists(user_authority))
            .filter(
                # CONFIRMED, not merely USER-origin. The check constraint below
                # makes an unconfirmed stated preference unrepresentable, but
                # the three places that decide "a USER signal that counts" —
                # this clause, `authoritative_user_signals()` and
                # `uniq_authoritative_user_signal` — have to name the same
                # predicate, or the next person to relax one of them
                # reintroduces two active truths for one attribute.
                Q(
                    origin=InspirationSignal.Origin.USER,
                    user_confirmation=InspirationSignal.UserConfirmation.CONFIRMED,
                )
                | Q(_under_user_authority=False)
            )
        )


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

    # --- supersession -------------------------------------------------
    # A preference is never edited or deleted; it is replaced, and the row it
    # was replaced by is recorded. `superseded_at` — not the foreign key — is
    # what "active" is read from, so that if `superseded_by` is ever nulled
    # (it is SET_NULL) a historical preference cannot quietly come back to
    # life.
    superseded_at = models.DateTimeField(null=True, blank=True, db_index=True)
    superseded_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supersedes',
    )
    superseded_reason = models.CharField(
        max_length=48, choices=SupersessionReason.choices, blank=True, default=''
    )

    # Case- and whitespace-folded copies, written by save(). They are what the
    # identity of an attribute and the equality of a value are decided on, so
    # the Python path and the SQL path cannot disagree about whether two
    # signals are about the same thing.
    # 765 = 255 x 3, because casefolding can treble a string's length: U+FB04
    # (the "ffl" ligature) folds to three characters. A shorter column would
    # fail the write on PostgreSQL and truncate silently on SQLite.
    normalized_attribute = models.CharField(max_length=765, blank=True, default='')
    normalized_value = models.TextField(blank=True, default='')

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
            models.Index(fields=['inspiration', 'category', 'normalized_attribute']),
        ]
        constraints = [
            # Exactly one stated preference may hold for an attribute at a
            # time. This is the CTO rework in one line: "latest active explicit
            # USER signal is authoritative" is only deterministic if the
            # database refuses to hold two of them. Superseded and rejected
            # rows fall outside the condition, so history accumulates freely.
            models.UniqueConstraint(
                fields=['inspiration', 'category', 'normalized_attribute'],
                condition=models.Q(
                    origin='USER', superseded_at__isnull=True, user_confirmation='CONFIRMED'
                ),
                name='uniq_authoritative_user_signal',
            ),
            # One live inference per attribute, so a retried PR6 analysis job
            # cannot pile up duplicates.
            models.UniqueConstraint(
                fields=['inspiration', 'category', 'normalized_attribute'],
                condition=models.Q(origin='AI', superseded_at__isnull=True),
                name='uniq_active_ai_signal',
            ),
            # PR1-011. A row cannot supersede itself; longer cycles are
            # unreachable because superseding a row deactivates it, and only
            # active rows are ever superseded.
            models.CheckConstraint(
                condition=~models.Q(superseded_by=models.F('id')),
                name='inspiration_signal_no_self_supersession',
            ),
            # A stated preference is confirmed by definition — a person said
            # it. `user_confirmation` defaults to PENDING for inferences, so
            # without this an ORM writer that omits the field produces a USER
            # row that falls OUTSIDE `uniq_authoritative_user_signal` and can
            # therefore sit alongside the real authority, giving one attribute
            # two active truths. The API never produced that state; a job
            # would have.
            models.CheckConstraint(
                condition=~models.Q(origin='USER', user_confirmation='PENDING'),
                name='inspiration_signal_user_preference_is_confirmed',
            ),
        ]

    def save(self, *args, **kwargs):
        """Keep the folded copies in step with what they are folded from.

        Computed here rather than at the call site so no writer — API, service
        or future job — can create a row whose normalized key disagrees with
        its raw key. When `update_fields` is given, the folded columns are
        added to it if their source changed, otherwise the row would keep a
        stale key that the retrieval query still trusts.
        """
        self.normalized_attribute = normalize_signal_text(self.attribute)
        self.normalized_value = normalize_signal_text(self.value)

        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            update_fields = set(update_fields)
            if 'attribute' in update_fields:
                update_fields.add('normalized_attribute')
            if 'value' in update_fields:
                update_fields.add('normalized_value')
            kwargs['update_fields'] = update_fields

        return super().save(*args, **kwargs)

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

    @property
    def is_superseded(self):
        return self.superseded_at is not None

    def retrieval_eligibility(self):
        """Why this signal is or is not the active preference for its attribute.

        Mirrors `InspirationSignalQuerySet.eligible_for_retrieval()` clause for
        clause. The two are checked against each other by
        `test_row_verdict_and_queryset_agree`, because a per-row verdict that
        disagreed with the query would be worse than no verdict at all.
        """
        if self.is_superseded:
            return {
                'eligible': False,
                'reason': self.superseded_reason or 'SUPERSEDED',
            }
        if self.user_confirmation == self.UserConfirmation.REJECTED:
            return {'eligible': False, 'reason': 'REJECTED_BY_USER'}
        if (
            self.origin == self.Origin.USER
            and self.user_confirmation == self.UserConfirmation.PENDING
        ):
            # Unrepresentable while the check constraint stands. Kept so this
            # verdict and the queryset never disagree about a row that exists.
            return {'eligible': False, 'reason': 'AWAITING_USER_CONFIRMATION'}
        if self.conflicts_with_id:
            return {'eligible': False, 'reason': 'CONFLICTS_WITH_USER_SIGNAL'}
        parent = self.inspiration.retrieval_eligibility()
        if not parent['eligible']:
            return {'eligible': False, 'reason': parent['reason']}
        if self.origin == self.Origin.AI and self._has_user_authority():
            return {'eligible': False, 'reason': 'USER_PREFERENCE_TAKES_PRECEDENCE'}
        return {'eligible': True, 'reason': 'ACTIVE'}

    def _has_user_authority(self):
        """Is there a stated preference for this attribute right now?"""
        return (
            InspirationSignal.objects.filter(
                inspiration_id=self.inspiration_id,
                category=self.category,
                normalized_attribute=self.normalized_attribute,
                origin=self.Origin.USER,
                user_confirmation=self.UserConfirmation.CONFIRMED,
                superseded_at__isnull=True,
            )
            .exclude(pk=self.pk)
            .exists()
        )
