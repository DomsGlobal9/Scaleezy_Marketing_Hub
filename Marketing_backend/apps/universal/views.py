"""
Client-facing universal endpoints. Normal tenant permissions, nothing more.

Every brand-scoped route resolves the brand inside the workspace the request
is authorised for — `Brand.objects.filter(pk=..., workspace=that_workspace)`
— so a brand id from another client is simply not found. Nothing here reads
across tenants: the library is platform-owned and carries no tenant at all,
and adoption writes only into the caller's own workspace.

Provider spend (the note parse, the enrichment fetches) sits behind the same
approval gate as generation, answered with the same 403 envelope.
"""
import logging
import uuid

from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.brands.models import Brand
from apps.brands.services.approval import SpendNotApproved, approval_gate_response
from apps.brands.services.brand_brain import rebuild_brand_brain_safely
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.knowledge.models import BrandMemory, BrandSource
from apps.workspaces.models import WorkspaceMember

from . import enrichment, nl
from .models import PlatformInspiration
from .serializers import inspiration_payload
from .services import UniversalError, adopt_inspiration, gallery_for, settings_for

logger = logging.getLogger(__name__)


def _bad_request(message, code='INVALID'):
    return APIResponse(
        success=False, message=message,
        error={'code': code, 'message': message},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _not_found(what):
    return APIResponse(
        success=False, message=f"{what} not found.",
        error={'code': 'NOT_FOUND', 'message': f"{what} not found."},
        status=status.HTTP_404_NOT_FOUND,
    )


def _spend_refused(exc):
    return APIResponse(
        success=False, message=exc.message,
        error={'code': exc.code, 'message': exc.message},
        status=status.HTTP_403_FORBIDDEN,
    )


class TenantView(APIView):
    """The same gate every tenant-owned viewset uses, on a plain APIView.

    `requires_workspace = False` mirrors the viewsets: the permission layer
    still resolves and checks membership whenever a workspace is named, and
    `_workspace()` then re-resolves and authorises the one the view actually
    acts on, so "checked" and "used" are the same workspace.
    """

    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def _workspace(self):
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        return workspace

    @staticmethod
    def _brand(workspace, brand_id):
        """The brand, only if it lives in the authorised workspace."""
        return Brand.objects.filter(pk=brand_id, workspace=workspace).first()

    @staticmethod
    def _body(request):
        return request.data if isinstance(request.data, dict) else {}


# ──────────────────────────────────────────────────────── natural language

class BrandNoteView(TenantView):
    """POST /brands/<brand>/notes/ {text} -> proposal cards. Writes the note only."""

    def post(self, request, brand_id):
        workspace = self._workspace()
        brand = self._brand(workspace, brand_id)
        if brand is None:
            return _not_found("Brand")

        # The parse is provider spend: refuse before anything is stored, with
        # the envelope generation uses, so the client sees one consistent gate.
        refused = approval_gate_response(workspace)
        if refused is not None:
            return refused

        text = self._body(request).get('text', '')
        if not isinstance(text, str):
            return _bad_request("text must be a string.", code='INVALID_NOTE')
        try:
            note = nl.capture_note(brand, text, user=request.user)
        except nl.NLError as exc:
            return _bad_request(str(exc), code='EMPTY_NOTE')

        try:
            result = nl.propose_from_note(workspace, brand, note, user=request.user)
        except SpendNotApproved as exc:
            # The router's own backstop; the gate above makes this unusual.
            return _spend_refused(exc)
        except nl.NLError as exc:
            # The note is already kept verbatim, so say so: the person's words
            # are not lost and can be re-parsed when a provider is back.
            return APIResponse(
                success=False,
                message=f"Your note was saved but could not be parsed: {exc}",
                error={'code': 'PARSE_UNAVAILABLE', 'message': str(exc)},
                data={'note_id': str(note.pk), 'proposals': []},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return APIResponse(success=True, data=result)


class BrandNoteAcceptView(TenantView):
    """POST /brands/<brand>/notes/<note>/accept/ {proposal} -> the record written."""

    def post(self, request, brand_id, note_id):
        workspace = self._workspace()
        brand = self._brand(workspace, brand_id)
        if brand is None:
            return _not_found("Brand")
        note = BrandSource.objects.filter(
            pk=note_id, brand=brand, workspace=workspace,
        ).first()
        if note is None:
            return _not_found("Note")

        proposal = self._body(request).get('proposal')
        if not isinstance(proposal, dict):
            return _bad_request("proposal must be an object.", code='INVALID_PROPOSAL')
        if not str(proposal.get('text') or proposal.get('value') or '').strip():
            return _bad_request(
                "proposal needs a text or value to save.", code='INVALID_PROPOSAL',
            )

        try:
            record = nl.accept_proposal(
                workspace, brand, proposal, note=note, user=request.user,
            )
        except nl.NLError as exc:
            return _bad_request(str(exc), code='INVALID_PROPOSAL')

        # Accepted intelligence must reach the snapshot generation reads, the
        # same way a rule or fact typed into its own form does.
        rebuild_brand_brain_safely(brand)

        kind = str(proposal.get('kind', '')).upper()
        if isinstance(record, BrandMemory):
            message = "Saved as a confirmed brand fact."
        else:
            message = "Saved as a soft rule the generator will follow."
        return APIResponse(
            success=True, message=message,
            data={'kind': kind, 'id': str(record.pk), 'message': message},
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────── library

class InspirationLibraryView(TenantView):
    """GET /inspirations/library/?industry=&kind= — what this client may browse."""

    def get(self, request):
        workspace = self._workspace()
        industry = str(request.query_params.get('industry', '')).strip()
        kind = str(request.query_params.get('kind', '')).strip().upper()
        rows = gallery_for(workspace, industry=industry, kind=kind)
        return APIResponse(success=True, data={
            'industry': industry,
            'kind': kind,
            'count': len(rows),
            'inspirations': [
                inspiration_payload(row, include_curator=False) for row in rows
            ],
        })


class InspirationAdoptView(TenantView):
    """POST /inspirations/library/<id>/adopt/ {brand_id} -> the brand's own copy."""

    def post(self, request, inspiration_id):
        workspace = self._workspace()
        raw_brand_id = str(self._body(request).get('brand_id', '') or '').strip()
        try:
            brand_id = uuid.UUID(raw_brand_id)
        except ValueError:
            return _bad_request("brand_id must be a brand id.", code='BRAND_REQUIRED')
        brand = self._brand(workspace, brand_id)
        if brand is None:
            return _not_found("Brand")

        # The library is visible only to clients who have not opted out, so
        # adoption is too — otherwise the opt-out is a display setting.
        if not settings_for(workspace).inspirations_enabled:
            return _not_found("Inspiration")
        reference = PlatformInspiration.objects.filter(pk=inspiration_id).first()
        if reference is None:
            return _not_found("Inspiration")

        try:
            adopted, created = adopt_inspiration(reference, brand, user=request.user)
        except UniversalError as exc:
            return _bad_request(str(exc), code='NOT_ADOPTABLE')
        if created:
            rebuild_brand_brain_safely(brand)
        return APIResponse(
            success=True,
            message=(
                "Added to your inspirations." if created
                else "Already in your inspirations."
            ),
            data={
                'inspiration_id': str(adopted.pk),
                'platform_inspiration_id': str(reference.pk),
                'brand_id': str(brand.pk),
                'created': created,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


# ───────────────────────────────────────────────────────────── enrichment

class BrandEnrichView(TenantView):
    """POST /brands/<brand>/enrich/ — one bounded pass over the brand's own site."""

    def post(self, request, brand_id):
        workspace = self._workspace()
        brand = self._brand(workspace, brand_id)
        if brand is None:
            return _not_found("Brand")

        refused = approval_gate_response(workspace)
        if refused is not None:
            return refused
        try:
            report = enrichment.enrich_brand_from_own_site(
                workspace, brand, user=request.user,
            )
        except SpendNotApproved as exc:
            return _spend_refused(exc)
        except enrichment.EnrichmentError as exc:
            return _bad_request(str(exc), code='ENRICHMENT_FAILED')
        return APIResponse(success=True, data=report)
