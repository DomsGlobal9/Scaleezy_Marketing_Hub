import uuid

from django.db import models

from apps.workspaces.models import MarketingWorkspace


class Capability(models.TextChoices):
    """
    The unit of routing.

    Providers are not chosen wholesale — a customer may want one AI for copy,
    another for imagery and a third for video. Callers ask for a capability
    and the router decides which provider serves it.
    """

    TEXT = 'TEXT', 'Copy (headline, caption, hashtags)'
    IMAGE = 'IMAGE', 'Image generation'
    IMAGE_ANALYSIS = 'IMAGE_ANALYSIS', 'Image analysis'
    IMAGE_CAPTION = 'IMAGE_CAPTION', 'Image caption generation'
    VIDEO = 'VIDEO', 'Video generation'
    VIDEO_ANALYSIS = 'VIDEO_ANALYSIS', 'Video analysis'
    EMBEDDING = 'EMBEDDING', 'Text embedding (feedback similarity)'


class Strategy(models.TextChoices):
    FAILOVER = 'FAILOVER', 'Failover — first healthy provider wins'
    BEST_OF = 'BEST_OF', 'Best of — run all, keep the highest scoring'
    ROUND_ROBIN = 'ROUND_ROBIN', 'Round robin — spread load and spend'


class ProviderIntegrationType(models.TextChoices):
    INSTALLED = 'INSTALLED', 'Installed adapter'
    OPENAI_COMPATIBLE = 'OPENAI_COMPATIBLE', 'Custom OpenAI-compatible endpoint'
    SCALEEZY_JSON = 'SCALEEZY_JSON', 'Scaleezy universal JSON endpoint'


class AIProvider(models.Model):
    """
    Global catalogue of installed providers.

    A row here means an adapter exists in code. Adding a provider is one new
    adapter file plus one row; nothing in the router changes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_workspace = models.ForeignKey(
        MarketingWorkspace,
        on_delete=models.CASCADE,
        related_name='custom_ai_providers',
        null=True,
        blank=True,
        help_text='Null for platform integrations; set for a tenant-owned custom endpoint.',
    )
    key = models.SlugField(max_length=50, unique=True, help_text="Matches the adapter's key.")
    display_name = models.CharField(max_length=100)
    integration_type = models.CharField(
        max_length=32,
        choices=ProviderIntegrationType.choices,
        default=ProviderIntegrationType.INSTALLED,
    )
    base_url = models.URLField(blank=True, max_length=500)
    capabilities = models.JSONField(
        default=list, help_text="Capability values this provider can serve."
    )
    default_model = models.CharField(max_length=100, blank=True)
    # Operator kill switch: disables the provider for every customer at once.
    is_available = models.BooleanField(default=True)
    unit_cost = models.DecimalField(
        max_digits=10, decimal_places=4, default=0,
        help_text="Indicative cost per generation, used for BEST_OF scoring.",
    )
    docs_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_providers'
        ordering = ['display_name']

    def __str__(self):
        return self.display_name

    def supports(self, capability: str) -> bool:
        return capability in (self.capabilities or [])

    @property
    def is_custom(self) -> bool:
        return self.integration_type != ProviderIntegrationType.INSTALLED


class WorkspaceAIProvider(models.Model):
    """
    Per-customer enablement and credentials. This is the on/off switch.

    Separate from routing: a provider can be connected but not routed to any
    capability yet.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.CASCADE, related_name='ai_providers'
    )
    provider = models.ForeignKey(AIProvider, on_delete=models.CASCADE, related_name='workspaces')

    enabled = models.BooleanField(default=False)
    # Fernet ciphertext, same helper that protects the OAuth tokens. Never
    # serialised back to the client.
    credentials_encrypted = models.TextField(blank=True)
    model_override = models.CharField(max_length=100, blank=True)
    capabilities = models.JSONField(
        default=None,
        null=True,
        blank=True,
        help_text=(
            "Capabilities this workspace assigned to this provider/model. "
            "Must remain within the installed adapter's technical support."
        ),
    )
    max_cost_per_generation = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    config = models.JSONField(default=dict, blank=True)

    last_health_check_at = models.DateTimeField(null=True, blank=True)
    last_health_ok = models.BooleanField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workspace_ai_providers'
        unique_together = ('workspace', 'provider')
        ordering = ['provider__display_name']

    def __str__(self):
        return f"{self.provider.display_name} @ {self.workspace.workspace_name}"

    @property
    def has_credentials(self) -> bool:
        return bool(self.credentials_encrypted)

    def supports(self, capability: str) -> bool:
        return capability in self.assigned_capabilities

    @property
    def assigned_capabilities(self) -> list:
        if self.capabilities is None:
            return list(self.provider.capabilities or [])
        return list(self.capabilities)

    @property
    def configured_models(self) -> list:
        models = (self.config or {}).get('models')
        if isinstance(models, list) and models:
            clean = [str(m).strip() for m in models if str(m).strip()]
            if clean:
                return clean
        if self.model_override:
            return [self.model_override.strip()]
        if self.provider.default_model:
            return [self.provider.default_model.strip()]
        return []


class WorkspaceAIRoute(models.Model):
    """
    Which providers and models serve which capability, in what order.

    This expresses independent, ordered provider/model sets for every capability.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.CASCADE, related_name='ai_routes'
    )
    capability = models.CharField(max_length=32, choices=Capability.choices)
    provider = models.ForeignKey(AIProvider, on_delete=models.CASCADE, related_name='routes')
    model_override = models.CharField(max_length=150, blank=True)

    priority = models.PositiveIntegerField(default=100, help_text="Lower runs first.")
    enabled = models.BooleanField(default=True)
    # Set on any row for a capability; the router reads the first one it finds.
    strategy = models.CharField(
        max_length=20, choices=Strategy.choices, default=Strategy.FAILOVER
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'workspace_ai_routes'
        unique_together = ('workspace', 'capability', 'provider', 'model_override')
        ordering = ['capability', 'priority']

    def __str__(self):
        m = f" ({self.model_override})" if self.model_override else ""
        return f"{self.capability} -> {self.provider.key}{m} (p{self.priority})"


class AIUsageLog(models.Model):
    """Per-call record, for cost attribution and debugging a bad generation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.CASCADE, related_name='ai_usage'
    )
    provider = models.ForeignKey(
        AIProvider, on_delete=models.SET_NULL, null=True, related_name='usage'
    )
    capability = models.CharField(max_length=32, choices=Capability.choices)
    content_item_id = models.UUIDField(null=True, blank=True)

    units = models.PositiveIntegerField(default=1)
    cost = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    success = models.BooleanField(default=True)
    error = models.TextField(blank=True)
    # Which strategy produced this call, and whether it won a BEST_OF race.
    strategy = models.CharField(max_length=20, blank=True)
    selected = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_usage_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['workspace', 'capability']),
        ]

    def __str__(self):
        return f"{self.capability} via {self.provider_id} ({'ok' if self.success else 'failed'})"
