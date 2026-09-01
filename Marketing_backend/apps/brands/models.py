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
        PENDING = 'PENDING', 'Pending approval'
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
    website = models.URLField(max_length=500, blank=True)
    location = models.CharField(max_length=255, blank=True)

    # What the brand is, and who it is for, in the operator's own words. These
    # are first-party statements, not sourced knowledge — brand guidelines stay
    # in Knowledge, where a source can be revoked and the brain recompiled
    # without it.
    description = models.TextField(blank=True)
    audience = models.TextField(blank=True)

    # Visual identity
    palette = models.JSONField(default=default_palette, blank=True)
    fonts = models.JSONField(default=default_fonts, blank=True)
    # Blank means "no preference", and the compose engine rotates the brand
    # through the whole template catalogue. This must not default to a named
    # pattern: it did, and the phantom "preference" pinned every brand's
    # posters to one skeleton nobody had actually chosen.
    layout_preference = models.CharField(
        max_length=64, choices=Layout.choices, default='', blank=True
    )

    # Voice
    tagline = models.CharField(max_length=255, blank=True)
    cta_keyword = models.CharField(max_length=100, blank=True)
    brand_tone = models.CharField(max_length=255, blank=True)

    # Market context
    instagram_handle = models.CharField(max_length=100, blank=True)
    competitors = models.JSONField(default=list, blank=True)
    # [{name, description}] and {platform: url}. A JSONField stores whatever it
    # is handed, so the shape is enforced in BrandSerializer rather than left
    # to whichever client wrote last.
    products_services = models.JSONField(default=list, blank=True)
    social_links = models.JSONField(default=dict, blank=True)

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

    # Compile health. `creative_brain` alone cannot answer "did the last
    # rebuild work?" — a brain that failed to recompile looks identical to one
    # that never needed to, because the previous snapshot is still sitting in
    # the column. These are what make "Brand Brain compile failures" a real
    # query instead of a tile that reads zero forever.
    brain_compiled_at = models.DateTimeField(null=True, blank=True)
    brain_version = models.CharField(max_length=64, blank=True)
    brain_last_error = models.TextField(blank=True)
    brain_failed_at = models.DateTimeField(null=True, blank=True)

    is_default = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    # Signup approval. A brand that arrives through public signup starts
    # PENDING and cannot run calibration until a Scaleezy operator approves it
    # (see apps.brands.services.approval). Who decided, and when, is a column
    # rather than something reconstructed from logs later. Brands created by
    # an existing member through the app are ACTIVE on creation, as before.
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_brands',
    )

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

    @property
    def is_pending_approval(self) -> bool:
        return self.status == self.Status.PENDING

    @property
    def brain_is_stale(self) -> bool:
        """True when the last compile failed and has not since succeeded.

        Generation still works — it reads the previous snapshot — but what it
        reads no longer reflects the records, which is exactly the condition
        an operator needs surfaced.
        """
        if not self.brain_failed_at:
            return False
        return (
            self.brain_compiled_at is None
            or self.brain_failed_at > self.brain_compiled_at
        )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Exactly one default per workspace. Enforced here rather than with a
        # constraint so that promoting a new default demotes the old one
        # instead of raising.
        if self.is_default:
            Brand.objects.filter(workspace=self.workspace).exclude(pk=self.pk).filter(
                is_default=True
            ).update(is_default=False)
