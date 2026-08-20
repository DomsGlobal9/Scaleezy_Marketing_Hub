import uuid
from django.db import models
from apps.workspaces.models import MarketingWorkspace
from django.contrib.auth import get_user_model

User = get_user_model()

class MarketingAsset(models.Model):
    class AssetType(models.TextChoices):
        POSTER = 'POSTER', 'Poster'
        IMAGE = 'IMAGE', 'Image'
        VIDEO = 'VIDEO', 'Video'
        OTHER_SUPPORTED_ASSET = 'OTHER_SUPPORTED_ASSET', 'Other Supported Asset'

    class Source(models.TextChoices):
        GEMINI_GENERATED = 'GEMINI_GENERATED', 'Gemini Generated'
        MANUAL_UPLOAD = 'MANUAL_UPLOAD', 'Manual Upload'
        # Composed server-side by the layout engine from the brand's own
        # palette, fonts and photograph — neither generated nor uploaded.
        COMPOSED = 'COMPOSED', 'Composed from brand'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(MarketingWorkspace, on_delete=models.CASCADE, related_name='marketing_assets')

    asset_type = models.CharField(max_length=50, choices=AssetType.choices, default=AssetType.IMAGE)
    file_name = models.CharField(max_length=255)
    file_url = models.URLField(max_length=1000, blank=True, null=True)
    storage_path = models.CharField(max_length=1000, blank=True, null=True)

    mime_type = models.CharField(max_length=100, blank=True, null=True)
    file_size = models.BigIntegerField(blank=True, null=True)

    width = models.IntegerField(blank=True, null=True)
    height = models.IntegerField(blank=True, null=True)
    duration = models.IntegerField(blank=True, null=True, help_text="Duration in seconds for video")

    source = models.CharField(max_length=50, choices=Source.choices)
    generation_id = models.CharField(max_length=255, blank=True, null=True, help_text="Reference to GeminiGenerationResult if applicable")

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_marketing_assets')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'marketing_assets'

    def __str__(self):
        return f"{self.file_name} ({self.workspace.workspace_name})"
