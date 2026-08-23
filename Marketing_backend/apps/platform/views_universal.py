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
from urllib.parse import urlsplit

from rest_framework import status

from apps.common.responses import APIResponse
from apps.universal.models import (
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

INSPIRATION_TEXT_FIELDS = ('title', 'reference_url', 'annotation', 'industry', 'channel')


def _clean_inspiration_fields(data, *, partial):
    fields = {}
    for key in INSPIRATION_TEXT_FIELDS:
        if key not in data:
            if not partial and key in ('title', 'reference_url'):
                return None, f"{key} is required."
            continue
        value = data.get(key)
        if not isinstance(value, str):
            return None, f"{key} must be a string."
        value = value.strip()
        if key in ('title', 'reference_url') and not value:
            return None, f"{key} is required."
        fields[key] = value

    if 'reference_url' in fields:
        parts = urlsplit(fields['reference_url'])
        if parts.scheme not in ('http', 'https') or not parts.netloc:
            return None, "reference_url must be an http(s) URL."
        if len(fields['reference_url']) > 1000:
            return None, "reference_url is longer than 1000 characters."

    if 'tags' in data:
        tags = data.get('tags')
        if isinstance(tags, str):
            tags = [t for t in (part.strip() for part in tags.split(',')) if t]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            return None, "tags must be a list of strings."
        fields['tags'] = [t.strip()[:64] for t in tags if t.strip()]

    if 'title' in fields and len(fields['title']) > 255:
        return None, "title is longer than 255 characters."
    if 'industry' in fields and len(fields['industry']) > 100:
        return None, "industry is longer than 100 characters."
    if 'channel' in fields and len(fields['channel']) > 64:
        return None, "channel is longer than 64 characters."
    return fields, None


class InspirationListView(PlatformView):
    """GET the library with live adoption counts; POST curates a DRAFT."""

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
        fields, error = _clean_inspiration_fields(data, partial=False)
        if error:
            return _bad_request(error, code='INVALID_INSPIRATION')
        inspiration = PlatformInspiration.objects.create(curated_by=request.user, **fields)
        self.audit(
            'PLATFORM_INSPIRATION_CREATED', target=f'inspiration:{inspiration.pk}',
            detail={'title': inspiration.title, 'url': inspiration.reference_url,
                    'industry': inspiration.industry, 'channel': inspiration.channel},
        )
        return APIResponse(
            success=True, message=f"Draft reference '{inspiration.title}' created.",
            data=inspiration_payload(inspiration), status=status.HTTP_201_CREATED,
        )


class InspirationDetailView(PlatformView):
    """PATCH edits a reference that is not retired."""

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
        fields, error = _clean_inspiration_fields(data, partial=True)
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
