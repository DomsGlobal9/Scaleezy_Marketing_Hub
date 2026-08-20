import uuid

from django.conf import settings
from django.db import models

from apps.workspaces.models import MarketingWorkspace


def default_palette():
    """Ink / cream / accent. Matches the shape the poster layouts expect."""
    return {"primary": "#221F3C", "light": "#FDFFE9", "accent": "#D2FFAA"}


def default_fonts():
    return {"primary": "DM Sans", "secondary": "Noto Serif"}


class Brand(models.Model):
    """
    A brand within a workspace: its visual identity, voice, and the rules the
    generator has learned about it.

    Replaces the browser-local brand kit, which held only a logo and a phone
    number in localStorage and was therefore lost on a browser change and
    invisible to the server that actually renders posters.
    """

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        ARCHIVED = 'ARCHIVED', 'Archived'

    class Layout(models.TextChoices):
        AGENCY_COLUMN = 'agency_column', 'Agency column'
        JIL_SANDER = 'jil_sander', 'Minimal centred'
        COS_SPLIT = 'cos_split', 'Split tone'
        DATA_HERO = 'data_hero', 'Data hero'
        GHOST_WORD = 'ghost_word', 'Ghost word'
        VS_TABLE = 'vs_table', 'Versus table'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        MarketingWorkspace, on_delete=models.CASCADE, related_name='brands'
    )

    name = models.CharField(max_length=255)
    industry = models.CharField(max_length=100, blank=True)

    # Visual identity
    palette = models.JSONField(default=default_palette, blank=True)
    fonts = models.JSONField(default=default_fonts, blank=True)
    layout_preference = models.CharField(
        max_length=64, choices=Layout.choices, default=Layout.AGENCY_COLUMN
    )

    # Voice
    tagline = models.CharField(max_length=255, blank=True)
    cta_keyword = models.CharField(max_length=100, blank=True)
    brand_tone = models.CharField(max_length=255, blank=True)

    # Market context
    instagram_handle = models.CharField(max_length=100, blank=True)
    competitors = models.JSONField(default=list, blank=True)

    # Logo. Stored on the brand rather than as a MarketingAsset so brand
    # artwork does not appear in the publishable asset library.
    logo_url = models.URLField(max_length=1000, blank=True)
    logo_storage_path = models.CharField(max_length=1000, blank=True)
    logo_file_name = models.CharField(max_length=255, blank=True)

    contact_phone = models.CharField(max_length=50, blank=True)

    # Defaults for the poster generator; overridable per generation.
    show_logo_on_posters = models.BooleanField(default=False)
    show_phone_on_posters = models.BooleanField(default=False)

    # Accumulated taste rules. Phase 6's training engine appends here, and the
    # generator feeds it back into each prompt.
    creative_brain = models.JSONField(default=dict, blank=True)

    is_default = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_brands',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'brands'
        ordering = ['-is_default', 'name']
        # Two brands may share a name across workspaces, never within one.
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'name'], name='unique_brand_name_per_workspace'
            )
        ]
        indexes = [models.Index(fields=['workspace', 'status'])]

    def __str__(self):
        return f"{self.name} ({self.workspace.workspace_name})"

    @property
    def has_logo(self) -> bool:
        return bool(self.logo_url)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Exactly one default per workspace. Enforced here rather than with a
        # constraint so that promoting a new default demotes the old one
        # instead of raising.
        if self.is_default:
            Brand.objects.filter(workspace=self.workspace).exclude(pk=self.pk).filter(
                is_default=True
            ).update(is_default=False)
