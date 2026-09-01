import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import m2m_changed
from django.dispatch import receiver


class AutopilotPolicy(models.Model):
    class Mode(models.TextChoices):
        ASSISTED = 'ASSISTED', 'Draft only'
        APPROVAL_REQUIRED = 'APPROVAL_REQUIRED', 'Human approval required'

    class Cadence(models.TextChoices):
        MANUAL = 'MANUAL', 'Manual only'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'workspaces.MarketingWorkspace', on_delete=models.CASCADE,
        related_name='autopilot_policies',
    )
    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.CASCADE, related_name='autopilot_policies'
    )
    name = models.CharField(max_length=120)
    objective = models.TextField()
    campaign_brief = models.TextField(blank=True)
    mode = models.CharField(
        max_length=24, choices=Mode.choices, default=Mode.APPROVAL_REQUIRED
    )
    cadence = models.CharField(
        max_length=16, choices=Cadence.choices, default=Cadence.MANUAL
    )
    next_run_at = models.DateTimeField(null=True, blank=True)
    allowed_formats = models.JSONField(default=list, blank=True)
    social_connections = models.ManyToManyField(
        'social_accounts.SocialConnection', blank=True,
        related_name='autopilot_policies',
    )
    daily_generation_limit = models.PositiveIntegerField(default=1)
    monthly_spend_cap = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='0 means the workspace billing cap is the only spend cap.',
    )
    enabled = models.BooleanField(default=False)
    paused = models.BooleanField(default=False)
    emergency_stop = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='autopilot_policies_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'brand', 'name'], name='uniq_autopilot_policy_name'
            ),
            models.CheckConstraint(
                condition=models.Q(monthly_spend_cap__gte=0),
                name='autopilot_spend_cap_non_negative',
            ),
        ]
        indexes = [
            models.Index(fields=['workspace', 'enabled', 'paused']),
            models.Index(fields=['enabled', 'next_run_at']),
        ]

    def save(self, *args, **kwargs):
        if self.brand_id and self.brand.workspace_id != self.workspace_id:
            raise ValidationError('Autopilot brand must belong to its workspace.')
        if not isinstance(self.allowed_formats, list):
            raise ValidationError('allowed_formats must be a list.')
        self.allowed_formats = [
            str(value).upper() for value in self.allowed_formats
            if str(value).upper() in {'POSTER', 'CAROUSEL', 'VIDEO'}
        ][:3]
        return super().save(*args, **kwargs)


class AutopilotRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'QUEUED', 'Queued'
        RUNNING = 'RUNNING', 'Running'
        WAITING_GENERATION = 'WAITING_GENERATION', 'Waiting for generation'
        WAITING_REVIEW = 'WAITING_REVIEW', 'Waiting for human review'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
        STOPPED = 'STOPPED', 'Stopped'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'workspaces.MarketingWorkspace', on_delete=models.CASCADE,
        related_name='autopilot_runs',
    )
    policy = models.ForeignKey(
        AutopilotPolicy, on_delete=models.CASCADE, related_name='runs'
    )
    status = models.CharField(max_length=28, choices=Status.choices, default=Status.QUEUED)
    scheduled_for = models.DateTimeField()
    dedupe_key = models.CharField(max_length=255)
    policy_snapshot = models.JSONField(default=dict)
    generation_request = models.ForeignKey(
        'gemini.GeminiGenerationRequest', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='autopilot_runs',
    )
    content_item = models.ForeignKey(
        'content.ContentItem', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='autopilot_runs',
    )
    publishing_job = models.ForeignKey(
        'publishing.PublishingJob', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='autopilot_runs',
    )
    task_id = models.CharField(max_length=64, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error = models.TextField(blank=True)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='autopilot_runs_initiated',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'dedupe_key'], name='uniq_autopilot_run_dedupe'
            )
        ]
        indexes = [
            models.Index(fields=['workspace', 'status', '-created_at']),
            models.Index(fields=['status', 'next_check_at']),
        ]

    def save(self, *args, **kwargs):
        if self.policy_id and self.policy.workspace_id != self.workspace_id:
            raise ValidationError('Autopilot policy must belong to its workspace.')
        return super().save(*args, **kwargs)


class AutopilotStep(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(AutopilotRun, on_delete=models.CASCADE, related_name='steps')
    key = models.CharField(max_length=80)
    status = models.CharField(max_length=24)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(fields=['run', 'key'], name='uniq_autopilot_run_step')
        ]


@receiver(m2m_changed, sender=AutopilotPolicy.social_connections.through)
def enforce_autopilot_connection_workspace(sender, instance, action, pk_set, **kwargs):
    """Keep tenant integrity on ORM/admin paths as well as through the API."""
    if action != 'pre_add' or not pk_set:
        return
    from apps.social_accounts.models import SocialConnection

    if SocialConnection.objects.filter(pk__in=pk_set).exclude(
        workspace_id=instance.workspace_id
    ).exists():
        raise ValidationError(
            'Every autopilot social account must belong to the policy workspace.'
        )
