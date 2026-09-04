"""
Serializers for inspirations.

Every tenant-owned relation is re-checked here against the workspace resolved
from the authenticated request, never against an id the client supplied. The
same checks run for the JSON and the multipart path (PR1-007, GLOBAL-010),
which is why the relation rules live in `validate_reference_graph` rather than
inside one serializer.
"""
import mimetypes
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

from apps.brands.models import Brand
from apps.common.permissions import get_request_workspace
from apps.knowledge.models import BrandSource

from .models import (
    BrandInspiration,
    InspirationSignal,
    ResearchFinding,
    ResearchRun,
    SignalCategory,
)

VALID_FOCUS_AREAS = {choice.value for choice in SignalCategory}
MAX_INSPIRATION_UPLOAD_BYTES = 15 * 1024 * 1024
SUPPORTED_INSPIRATION_UPLOAD_MIME_TYPES = frozenset({
    'image/jpeg', 'image/png', 'image/webp',
})
PIL_FORMAT_MIME_TYPES = {
    'JPEG': 'image/jpeg',
    'PNG': 'image/png',
    'WEBP': 'image/webp',
}
MAX_INSPIRATION_PIXELS = 50_000_000
IMAGE_INSPIRATION_TYPES = frozenset({
    BrandInspiration.InspirationType.IMAGE,
    BrandInspiration.InspirationType.SCREENSHOT,
    BrandInspiration.InspirationType.POST,
    BrandInspiration.InspirationType.AD,
    BrandInspiration.InspirationType.PIN,
    BrandInspiration.InspirationType.REFERENCE,
    BrandInspiration.InspirationType.MOODBOARD,
    # A brand's own poster design, uploaded for generation to match. Image
    # only: the whole point is a picture the generator can reproduce the look
    # of.
    BrandInspiration.InspirationType.BRAND_TEMPLATE,
})


def request_workspace_or_raise(serializer):
    workspace, error = get_request_workspace(serializer.context['request'])
    if error or not workspace:
        raise serializers.ValidationError("Workspace is required and must be valid.")
    return workspace


def validate_reference_graph(workspace, brand, source, usage_scope, focus_areas):
    """The rules that must hold for any inspiration, whatever path created it.

    Raises DRF ValidationError so both the JSON serializer and the upload
    serializer produce the same 400 shape.
    """
    if brand is not None and brand.workspace_id != workspace.id:
        raise serializers.ValidationError(
            {"brand": "Brand must belong to the authorized workspace."}
        )

    if source is not None:
        if source.workspace_id != workspace.id:
            raise serializers.ValidationError(
                {"source": "Source must belong to the authorized workspace."}
            )
        if brand is not None and source.brand_id != brand.id:
            raise serializers.ValidationError(
                {"source": "Source must belong to the same brand as the inspiration."}
            )
        if source.status == BrandSource.SourceStatus.ARCHIVED:
            raise serializers.ValidationError(
                {"source": "Archived sources cannot be used as an inspiration reference."}
            )

    if focus_areas:
        if not isinstance(focus_areas, list):
            raise serializers.ValidationError(
                {"focus_areas": "focus_areas must be a list of signal categories."}
            )
        unknown = [area for area in focus_areas if area not in VALID_FOCUS_AREAS]
        if unknown:
            raise serializers.ValidationError(
                {"focus_areas": f"Unknown signal categories: {', '.join(map(str, unknown))}."}
            )

    # "Use only the typography" has to be storable as something other than a
    # sentence in a free-text note, or no consumer can act on it.
    if usage_scope == BrandInspiration.UsageScope.SPECIFIC_ELEMENTS and not focus_areas:
        raise serializers.ValidationError(
            {"focus_areas": "focus_areas is required when usage_scope is SPECIFIC_ELEMENTS."}
        )
    if usage_scope == BrandInspiration.UsageScope.FULL_REFERENCE and focus_areas:
        raise serializers.ValidationError(
            {"focus_areas": "focus_areas is only allowed when usage_scope is SPECIFIC_ELEMENTS."}
        )


