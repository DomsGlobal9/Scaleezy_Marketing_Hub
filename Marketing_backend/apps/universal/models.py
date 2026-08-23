"""
The universal layer: Scaleezy's own curated intelligence.

Two things live here, and keeping them apart matters:

* `UniversalStandard` — craft standards the Scaleezy team authors. Scaleezy's
  own IP, so no client consent is involved and it is useful from the first
  client.
* `PlatformInspiration` — references the team finds and curates: a link, an
  uploaded image / video / file, or a piece of text, plus the team's own
  annotation. Never anything derived from a client's own material.

Both reach a generation at authority rank 80 or weaker — below every
brand-specific rank (10 hard rule → 70 inspiration signal) — so a universal
standard can never override what a client stated, confirmed, or was learned
from their own behaviour. Both are attributable and switchable off per client.

Nothing here is a source of truth: delete the whole app and every client's own
intelligence is untouched.
"""
import hashlib
import json
import uuid

from django.conf import settings
from django.db import models

#: Weaker than RANK_INSPIRATION_SIGNAL (70), the weakest brand-specific rank.
#: Stated here rather than imported so a change to the brand ranks cannot
#: silently promote the universal layer above them; the test asserts the gap.
RANK_UNIVERSAL_STANDARD = 80
RANK_PLATFORM_INSPIRATION = 85


class UniversalScope(models.TextChoices):
    """How narrowly a standard applies. GLOBAL is the default and the norm."""

    GLOBAL = 'GLOBAL', 'Every client'
    INDUSTRY = 'INDUSTRY', 'One industry'
    CHANNEL = 'CHANNEL', 'One channel'
    CONTENT_TYPE = 'CONTENT_TYPE', 'One content type'


class LifecycleStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    PUBLISHED = 'PUBLISHED', 'Published'
    RETIRED = 'RETIRED', 'Retired'


class UniversalStandard(models.Model):
    """One craft standard, authored by Scaleezy, versioned and retirable.

    Shaped as a claim (category / attribute / value) so it drops straight into
    the same `resolve_claims()` precedence machinery the Brand Brain already
    uses, rather than needing a second resolver that could disagree with it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=255)
    #: Why this standard exists, for the team — never sent to a provider.
    rationale = models.TextField(blank=True)

    #: The claim itself, e.g. category=COPY_STYLE attribute=length value=short.
    category = models.CharField(max_length=64)
    attribute = models.CharField(max_length=64)
    value = models.CharField(max_length=255)
    #: The sentence a generation actually receives.
    guidance = models.TextField()

    scope = models.CharField(
        max_length=20, choices=UniversalScope.choices, default=UniversalScope.GLOBAL
    )
    #: Free text matched case-insensitively against the brand's industry /
    #: channel / content type. Empty for GLOBAL.
    scope_value = models.CharField(max_length=100, blank=True)

    status = models.CharField(
        max_length=20, choices=LifecycleStatus.choices, default=LifecycleStatus.DRAFT
    )
    #: The standard this one replaces, so a correction keeps its lineage
    #: instead of looking like an unrelated new rule.
    supersedes = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='superseded_by',
    )

    authored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='authored_standards',
    )
    published_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'universal_standards'
        ordering = ['category', 'attribute', 'title']
        indexes = [
            models.Index(fields=['status', 'scope']),
            models.Index(fields=['category', 'attribute']),
        ]

    def __str__(self):
        return f"{self.title} ({self.status})"

    @property
    def is_live(self) -> bool:
        return self.status == LifecycleStatus.PUBLISHED

    def applies_to(self, brand, *, channel='', content_type='') -> bool:
        """Whether this standard is in scope for one generation.

        Scope matching is deliberately exact-after-normalisation rather than
        fuzzy: `Brand.industry` is free text, and a standard that leaks into a
        neighbouring industry because of a substring match is worse than one
        that applies to nobody.
        """
        if self.scope == UniversalScope.GLOBAL:
            return True
        target = {
            UniversalScope.INDUSTRY: getattr(brand, 'industry', ''),
            UniversalScope.CHANNEL: channel,
            UniversalScope.CONTENT_TYPE: content_type,
        }.get(self.scope, '')
        return bool(target) and target.strip().casefold() == self.scope_value.strip().casefold()

    def as_claim(self):
        """The shape the Brand Brain's resolver understands."""
        return {
            'category': self.category,
            'attribute': self.attribute,
            'value': self.value,
            'guidance': self.guidance,
            'rank': RANK_UNIVERSAL_STANDARD,
            'origin': 'SCALEEZY_STANDARD',
            'standard_id': str(self.pk),
            'title': self.title,
        }


