import uuid

from django.conf import settings
from django.db import models

from apps.brands.models import Brand
from apps.marketing.models import MarketingAsset
from apps.workspaces.models import MarketingWorkspace


class ContentItem(models.Model):
    """
    A generated or uploaded post, persisted.

    Until now Gemini output was returned to the browser and never stored, so
    headlines, captions and hashtags lived only in React state and were lost
    on refresh. Everything downstream — review, feedback, training — needs a
    durable row to attach to.
    """

    class Format(models.TextChoices):
        POSTER = 'POSTER', 'Poster'
        CAROUSEL = 'CAROUSEL', 'Carousel'
        VIDEO = 'VIDEO', 'Video'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        PENDING_REVIEW = 'PENDING_REVIEW', 'Pending review'
        APPROVED = 'APPROVED', 'Approved'
        NEEDS_EDITS = 'NEEDS_EDITS', 'Needs edits'
        REJECTED = 'REJECTED', 'Rejected'
        PUBLISHED = 'PUBLISHED', 'Published'

    # Only APPROVED content may be published.
    PUBLISHABLE = {Status.APPROVED}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.CASCADE, related_name='content_items'
    )
    brand = models.ForeignKey(
        Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='content_items'
    )
    asset = models.ForeignKey(
        MarketingAsset, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='content_items',
    )

    content_format = models.CharField(max_length=20, choices=Format.choices, default=Format.POSTER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    # Revisions: a NEEDS_EDITS item spawns a new version pointing back here.
    version = models.PositiveIntegerField(default=1)
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='revisions'
    )

    headline = models.CharField(max_length=500, blank=True)
    caption = models.TextField(blank=True)
    cta = models.CharField(max_length=255, blank=True)
    hashtags = models.TextField(blank=True)

    preview_url = models.URLField(max_length=1000, blank=True)
    # Ordered carousel slides: [{position, description, preview_url}]. A JSON
    # column rather than a table — slides are never queried apart from their
    # parent, so a join would buy nothing.
    slides = models.JSONField(default=list, blank=True)

    # How this individual item is composed. Brand-wide template defaults are
    # deliberately not consulted.
    layout_plugin = models.CharField(max_length=64, blank=True)
    layout_config = models.JSONField(default=dict, blank=True)

    # What produced it, for cost tracking and for the Phase 5 AI router.
    ai_provider = models.CharField(max_length=50, blank=True)
    ai_model = models.CharField(max_length=100, blank=True)
    ai_prompt = models.TextField(blank=True)
    ai_cost = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    review_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_content',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_content',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'content_items'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'status']),
            models.Index(fields=['workspace', '-created_at']),
        ]

    def __str__(self):
        return f"{self.headline or self.content_format} ({self.status})"

    @property
    def is_publishable(self) -> bool:
        return self.status in self.PUBLISHABLE
