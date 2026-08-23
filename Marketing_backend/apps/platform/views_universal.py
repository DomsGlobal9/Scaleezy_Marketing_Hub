"""
P6 — authoring the universal layer from the console.

Standards and the inspiration library are Scaleezy's own IP, so they have no
tenant and are edited here, behind `IsPlatformAdmin`, never under
/api/marketing/. The lifecycle moves (publish, retire) go through the services
in `apps.universal.services`, which already audit themselves; the plain edits
(create, patch) are audited here.

One rule that is easy to get wrong: a PUBLISHED standard is never edited in
place. It has reached generations, and a trace that names it must stay
explainable — so the console retires it and publishes a successor that
`supersedes` it, which keeps the lineage visible.
"""
import logging
import os
import re
from urllib.parse import urlsplit

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser

from apps.common.responses import APIResponse
from apps.marketing.services.storage import StorageError, SupabaseStorageService
from apps.universal.models import (
    UPLOAD_KINDS,
    EntryKind,
    LifecycleStatus,
    PlatformInspiration,
    UniversalScope,
    UniversalStandard,
)
from apps.universal.serializers import inspiration_payload, standard_payload
from apps.universal.services import (
    adoption_count,
    preview_affected,
    publish_inspiration,
    publish_standard,
    retire_standard,
)

from .views import PlatformView

logger = logging.getLogger(__name__)


