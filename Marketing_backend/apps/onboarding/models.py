"""
Onboarding orchestration and calibration.

Two records, both deliberately thin. `BrandOnboarding` stores where a brand is
in its setup journey and nothing else — the knowledge, inspirations, learning
and brain it orchestrates all live in the apps that own them, so this table
duplicating any of it would create a second truth to drift. `CalibrationDirection`
stores one generated direction and what it was testing, so the user's verdict on
it can be traced from the click all the way to the preference it reinforced.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class BrandOnboarding(models.Model):
    """Where one brand is in its setup journey.

    Stage is derived from what actually exists (see `services.refresh_stage`),
    not advanced by button clicks — a user who uploads knowledge through the
    normal Knowledge tab has progressed whether or not they did it from the
    onboarding screen.
    """

    class Stage(models.TextChoices):
        BASICS = 'BASICS', 'Brand basics'
        KNOWLEDGE = 'KNOWLEDGE', 'Upload knowledge'
        INSPIRATIONS = 'INSPIRATIONS', 'Add inspirations'
        CALIBRATION = 'CALIBRATION', 'Teach Scaleezy your taste'
        FIRST_GENERATION = 'FIRST_GENERATION', 'Create your first content'
        DONE = 'DONE', 'Done'

    class Status(models.TextChoices):
        NOT_STARTED = 'NOT_STARTED', 'Not started'
        IN_PROGRESS = 'IN_PROGRESS', 'In progress'
        READY_FOR_GENERATION = 'READY_FOR_GENERATION', 'Ready for generation'
        COMPLETED = 'COMPLETED', 'Completed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'workspaces.MarketingWorkspace', on_delete=models.CASCADE,
        related_name='brand_onboardings',
    )
    brand = models.OneToOneField(
        'brands.Brand', on_delete=models.CASCADE, related_name='onboarding'
    )

    current_stage = models.CharField(
        max_length=20, choices=Stage.choices, default=Stage.BASICS
    )
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.NOT_STARTED
    )
    # Stage keys the user chose to move past without completing. Skipping is
    # allowed everywhere except where generation would be genuinely impossible.
    skipped_steps = models.JSONField(default=list, blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'brand_onboarding'
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.brand_id} @ {self.current_stage} ({self.status})"

    def save(self, *args, **kwargs):
        if self.brand_id and self.brand.workspace_id != self.workspace_id:
            raise ValidationError(
                "BrandOnboarding.brand must belong to the same workspace."
            )
        return super().save(*args, **kwargs)


class CalibrationDirection(models.Model):
    """One generated direction, what it was testing, and the user's verdict.

    The provenance link the mission requires: calibration → direction →
    decision → LearningEvent → preference evidence. `learning_event_id` records
    the event this verdict produced, so nothing about the chain has to be
    reconstructed later.
    """

    class Verdict(models.TextChoices):
        PENDING = 'PENDING', 'Awaiting reaction'
        LIKED = 'LIKED', 'Like'
        NOT_US = 'NOT_US', 'Not us'
        ADJUSTED = 'ADJUSTED', 'Adjust'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'workspaces.MarketingWorkspace', on_delete=models.CASCADE, related_name='+'
    )
    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.CASCADE, related_name='calibration_directions'
    )

    #: Groups the directions generated together, so one calibration round is
    #: addressable as a unit.
    round_id = models.UUIDField(db_index=True)
    #: A / B / C
    label = models.CharField(max_length=8)
    #: What this direction deliberately tests, e.g. "minimal_restrained".
    tests_dimension = models.CharField(max_length=64)
    #: The claim values this direction leans on, for the learning write.
    tested_attributes = models.JSONField(default=dict, blank=True)

    headline = models.CharField(max_length=500, blank=True)
    caption = models.TextField(blank=True)
    hashtags = models.TextField(blank=True)
    preview_url = models.URLField(max_length=1000, blank=True)

    provider = models.CharField(max_length=50, blank=True)
    brain_version = models.CharField(max_length=64, blank=True)

    verdict = models.CharField(
        max_length=10, choices=Verdict.choices, default=Verdict.PENDING
    )
    adjustment_note = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='calibration_decisions',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    #: The LearningEvent this verdict produced. Soft id — learning owns it.
    learning_event_id = models.UUIDField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'calibration_directions'
        ordering = ['round_id', 'label']
        indexes = [models.Index(fields=['brand', '-created_at'])]

    def __str__(self):
        return f"{self.label}:{self.tests_dimension} ({self.verdict})"

    def save(self, *args, **kwargs):
        if self.brand_id and self.brand.workspace_id != self.workspace_id:
            raise ValidationError(
                "CalibrationDirection.brand must belong to the same workspace."
            )
        return super().save(*args, **kwargs)
