import uuid
from django.db import models
from django.conf import settings

class BrandSource(models.Model):
    class SourceType(models.TextChoices):
        WEBSITE = 'WEBSITE', 'Website'
        URL = 'URL', 'URL'
        PDF = 'PDF', 'PDF'
        DOCUMENT = 'DOCUMENT', 'Document'
        TRANSCRIPT = 'TRANSCRIPT', 'Transcript'
        MOM = 'MOM', 'Minutes of Meeting'
        AUDIO = 'AUDIO', 'Audio'
        VIDEO = 'VIDEO', 'Video'
        NOTE = 'NOTE', 'Note'
        EMAIL_EXPORT = 'EMAIL_EXPORT', 'Email Export'
        PRODUCT_DOC = 'PRODUCT_DOC', 'Product Documentation'
        SALES_CALL = 'SALES_CALL', 'Sales Call'
        CUSTOMER_CALL = 'CUSTOMER_CALL', 'Customer Call'
        OTHER = 'OTHER', 'Other'

    class SourceStatus(models.TextChoices):
        UPLOADED = 'UPLOADED', 'Uploaded'
        QUEUED = 'QUEUED', 'Queued'
        PROCESSING = 'PROCESSING', 'Processing'
        READY = 'READY', 'Ready'
        NEEDS_REVIEW = 'NEEDS_REVIEW', 'Needs Review'
        FAILED = 'FAILED', 'Failed'
        ARCHIVED = 'ARCHIVED', 'Archived'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey('workspaces.MarketingWorkspace', on_delete=models.CASCADE, related_name='knowledge_sources')
    brand = models.ForeignKey('brands.Brand', on_delete=models.CASCADE, related_name='knowledge_sources')
    
    source_type = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.OTHER)
    title = models.CharField(max_length=255)
    
    source_url = models.URLField(max_length=1000, blank=True, null=True)
    storage_path = models.CharField(max_length=1000, blank=True, null=True)
    file_url = models.URLField(max_length=1000, blank=True, null=True)
    mime_type = models.CharField(max_length=100, blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    
    language = models.CharField(max_length=10, blank=True, null=True)
    status = models.CharField(max_length=20, choices=SourceStatus.choices, default=SourceStatus.UPLOADED)
    
    raw_text = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='knowledge_sources_created')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.source_type})"

    class Meta:
        ordering = ['-created_at']


class BrandMemory(models.Model):
    class MemoryType(models.TextChoices):
        FACT = 'FACT', 'Fact'
        BRAND_CANON = 'BRAND_CANON', 'Brand Canon'
        PRODUCT_TRUTH = 'PRODUCT_TRUTH', 'Product Truth'
        FOUNDER_POV = 'FOUNDER_POV', 'Founder POV'
        POSITIONING_SIGNAL = 'POSITIONING_SIGNAL', 'Positioning Signal'
        BUYER_PAIN = 'BUYER_PAIN', 'Buyer Pain'
        OBJECTION = 'OBJECTION', 'Objection'
        EVIDENCE = 'EVIDENCE', 'Evidence'
        DECISION = 'DECISION', 'Decision'
        CONTENT_IDEA = 'CONTENT_IDEA', 'Content Idea'
        CAMPAIGN_CONTEXT = 'CAMPAIGN_CONTEXT', 'Campaign Context'
        ACTION_ITEM = 'ACTION_ITEM', 'Action Item'
        CONFLICT = 'CONFLICT', 'Conflict'

    class MemoryScope(models.TextChoices):
        ASSET = 'ASSET', 'Asset'
        CAMPAIGN = 'CAMPAIGN', 'Campaign'
        BRAND = 'BRAND', 'Brand'
        TENANT = 'TENANT', 'Tenant'

    class MemoryPermanence(models.TextChoices):
        TEMPORARY = 'TEMPORARY', 'Temporary'
        EMERGING = 'EMERGING', 'Emerging'
        PERMANENT = 'PERMANENT', 'Permanent'

    class MemoryStatus(models.TextChoices):
        CANDIDATE = 'CANDIDATE', 'Candidate'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        REJECTED = 'REJECTED', 'Rejected'
        SUPERSEDED = 'SUPERSEDED', 'Superseded'
        EXPIRED = 'EXPIRED', 'Expired'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey('workspaces.MarketingWorkspace', on_delete=models.CASCADE, related_name='memories')
    brand = models.ForeignKey('brands.Brand', on_delete=models.CASCADE, related_name='memories')
    source = models.ForeignKey(BrandSource, on_delete=models.SET_NULL, null=True, blank=True, related_name='extracted_memories')
    
    memory_type = models.CharField(max_length=30, choices=MemoryType.choices)
    content = models.TextField()
    normalized_key = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    confidence = models.FloatField(default=0.0)
    
    scope = models.CharField(max_length=20, choices=MemoryScope.choices, default=MemoryScope.BRAND)
    permanence = models.CharField(max_length=20, choices=MemoryPermanence.choices, default=MemoryPermanence.EMERGING)
    status = models.CharField(max_length=20, choices=MemoryStatus.choices, default=MemoryStatus.CANDIDATE)
    
    valid_from = models.DateTimeField(blank=True, null=True)
    valid_until = models.DateTimeField(blank=True, null=True)
    
    supersedes = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='superseded_by')
    
    embedding = models.JSONField(blank=True, null=True)
    embedding_model = models.CharField(max_length=100, blank=True, null=True)
    extracted_by_provider = models.CharField(max_length=100, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.memory_type}: {self.content[:50]}"

    class Meta:
        ordering = ['-created_at']
