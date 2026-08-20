import uuid

from django.conf import settings
from django.db import models

from apps.brands.models import Brand
from apps.content.models import ContentItem
from apps.marketing.models import MarketingAsset
from apps.workspaces.models import MarketingWorkspace


class FeedbackElement(models.Model):
    """
    The vocabulary a reviewer tags feedback with.

    A table rather than a Python enum on purpose: the definitive element list
    belongs to the creative team, not to this repository, so replacing it must
    be a data change and never a deploy. Rows seeded by migration 0002 are
    marked `is_provisional` — see docs/ENHANCEMENT_PLAN.md.
    """

    class Group(models.TextChoices):
        TYPOGRAPHY = 'TYPOGRAPHY', 'Typography'
        COPY = 'COPY', 'Copy & message'
        LINE_BY_LINE = 'LINE_BY_LINE', 'Line-by-line'
        LOGO = 'LOGO', 'Logo & branding'
        VISUAL = 'VISUAL', 'Visual & background'
        LAYOUT = 'LAYOUT', 'Layout'
        AUDIO = 'AUDIO', 'Audio'
        FORMAT = 'FORMAT', 'Format & technical'
        STRATEGY = 'STRATEGY', 'Strategy'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=64, unique=True)
    label = models.CharField(max_length=120)
    group = models.CharField(max_length=32, choices=Group.choices)
    description = models.CharField(max_length=255, blank=True)
    position = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    # True for the placeholder taxonomy shipped with Phase 6. Flip to False as
    # the real names land so the console can show what is still a stand-in.
    is_provisional = models.BooleanField(default=False)

    class Meta:
        db_table = 'feedback_elements'
        ordering = ['group', 'position', 'label']
        indexes = [models.Index(fields=['group', 'position'])]

    def __str__(self):
        return f"{self.get_group_display()} / {self.label}"


class Feedback(models.Model):
    """
    One reviewer verdict on one piece of content, in a form the training
    engine can learn from.

    Distinct from `ContentItem.review_note`, which is a single free-text field
    for the creator to read. This is the structured record: what was wrong,
    which elements it was wrong in, and how the reviewer wants it fixed.
    """

    class Verdict(models.TextChoices):
        APPROVE = 'APPROVE', 'Approve'
        NEEDS_EDITS = 'NEEDS_EDITS', 'Needs edits'
        REJECT = 'REJECT', 'Reject'

    class Sentiment(models.TextChoices):
        POSITIVE = 'POSITIVE', 'Positive'
        NEUTRAL = 'NEUTRAL', 'Neutral'
        NEGATIVE = 'NEGATIVE', 'Negative'

    class Urgency(models.TextChoices):
        LOW = 'LOW', 'Low'
        NORMAL = 'NORMAL', 'Normal'
        HIGH = 'HIGH', 'High'

    #: Verdicts that carry a correction signal worth learning from.
    CORRECTIVE = {Verdict.NEEDS_EDITS, Verdict.REJECT}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.CASCADE, related_name='feedback'
    )
    content_item = models.ForeignKey(
        ContentItem, on_delete=models.CASCADE, related_name='feedback'
    )
    # Denormalised from the content item: rules are learned per brand, and the
    # item may later be repointed at a different one.
    brand = models.ForeignKey(
        Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='feedback'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='given_feedback',
    )

    verdict = models.CharField(max_length=20, choices=Verdict.choices)
    # FeedbackElement.key values. A list column rather than M2M: it is read
    # whole, never joined or filtered on individually.
    element_keys = models.JSONField(default=list, blank=True)
    feedback_text = models.TextField(blank=True)
    fix_request = models.TextField(blank=True)

    sentiment = models.CharField(
        max_length=20, choices=Sentiment.choices, default=Sentiment.NEUTRAL
    )
    urgency = models.CharField(max_length=20, choices=Urgency.choices, default=Urgency.NORMAL)

    # Before/after pair, for the eventual visual diff in the training report.
    before_asset = models.ForeignKey(
        MarketingAsset, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='feedback_before',
    )
    after_asset = models.ForeignKey(
        MarketingAsset, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='feedback_after',
    )

    # Semantic vector of the feedback text, stored as a JSON list of floats.
    # Deliberately not pgvector: the test suite runs on SQLite, which has no
    # vector type, and at this row count an in-process cosine scan over a
    # workspace is faster than the round trip. `apps.feedback.embeddings` is
    # the only module that touches the representation, so swapping in a
    # VectorField later is a one-file change.
    embedding = models.JSONField(default=list, blank=True)
    embedding_model = models.CharField(max_length=100, blank=True)

    # What the training engine concluded, and which brand rules it wrote.
    pattern_extracted = models.JSONField(default=dict, blank=True)
    rules_updated = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'feedback'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['workspace', 'verdict']),
        ]

    def __str__(self):
        return f"{self.verdict} on {self.content_item_id}"

    @property
    def is_corrective(self) -> bool:
        return self.verdict in self.CORRECTIVE
