import uuid
from django.db import models
from apps.workspaces.models import MarketingWorkspace
from apps.marketing.models import MarketingAsset
from django.contrib.auth import get_user_model

User = get_user_model()

class GeminiGenerationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        GENERATING = 'GENERATING', 'Generating'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(MarketingWorkspace, on_delete=models.CASCADE, related_name='gemini_requests')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    prompt_data = models.TextField(
        blank=True,
        null=True,
        help_text="Provider-neutral generation brief",
    )
    
    campaign_name = models.CharField(max_length=255, blank=True, null=True)
    product = models.CharField(max_length=255, blank=True, null=True)
    target_audience = models.CharField(max_length=255, blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    occasion = models.CharField(max_length=255, blank=True, null=True)
    offer = models.CharField(max_length=255, blank=True, null=True)
    brand_tone = models.CharField(max_length=255, blank=True, null=True)
    content_format = models.CharField(max_length=255, blank=True, null=True)
    visual_direction = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=50, choices=Status.choices, default=Status.PENDING)
    
    provider = models.CharField(max_length=50, blank=True, default='', editable=False)
    model = models.CharField(max_length=100, blank=True, default='')

    error_message = models.TextField(blank=True, null=True)

    #: How many times the stuck-generation sweep has re-queued this request
    #: after a worker died mid-generation. Bounds the rescue: one re-run,
    #: then an honest FAILED.
    retry_count = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    #: When a worker last moved this row through its lifecycle. Every status
    #: transition stamps it explicitly (auto_now does not fire on queryset
    #: updates, and update_fields must name it); the stuck-generation sweep
    #: reads it as "how long since anything touched this". Nullable only for
    #: schema history — migration 0003 backfills it from created_at.
    updated_at = models.DateTimeField(auto_now=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'gemini_generation_requests'
        indexes = [
            # The stuck-generation sweep's probe, which runs on every worker
            # pass. Partial, so it holds only the handful of in-flight rows
            # however large the table grows.
            models.Index(
                fields=['updated_at'],
                name='gemini_req_generating_idx',
                condition=models.Q(status='GENERATING'),
            ),
        ]

    def __str__(self):
        return f"Request {self.id} for {self.workspace.workspace_name}"


class GeminiGenerationResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    generation_request = models.OneToOneField(GeminiGenerationRequest, on_delete=models.CASCADE, related_name='result')
    asset = models.ForeignKey(MarketingAsset, on_delete=models.SET_NULL, null=True, blank=True, related_name='gemini_results')
    
    generated_text = models.TextField(blank=True, null=True)
    generated_asset_url = models.URLField(max_length=1000, blank=True, null=True)
    
    metadata = models.JSONField(default=dict, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'gemini_generation_results'

    def __str__(self):
        return f"Result {self.id} for Request {self.generation_request_id}"
