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

    prompt_data = models.TextField(blank=True, null=True, help_text="Raw prompt or structure sent to Gemini")
    
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
    
    provider = models.CharField(max_length=50, default='GOOGLE_GEMINI', editable=False)
    model = models.CharField(max_length=100, default='gemini-1.5-pro')

    error_message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'gemini_generation_requests'

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