class BrandInspirationSerializer(serializers.ModelSerializer):
    retrieval_eligibility = serializers.SerializerMethodField()

    class Meta:
        model = BrandInspiration
        fields = [
            'id', 'workspace', 'brand', 'source', 'inspiration_type', 'title',
            'annotation', 'reference_url', 'storage_path', 'file_url',
            'mime_type', 'file_name', 'external_platform', 'metadata',
            'usage_scope', 'focus_areas', 'analysis_status', 'lifecycle_status',
            'template_last_used_at',
            'retrieval_eligibility', 'created_by', 'archived_by', 'archived_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'workspace', 'created_by',
            # Lifecycle moves through named actions only (PR1-003).
            'analysis_status', 'lifecycle_status', 'archived_by', 'archived_at',
            # The rotation clock is written by the generation defaulting only.
            'template_last_used_at',
            # Storage coordinates are server-assigned by the upload action; a
            # client that could set them could point a row at another tenant's
            # object.
            'storage_path', 'file_url', 'mime_type', 'file_name',
            'created_at', 'updated_at',
        ]

    def get_retrieval_eligibility(self, obj):
        return obj.retrieval_eligibility()

    def validate_reference_url(self, value):
        if not value:
            return value
        parsed = urlsplit(str(value).strip())
        if parsed.scheme.casefold() != 'https' or not parsed.hostname:
            raise serializers.ValidationError(
                'Inspiration links must use public HTTPS.'
            )
        if parsed.username is not None or parsed.password is not None:
            raise serializers.ValidationError(
                'Inspiration links cannot contain credentials.'
            )
        return str(value).strip()

    #: Written only by `apps.universal.services.adopt_inspiration`. They are
    #: what the platform counts adoptions by and dedupes on, so a client must
    #: not be able to mint them: a row claiming to be adopted from the library
    #: would inflate a count every other tenant and the console can see.
    PLATFORM_METADATA_KEYS = frozenset({
        'adopted_from_platform', 'platform_inspiration_id', 'platform_kind',
        'adopted_at', 'authority_note', 'analysis',
    })

    def validate_metadata(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("metadata must be an object.")
        current = (getattr(self.instance, 'metadata', None) or {})
        forged = sorted(
            key for key in value
            if key in self.PLATFORM_METADATA_KEYS and value[key] != current.get(key)
        )
        if forged:
            raise serializers.ValidationError(
                f"{', '.join(forged)}: set by the platform when a library "
                "reference is adopted; not client-writable."
            )
        # A replacement metadata object must not erase server-owned lineage.
        return {**value, **{key: current[key] for key in self.PLATFORM_METADATA_KEYS if key in current}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Scope the relation querysets the same way the upload and signal
        # serializers do, so another tenant's id is not resolvable on ANY
        # path. `validate()` below still runs: a queryset can express "in my
        # workspace" but not "on this inspiration's brand".
        request = self.context.get('request')
        if request is None:
            return
        workspace, error = get_request_workspace(request)
        if error or not workspace:
            return
        self.fields['brand'].queryset = Brand.objects.filter(workspace=workspace)
        self.fields['source'].queryset = BrandSource.objects.filter(workspace=workspace)

    def validate(self, data):
        workspace = request_workspace_or_raise(self)

        # Evaluate the object as it would be AFTER the write, so a partial
        # PATCH cannot slip past by leaving the offending half unchanged
        # (PR1-008).
        brand = data.get('brand') or getattr(self.instance, 'brand', None)
        source = data.get('source') or getattr(self.instance, 'source', None)
        usage_scope = data.get(
            'usage_scope',
            getattr(self.instance, 'usage_scope', BrandInspiration.UsageScope.FULL_REFERENCE),
        )
        focus_areas = data.get('focus_areas', getattr(self.instance, 'focus_areas', None) or [])

        if self.instance is not None:
            if 'brand' in data and data['brand'] != self.instance.brand:
                raise serializers.ValidationError(
                    {"brand": "Brand cannot be changed once set. No transfer workflow exists."}
                )
            if 'source' in data and data['source'] != self.instance.source:
                raise serializers.ValidationError(
                    {"source": "Source cannot be changed once set; provenance is immutable."}
                )
            for field in ('reference_url', 'inspiration_type', 'external_platform'):
                if field in data and data[field] != getattr(self.instance, field):
                    raise serializers.ValidationError({
                        field: "Reference evidence is immutable. Add the replacement reference and archive this one."
                    })

        validate_reference_graph(workspace, brand, source, usage_scope, focus_areas)

        if self.instance is None:
            reference_url = data.get('reference_url')
            if not reference_url and source is None:
                raise serializers.ValidationError(
                    "An inspiration needs a reference: provide source, reference_url, "
                    "or use the upload endpoint."
                )

        return data


class BrandInspirationUploadSerializer(serializers.Serializer):
    """Multipart entry path. Same relation rules as the JSON path."""

    file = serializers.FileField(required=True)
    brand = serializers.PrimaryKeyRelatedField(queryset=Brand.objects.none(), required=True)
    source = serializers.PrimaryKeyRelatedField(
        queryset=BrandSource.objects.none(), required=False, allow_null=True
    )
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    inspiration_type = serializers.ChoiceField(
        choices=BrandInspiration.InspirationType.choices,
        required=False,
        default=BrandInspiration.InspirationType.IMAGE,
    )
    annotation = serializers.CharField(required=False, allow_blank=True, default='')
    external_platform = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=''
    )
    usage_scope = serializers.ChoiceField(
        choices=BrandInspiration.UsageScope.choices,
        required=False,
        default=BrandInspiration.UsageScope.FULL_REFERENCE,
    )
    focus_areas = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Scope the relation querysets to the caller's workspace so an id from
        # another tenant is not even resolvable, then re-validate in validate()
        # for the same-brand rule that a queryset cannot express.
        request = self.context.get('request')
        if request is None:
            return
        workspace, error = get_request_workspace(request)
        if error or not workspace:
            return
        self.fields['brand'].queryset = Brand.objects.filter(workspace=workspace)
        self.fields['source'].queryset = BrandSource.objects.filter(workspace=workspace)

    def validate_file(self, file_obj):
        """Reject bytes this poster-reference path cannot truthfully analyse."""
        size = int(getattr(file_obj, 'size', 0) or 0)
        if size <= 0:
            raise serializers.ValidationError('The inspiration file is empty.')
        if size > MAX_INSPIRATION_UPLOAD_BYTES:
            raise serializers.ValidationError(
                'The inspiration file exceeds the 15 MB upload limit.'
            )

        declared = str(getattr(file_obj, 'content_type', '') or '')
        declared = declared.split(';', 1)[0].strip().casefold()
        guessed = (mimetypes.guess_type(str(file_obj.name or ''))[0] or '').casefold()
        if (
            declared
            and declared != 'application/octet-stream'
            and guessed
            and declared != guessed
        ):
            raise serializers.ValidationError('The file type does not match its filename.')
        mime_type = (
            declared
            if declared in SUPPORTED_INSPIRATION_UPLOAD_MIME_TYPES
            else guessed
            if declared in ('', 'application/octet-stream')
            else ''
        )
        if mime_type not in SUPPORTED_INSPIRATION_UPLOAD_MIME_TYPES:
            raise serializers.ValidationError(
                'Unsupported inspiration file. Upload a JPEG, PNG, or WebP image.'
            )
        if len(str(file_obj.name or '')) > 255:
            raise serializers.ValidationError('The inspiration filename is too long.')

        try:
            file_obj.seek(0)
            with Image.open(file_obj) as image:
                if image.width * image.height > MAX_INSPIRATION_PIXELS:
                    raise serializers.ValidationError(
                        'The inspiration image dimensions are too large.'
                    )
                actual_mime = PIL_FORMAT_MIME_TYPES.get(str(image.format or '').upper())
                image.verify()
        except serializers.ValidationError:
            raise
        except (
            Image.DecompressionBombError,
            UnidentifiedImageError,
            OSError,
            ValueError,
        ) as exc:
            raise serializers.ValidationError(
                'The uploaded file is not a readable JPEG, PNG, or WebP image.'
            ) from exc
        finally:
            file_obj.seek(0)
        if actual_mime != mime_type:
            raise serializers.ValidationError(
                'The file contents do not match the declared image type.'
            )
        file_obj.content_type = mime_type
        return file_obj

    def validate(self, data):
        workspace = request_workspace_or_raise(self)
        inspiration_type = data.get(
            'inspiration_type', BrandInspiration.InspirationType.IMAGE
        )
        if inspiration_type not in IMAGE_INSPIRATION_TYPES:
            raise serializers.ValidationError({
                'inspiration_type': (
                    'Uploaded poster references must be an image-based inspiration.'
                )
            })
        validate_reference_graph(
            workspace,
            data.get('brand'),
            data.get('source'),
            data.get('usage_scope', BrandInspiration.UsageScope.FULL_REFERENCE),
            data.get('focus_areas') or [],
        )
        return data


class InspirationSignalSerializer(serializers.ModelSerializer):
    workspace = serializers.UUIDField(source='workspace_id', read_only=True)
    brand = serializers.UUIDField(source='brand_id', read_only=True)
    retrieval_eligibility = serializers.SerializerMethodField()
    # The model defaults to NEUTRAL so existing rows stay valid, but the API
    # refuses to guess: liked/disliked/neutral is a statement, not a default.
    sentiment = serializers.ChoiceField(
        choices=InspirationSignal.Sentiment.choices, required=True
    )

    class Meta:
        model = InspirationSignal
        fields = [
            'id', 'inspiration', 'workspace', 'brand', 'category', 'attribute',
            'value', 'sentiment', 'weight', 'confidence', 'origin',
            'user_confirmation', 'conflicts_with', 'extracted_by_provider',
            'normalized_attribute', 'normalized_value',
            'superseded_at', 'superseded_by', 'superseded_reason',
            'retrieval_eligibility', 'created_by', 'confirmed_by',
            'confirmed_at', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id',
            # `workspace` and `brand` are declared above as read-only mirrors
            # of the parent inspiration, so they must not be repeated here.
            # Provenance is assigned by the server. A client cannot mint a
            # USER-origin signal for something a model inferred, and cannot
            # move an AI signal to USER afterwards.
            'origin', 'extracted_by_provider',
            # Confirmation moves through the confirm/reject actions only.
            'user_confirmation', 'conflicts_with', 'created_by', 'confirmed_by',
            'confirmed_at', 'created_at', 'updated_at',
            # Derived and audit-only. The folded copies are what identity and
            # equality are decided on, so a client must never supply them; the
            # supersession trail is written by the service.
            'normalized_attribute', 'normalized_value',
            'superseded_at', 'superseded_by', 'superseded_reason',
        ]

    def get_retrieval_eligibility(self, obj):
        return obj.retrieval_eligibility()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is None:
            return
        workspace, error = get_request_workspace(request)
        if error or not workspace:
            return
        self.fields['inspiration'].queryset = BrandInspiration.objects.filter(
            workspace=workspace
        )

    def validate(self, data):
        workspace = request_workspace_or_raise(self)

        inspiration = data.get('inspiration') or getattr(self.instance, 'inspiration', None)
        if inspiration is None:
            raise serializers.ValidationError({"inspiration": "This field is required."})

        # Belt and braces: the queryset above already excludes other tenants,
        # but this is the check that survives a future refactor of the field.
        if inspiration.workspace_id != workspace.id:
            raise serializers.ValidationError(
                {"inspiration": "Inspiration must belong to the authorized workspace."}
            )

        if self.instance is not None:
            if 'inspiration' in data and data['inspiration'] != self.instance.inspiration:
                raise serializers.ValidationError(
                    {"inspiration": "A signal cannot be moved to another inspiration."}
                )

            # What a preference SAYS is append-only. Editing it in place would
            # rewrite the record of what a brand believed, with no trace that
            # it ever said anything else — and the supersession history the
            # audit rules require would simply not exist. Changing your mind is
            # a new signal, which retires this one and says so.
            for field in ('category', 'attribute', 'value', 'sentiment'):
                if field in data and data[field] != getattr(self.instance, field):
                    raise serializers.ValidationError(
                        {
                            field: (
                                "A stated preference cannot be edited. Create a new "
                                "signal for this attribute; it will supersede this one "
                                "and this one stays on the record."
                            )
                        }
                    )

        if self.instance is None:
            if inspiration.lifecycle_status == BrandInspiration.LifecycleStatus.ARCHIVED:
                raise serializers.ValidationError(
                    {"inspiration": "Archived inspirations cannot receive new signals."}
                )

        return data


class ResearchFindingSerializer(serializers.ModelSerializer):
    workspace = serializers.UUIDField(source='workspace_id', read_only=True)
    brand = serializers.UUIDField(source='brand_id', read_only=True)
    run = serializers.UUIDField(source='run_id', read_only=True)
    adopted_inspiration = serializers.UUIDField(
        source='adopted_inspiration_id', read_only=True
    )

    class Meta:
        model = ResearchFinding
        fields = [
            'id', 'run', 'workspace', 'brand', 'kind', 'title', 'source_url', 'preview_url',
            'source_name', 'platform', 'excerpt', 'observed_at', 'rights_status',
            'verification_status', 'verification_error', 'source_content_hash',
            'adopted_inspiration', 'adopted_at', 'created_at',
        ]
        read_only_fields = fields


class ResearchRunSerializer(serializers.ModelSerializer):
    workspace = serializers.UUIDField(source='workspace_id', read_only=True)
    findings = ResearchFindingSerializer(many=True, read_only=True)

    class Meta:
        model = ResearchRun
        fields = [
            'id', 'workspace', 'brand', 'query', 'objectives', 'sources',
            'status', 'result_count', 'provider_key', 'provider_name', 'task_id',
            'error', 'started_at', 'completed_at', 'created_at', 'findings',
        ]
        read_only_fields = [
            'id', 'workspace', 'status', 'result_count', 'provider_key',
            'provider_name', 'task_id', 'error', 'started_at', 'completed_at',
            'created_at', 'findings',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is None:
            return
        workspace, error = get_request_workspace(request)
        if error or not workspace:
            return
        self.fields['brand'].queryset = Brand.objects.filter(workspace=workspace)

    @staticmethod
    def _bounded_strings(value, field):
        if not isinstance(value, list):
            raise serializers.ValidationError({field: 'Must be a list.'})
        out = []
        for item in value[:12]:
            text = ' '.join(str(item or '').split())[:255]
            if text and text not in out:
                out.append(text)
        return out

    def validate(self, data):
        workspace = request_workspace_or_raise(self)
        brand = data.get('brand')
        if brand is None or brand.workspace_id != workspace.id:
            raise serializers.ValidationError(
                {'brand': 'Brand must belong to the authorized workspace.'}
            )
        query = ' '.join(str(data.get('query') or '').split())
        if len(query) < 3:
            raise serializers.ValidationError({'query': 'Describe what to research.'})
        data['query'] = query[:1000]
        data['objectives'] = self._bounded_strings(data.get('objectives') or [], 'objectives')
        data['sources'] = self._bounded_strings(data.get('sources') or [], 'sources')
        return data