class EntryKind(models.TextChoices):
    """What a library entry IS. Decides which content field carries it.

    LINK and TEXT are authored as JSON; IMAGE / VIDEO / FILE only ever come
    through the multipart upload route, which derives the kind from the file's
    media type so the kind and the content can never disagree.
    """

    LINK = 'LINK', 'Link'
    IMAGE = 'IMAGE', 'Image'
    VIDEO = 'VIDEO', 'Video'
    FILE = 'FILE', 'File'
    TEXT = 'TEXT', 'Text'


#: The kinds whose content is an uploaded object rather than a URL or text.
UPLOAD_KINDS = (EntryKind.IMAGE, EntryKind.VIDEO, EntryKind.FILE)


class PlatformInspiration(models.Model):
    """A reference the Scaleezy team curated, shared across clients.

    Deliberately holds NO tenant foreign key: the library is platform-owned,
    and a row that could point at a client's own material would be a tenancy
    problem, so it is impossible by construction. What an entry IS is its
    `kind` — a link, an uploaded image / video / file, or a piece of text —
    and exactly one content field carries it (`reference_url`, the file
    columns, or `body`). Uploads live under a platform-owned storage prefix,
    never under any workspace's, and the team that uploads them is the one
    answerable for the rights to do so. Whatever the kind, `annotation` — why
    the team kept it — is the part a client is really given.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=255)
    kind = models.CharField(
        max_length=10, choices=EntryKind.choices, default=EntryKind.LINK
    )
    #: The content of a LINK. Optional on every other kind, where it is the
    #: source the upload or text was taken from — a credit, not the content.
    reference_url = models.URLField(max_length=1000, blank=True, default='')
    #: The content of a TEXT entry: a hook, a headline, a caption, a brief —
    #: the words themselves, as distinct from the annotation about them.
    body = models.TextField(blank=True, default='')
    #: The content of an IMAGE / VIDEO / FILE entry. Server-assigned by the
    #: upload route, never accepted from a request body.
    file_url = models.URLField(max_length=1000, blank=True, default='')
    storage_path = models.CharField(max_length=1000, blank=True, default='')
    mime_type = models.CharField(max_length=100, blank=True, default='')
    file_name = models.CharField(max_length=255, blank=True, default='')
    #: Why the team kept it. This, not the artwork, is the value.
    annotation = models.TextField(blank=True)
    #: e.g. ["minimal", "product-led", "high-contrast"]
    tags = models.JSONField(default=list, blank=True)

    industry = models.CharField(max_length=100, blank=True)
    channel = models.CharField(max_length=64, blank=True)

    status = models.CharField(
        max_length=20, choices=LifecycleStatus.choices, default=LifecycleStatus.DRAFT
    )
    curated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='curated_inspirations',
    )
    published_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'platform_inspirations'
        ordering = ['-published_at', '-created_at']
        indexes = [models.Index(fields=['status', 'industry'])]

    def __str__(self):
        return self.title


class ClientUniversalSettings(models.Model):
    """One client's opt-out of the universal layer.

    A row only exists once somebody changes something, so the default — both
    layers on — costs nothing and needs no backfill.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        'workspaces.MarketingWorkspace', on_delete=models.CASCADE,
        related_name='universal_settings',
    )
    standards_enabled = models.BooleanField(default=True)
    inspirations_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'client_universal_settings'

    def __str__(self):
        return f"{self.workspace_id}: standards={self.standards_enabled}"


def universal_version(standards) -> str:
    """A fingerprint of exactly which standards are live.

    Goes into the generation cache key and the generation trace, so retiring a
    standard invalidates cached context immediately, and "did standard X touch
    client Y" stays answerable after the fact. Without it a retired standard
    would keep being served from cache for the life of the entry.
    """
    payload = json.dumps(
        sorted(
            [
                [str(s.pk), s.category, s.attribute, s.value, s.guidance]
                for s in standards
            ]
        ),
        separators=(',', ':'),
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]