def _bad_request(message, code='INVALID'):
    return APIResponse(
        success=False, message=message,
        error={'code': code, 'message': message},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _status_filter(request):
    """`?status=` narrowed to a real lifecycle value; anything else means all."""
    wanted = str(request.query_params.get('status', '')).upper()
    return wanted if wanted in LifecycleStatus.values else ''


# ───────────────────────────────────────────────────────────── standards

STANDARD_REQUIRED = ('title', 'category', 'attribute', 'value', 'guidance')
STANDARD_EDITABLE = STANDARD_REQUIRED + ('rationale', 'scope', 'scope_value', 'supersedes')


def _clean_standard_fields(data, *, partial, current=None):
    """Validate the authoring fields of a standard.

    Returns (fields, error_message). `partial` is the PATCH case: only the
    keys present are validated, but scope and scope_value are checked against
    the merged result so a PATCH cannot leave a non-GLOBAL standard with no
    scope value — such a standard applies to nobody and looks like a rule.
    """
    fields = {}
    for key in STANDARD_REQUIRED + ('rationale', 'scope_value'):
        if key not in data:
            if not partial and key in STANDARD_REQUIRED:
                return None, f"{key} is required."
            continue
        value = data.get(key)
        if not isinstance(value, str):
            return None, f"{key} must be a string."
        value = value.strip()
        if key in STANDARD_REQUIRED and not value:
            return None, f"{key} is required."
        fields[key] = value

    if 'scope' in data:
        scope = str(data.get('scope') or '').upper()
        if scope not in UniversalScope.values:
            return None, (
                f"scope must be one of {', '.join(UniversalScope.values)}."
            )
        fields['scope'] = scope
    elif not partial:
        fields['scope'] = UniversalScope.GLOBAL

    merged_scope = fields.get('scope', getattr(current, 'scope', UniversalScope.GLOBAL))
    merged_value = fields.get('scope_value', getattr(current, 'scope_value', ''))
    if merged_scope == UniversalScope.GLOBAL:
        fields['scope_value'] = ''
    elif not merged_value:
        return None, f"scope_value is required when scope is {merged_scope}."

    if 'supersedes' in data:
        raw = data.get('supersedes')
        if raw in (None, ''):
            fields['supersedes'] = None
        else:
            predecessor = UniversalStandard.objects.filter(pk=str(raw)).first()
            if predecessor is None:
                return None, "supersedes does not name an existing standard."
            if current is not None and predecessor.pk == current.pk:
                return None, "A standard cannot supersede itself."
            fields['supersedes'] = predecessor

    for key in ('title', 'category', 'attribute'):
        limit = {'title': 255, 'category': 64, 'attribute': 64}[key]
        if key in fields and len(fields[key]) > limit:
            return None, f"{key} is longer than {limit} characters."
    if 'value' in fields and len(fields['value']) > 255:
        return None, "value is longer than 255 characters."
    if 'scope_value' in fields and len(fields['scope_value']) > 100:
        return None, "scope_value is longer than 100 characters."
    return fields, None


class StandardListView(PlatformView):
    """GET lists every standard (`?status=` to narrow); POST authors a DRAFT."""

    def get(self, request):
        wanted = _status_filter(request)
        rows = UniversalStandard.objects.select_related('authored_by', 'supersedes')
        if wanted:
            rows = rows.filter(status=wanted)
        rows = list(rows.order_by('-created_at')[:500])
        self.audit('UNIVERSAL_STANDARDS_VIEWED', detail={
            'status': wanted or 'ALL', 'count': len(rows),
        })
        return APIResponse(success=True, data={
            'status': wanted or 'ALL',
            'count': len(rows),
            'standards': [standard_payload(s) for s in rows],
        })

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        fields, error = _clean_standard_fields(data, partial=False)
        if error:
            return _bad_request(error, code='INVALID_STANDARD')
        standard = UniversalStandard.objects.create(authored_by=request.user, **fields)
        self.audit(
            'UNIVERSAL_STANDARD_CREATED', target=f'standard:{standard.pk}',
            detail={'title': standard.title, 'category': standard.category,
                    'attribute': standard.attribute, 'scope': standard.scope,
                    'scope_value': standard.scope_value,
                    'supersedes': str(standard.supersedes_id) if standard.supersedes_id else None},
        )
        return APIResponse(
            success=True, message=f"Draft '{standard.title}' created.",
            data=standard_payload(standard), status=status.HTTP_201_CREATED,
        )


class StandardDetailView(PlatformView):
    """PATCH edits a DRAFT. Published and retired standards are immutable."""

    def patch(self, request, standard_id):
        standard = (
            UniversalStandard.objects.select_related('authored_by', 'supersedes')
            .filter(pk=standard_id).first()
        )
        if standard is None:
            return self.not_found("Standard")
        if standard.status != LifecycleStatus.DRAFT:
            return _bad_request(
                f"A {standard.status.lower()} standard cannot be edited; "
                "retire it and publish a successor that supersedes it instead.",
                code='STANDARD_NOT_DRAFT',
            )

        data = request.data if isinstance(request.data, dict) else {}
        fields, error = _clean_standard_fields(data, partial=True, current=standard)
        if error:
            return _bad_request(error, code='INVALID_STANDARD')

        changes = {}
        for key, value in fields.items():
            before = getattr(standard, key)
            if key == 'supersedes':
                before_repr = str(standard.supersedes_id) if standard.supersedes_id else None
                after_repr = str(value.pk) if value is not None else None
            else:
                before_repr, after_repr = before, value
            if before_repr != after_repr:
                changes[key] = {'from': before_repr, 'to': after_repr}
                setattr(standard, key, value)
        if changes:
            standard.save(update_fields=list(changes) + ['updated_at'])
        self.audit(
            'UNIVERSAL_STANDARD_EDITED', target=f'standard:{standard.pk}',
            detail={'title': standard.title, 'changes': changes},
        )
        return APIResponse(success=True, data=standard_payload(standard))


class StandardLifecycleView(PlatformView):
    """POST .../publish/ | .../retire/ | GET .../preview/ on one standard."""

    def _load(self, standard_id):
        return (
            UniversalStandard.objects.select_related('authored_by', 'supersedes')
            .filter(pk=standard_id).first()
        )

    def post(self, request, standard_id, move):
        standard = self._load(standard_id)
        if standard is None:
            return self.not_found("Standard")

        if move == 'publish':
            # publish_standard audits, and retires what it supersedes.
            publish_standard(standard, by=request.user)
            return APIResponse(
                success=True, message=f"'{standard.title}' is live.",
                data=standard_payload(self._load(standard.pk)),
            )

        if move == 'retire':
            reason = str(request.data.get('reason', '') if isinstance(request.data, dict) else '')[:255]
            retire_standard(standard, by=request.user, reason=reason)
            return APIResponse(
                success=True,
                message=f"'{standard.title}' retired; it stops reaching generations now.",
                data=standard_payload(self._load(standard.pk)),
            )

        return self.not_found("Action")

    def get(self, request, standard_id, move):
        if move != 'preview':
            return self.not_found("Action")
        standard = self._load(standard_id)
        if standard is None:
            return self.not_found("Standard")
        preview = preview_affected(standard)
        self.audit(
            'UNIVERSAL_STANDARD_PREVIEWED', target=f'standard:{standard.pk}',
            detail={'title': standard.title, 'scope': standard.scope,
                    'matched_brand_count': preview['matched_brand_count']},
        )
        return APIResponse(success=True, data={
            'standard': standard_payload(standard),
            **preview,
        })


# ────────────────────────────────────────────────────────── inspirations

INSPIRATION_TEXT_FIELDS = ('title', 'reference_url', 'annotation', 'industry', 'channel', 'body')
INSPIRATION_LIMITS = {
    'title': 255, 'reference_url': 1000, 'industry': 100, 'channel': 64, 'body': 20000,
}

#: The kinds a JSON body may author. Images, videos and files only ever come
#: through `InspirationUploadView`, which derives the kind from the file and
#: never takes one from the request, so kind and content cannot disagree.
AUTHORED_KINDS = (EntryKind.LINK, EntryKind.TEXT)

#: What the upload route accepts, by extension, and the media type each is
#: stored and served as. Our own table rather than `mimetypes`, which reads
#: the host's registry / mime.types and so differs between a Windows laptop
#: and the Linux box the API runs on. Deliberately conservative: the images
#: and video the library can show inline, and the formats a reference deck or
#: brief arrives in. SVG is left out because it can carry script.
UPLOAD_TYPES = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.avif': 'image/avif',
    '.mp4': 'video/mp4', '.m4v': 'video/mp4', '.webm': 'video/webm',
    '.mov': 'video/quicktime',
    '.pdf': 'application/pdf', '.txt': 'text/plain', '.md': 'text/markdown',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.ppt': 'application/vnd.ms-powerpoint',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}
UPLOAD_ACCEPTED = (
    "an image (PNG, JPG, GIF, WebP, AVIF), a video (MP4, WebM, MOV), "
    "a PDF, a text or Markdown file, or a Word / PowerPoint document"
)
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: Where library uploads live in the bucket: `library/platform/<uuid>_<name>`.
#: Outside every workspace's `<prefix>/<workspace_id>/` namespace by
#: construction, so no tenant path can ever resolve to a platform object or
#: the other way round.
PLATFORM_STORAGE_PREFIX = 'library'
PLATFORM_STORAGE_OWNER = 'platform'


def _authored_kind(data):
    """The kind a JSON create asks for. Absent means LINK, as it always did."""
    raw = str(data.get('kind') or EntryKind.LINK).strip().upper()
    if raw in UPLOAD_KINDS:
        return None, (
            "Images, videos and files are added by uploading them "
            "(POST /api/platform/inspirations/upload/)."
        )
    if raw not in AUTHORED_KINDS:
        return None, f"kind must be one of {', '.join(AUTHORED_KINDS)}."
    return raw, None


def _clean_inspiration_fields(data, *, partial, kind, current=None):
    """Validate the authoring fields of a library entry.

    `kind` is what the entry is — on create the requested (or, for an upload,
    the derived) kind; on PATCH the stored one, which cannot change. The
    content rule is checked on the merged result, so a PATCH can neither
    blank a link's URL nor empty a text entry. The file columns are not
    authoring fields at all: only the upload route ever writes them.
    """
    fields = {}
    for key in INSPIRATION_TEXT_FIELDS:
        if key not in data:
            if not partial and key == 'title':
                return None, "title is required."
            continue
        value = data.get(key)
        if not isinstance(value, str):
            return None, f"{key} must be a string."
        value = value.strip()
        if key == 'title' and not value:
            return None, "title is required."
        limit = INSPIRATION_LIMITS.get(key)
        if limit and len(value) > limit:
            return None, f"{key} is longer than {limit} characters."
        fields[key] = value

    if fields.get('reference_url'):
        parts = urlsplit(fields['reference_url'])
        if parts.scheme not in ('http', 'https') or not parts.netloc:
            return None, "reference_url must be an http(s) URL."

    if 'tags' in data:
        tags = data.get('tags')
        if isinstance(tags, str):
            tags = [t for t in (part.strip() for part in tags.split(',')) if t]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            return None, "tags must be a list of strings."
        fields['tags'] = [t.strip()[:64] for t in tags if t.strip()]

    # The content rule, on what the row would hold after the write.
    merged_url = fields.get('reference_url', getattr(current, 'reference_url', ''))
    merged_body = fields.get('body', getattr(current, 'body', ''))
    if kind == EntryKind.LINK and not merged_url:
        return None, "reference_url is required for a link."
    if kind == EntryKind.TEXT and not merged_body:
        return None, "body is required for a text entry."
    return fields, None


def _safe_filename(name):
    """A file name that is safe in a storage path and a public URL.

    Keeps letters, digits, dot, dash and underscore; everything else, spaces
    included, becomes a dash. The extension survives, which matters because
    it is what the upload is classified by.
    """
    base = os.path.basename(str(name or '')).strip()
    stem, ext = os.path.splitext(base)
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', stem).strip('-.') or 'file'
    ext = re.sub(r'[^A-Za-z0-9]', '', ext.lower())
    return (stem[:120] + ('.' + ext if ext else ''))[:255]


def _classify_upload(file_obj, file_name):
    """(kind, mime_type, error) for one uploaded file.

    Classified by extension against our own table, not by the Content-Type
    the browser sent — the extension is what the stored object will be
    served as, and the allowlist is also the mapping.
    """
    if file_obj.size == 0:
        return None, None, "The file is empty."
    if file_obj.size > MAX_UPLOAD_BYTES:
        return None, None, f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
    mime_type = UPLOAD_TYPES.get(os.path.splitext(file_name)[1].lower())
    if mime_type is None:
        return None, None, f"That file type is not accepted. Upload {UPLOAD_ACCEPTED}."
    if mime_type.startswith('image/'):
        kind = EntryKind.IMAGE
    elif mime_type.startswith('video/'):
        kind = EntryKind.VIDEO
    else:
        kind = EntryKind.FILE
    return kind, mime_type, None


def _created(inspiration):
    return APIResponse(
        success=True, message=f"Draft '{inspiration.title}' created.",
        data=inspiration_payload(inspiration), status=status.HTTP_201_CREATED,
    )


class InspirationListView(PlatformView):
    """GET the library with live adoption counts; POST curates a LINK or TEXT draft."""

    def get(self, request):
        wanted = _status_filter(request)
        rows = PlatformInspiration.objects.select_related('curated_by')
        if wanted:
            rows = rows.filter(status=wanted)
        rows = list(rows[:500])
        self.audit('PLATFORM_INSPIRATIONS_VIEWED', detail={
            'status': wanted or 'ALL', 'count': len(rows),
        })
        return APIResponse(success=True, data={
            'status': wanted or 'ALL',
            'count': len(rows),
            'inspirations': [inspiration_payload(i) for i in rows],
        })

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        kind, error = _authored_kind(data)
        if error:
            return _bad_request(error, code='INVALID_INSPIRATION')
        fields, error = _clean_inspiration_fields(data, partial=False, kind=kind)
        if error:
            return _bad_request(error, code='INVALID_INSPIRATION')
        inspiration = PlatformInspiration.objects.create(
            curated_by=request.user, kind=kind, **fields,
        )
        self.audit(
            'PLATFORM_INSPIRATION_CREATED', target=f'inspiration:{inspiration.pk}',
            detail={'title': inspiration.title, 'kind': inspiration.kind,
                    'url': inspiration.reference_url,
                    'industry': inspiration.industry, 'channel': inspiration.channel},
        )
        return _created(inspiration)


class InspirationUploadView(PlatformView):
    """POST multipart — an image, video or file becomes a DRAFT entry.

    The kind is derived from the file, never read from the form. Everything
    else (title, annotation, tags, industry, channel, an optional source URL)
    is validated by the same function the JSON route uses. Nothing is
    written unless the object is actually in storage: a library entry whose
    file never arrived would be a dead card in every client's gallery.
    """

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file_obj = request.FILES.get('file')
        if file_obj is None:
            return _bad_request("file is required.", code='INVALID_UPLOAD')
        file_name = _safe_filename(file_obj.name)
        kind, mime_type, error = _classify_upload(file_obj, file_name)
        if error:
            return _bad_request(error, code='INVALID_UPLOAD')

        # One value per key, as the JSON route sees it. A missing title falls
        # back to the file name, the way the brand-side upload does.
        data = {key: request.data.get(key) for key in request.data}
        if not str(data.get('title') or '').strip():
            data['title'] = file_name
        fields, error = _clean_inspiration_fields(data, partial=False, kind=kind)
        if error:
            return _bad_request(error, code='INVALID_INSPIRATION')

        # Stored and served as what we classified it as, not as whatever the
        # browser claimed, so the card renders what the row says it is.
        file_obj.content_type = mime_type
        try:
            stored = SupabaseStorageService.upload_and_describe(
                PLATFORM_STORAGE_OWNER, file_obj, file_name,
                prefix=PLATFORM_STORAGE_PREFIX,
            )
        except StorageError as exc:
            return APIResponse(
                success=False, message=str(exc),
                error={'code': 'STORAGE_FAILED', 'message': str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        inspiration = PlatformInspiration.objects.create(
            curated_by=request.user, kind=kind,
            file_url=stored['url'][:1000], storage_path=stored['path'][:1000],
            mime_type=mime_type, file_name=file_name,
            **fields,
        )
        self.audit(
            'PLATFORM_INSPIRATION_CREATED', target=f'inspiration:{inspiration.pk}',
            detail={'title': inspiration.title, 'kind': inspiration.kind,
                    'file_name': file_name, 'mime_type': mime_type,
                    'size': file_obj.size, 'url': inspiration.reference_url,
                    'industry': inspiration.industry, 'channel': inspiration.channel},
        )
        return _created(inspiration)


class InspirationDetailView(PlatformView):
    """PATCH edits a reference that is not retired. Its kind and file are fixed."""

    def patch(self, request, inspiration_id):
        inspiration = (
            PlatformInspiration.objects.select_related('curated_by')
            .filter(pk=inspiration_id).first()
        )
        if inspiration is None:
            return self.not_found("Inspiration")
        if inspiration.status == LifecycleStatus.RETIRED:
            return _bad_request(
                "A retired reference is history and cannot be edited.",
                code='INSPIRATION_RETIRED',
            )
        data = request.data if isinstance(request.data, dict) else {}
        if 'kind' in data and str(data.get('kind') or '').strip().upper() != inspiration.kind:
            return _bad_request(
                "kind cannot be changed; add a new entry instead.",
                code='INVALID_INSPIRATION',
            )
        fields, error = _clean_inspiration_fields(
            data, partial=True, kind=inspiration.kind, current=inspiration,
        )
        if error:
            return _bad_request(error, code='INVALID_INSPIRATION')

        changes = {}
        for key, value in fields.items():
            before = getattr(inspiration, key)
            if before != value:
                changes[key] = {'from': before, 'to': value}
                setattr(inspiration, key, value)
        if changes:
            inspiration.save(update_fields=list(changes) + ['updated_at'])
        self.audit(
            'PLATFORM_INSPIRATION_EDITED', target=f'inspiration:{inspiration.pk}',
            detail={'title': inspiration.title, 'changes': changes},
        )
        return APIResponse(success=True, data=inspiration_payload(inspiration))


class InspirationLifecycleView(PlatformView):
    """POST .../publish/ | .../retire/ on one reference."""

    def post(self, request, inspiration_id, move):
        inspiration = (
            PlatformInspiration.objects.select_related('curated_by')
            .filter(pk=inspiration_id).first()
        )
        if inspiration is None:
            return self.not_found("Inspiration")

        if move == 'publish':
            publish_inspiration(inspiration, by=request.user)  # audits itself
            return APIResponse(
                success=True, message=f"'{inspiration.title}' is in the library.",
                data=inspiration_payload(inspiration),
            )

        if move == 'retire':
            reason = str(request.data.get('reason', '') if isinstance(request.data, dict) else '')[:255]
            if inspiration.status != LifecycleStatus.RETIRED:
                # Retire, never delete: brands that adopted it keep their copy
                # and its provenance still resolves to this row.
                inspiration.status = LifecycleStatus.RETIRED
                inspiration.save(update_fields=['status', 'updated_at'])
            self.audit(
                'PLATFORM_INSPIRATION_RETIRED', target=f'inspiration:{inspiration.pk}',
                detail={'title': inspiration.title, 'reason': reason,
                        'adoption_count': adoption_count(inspiration)},
            )
            return APIResponse(
                success=True,
                message=f"'{inspiration.title}' retired; it leaves the client library now.",
                data=inspiration_payload(inspiration),
            )

        return self.not_found("Action")
