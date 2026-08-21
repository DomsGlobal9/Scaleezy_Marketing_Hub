"""
Inspiration APIs.

Follows the shape established by `apps.knowledge`: workspace-scoped queryset,
role-gated writes, lifecycle changes through named actions rather than PATCH,
and no hard delete on anything that carries provenance.
"""
import mimetypes

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.marketing.services.storage import StorageError, SupabaseStorageService
from apps.workspaces.models import WorkspaceMember

from .models import BrandInspiration, InspirationSignal
from .serializers import (
    BrandInspirationSerializer,
    BrandInspirationUploadSerializer,
    InspirationSignalSerializer,
)


class WorkspaceResolvedViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def _authorised_workspace(self):
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        return workspace


class BrandInspirationViewSet(WorkspaceScopedMixin, WorkspaceResolvedViewSet):
    queryset = BrandInspiration.objects.all()
    serializer_class = BrandInspirationSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        brand_id = self.request.query_params.get('brand_id')
        if brand_id:
            queryset = queryset.filter(brand_id=brand_id)
        # Lets a caller ask for exactly what a future retrieval step would see,
        # instead of reimplementing the eligibility rule client-side.
        if self.request.query_params.get('eligible_only') == 'true':
            queryset = queryset.eligible_for_retrieval()
        return queryset

    def perform_create(self, serializer):
        serializer.save(
            workspace=self._authorised_workspace(), created_by=self.request.user
        )

    def destroy(self, request, *args, **kwargs):
        return APIResponse(
            success=False,
            message="Hard deletion is disabled. Use the archive action instead.",
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        inspiration = self.get_object()
        if inspiration.lifecycle_status == BrandInspiration.LifecycleStatus.ARCHIVED:
            return APIResponse(
                success=False,
                message="Inspiration is already archived.",
                status=status.HTTP_400_BAD_REQUEST,
            )
        inspiration.lifecycle_status = BrandInspiration.LifecycleStatus.ARCHIVED
        inspiration.archived_by = request.user
        inspiration.archived_at = timezone.now()
        inspiration.save(update_fields=['lifecycle_status', 'archived_by', 'archived_at'])
        return APIResponse(
            success=True,
            message="Inspiration archived. It is no longer eligible for retrieval.",
            data=BrandInspirationSerializer(
                inspiration, context=self.get_serializer_context()
            ).data,
        )

    @action(detail=True, methods=['post'])
    def analyze(self, request, pk=None):
        """Placeholder for PR6. Reports honestly that nothing ran."""
        inspiration = self.get_object()
        if inspiration.lifecycle_status == BrandInspiration.LifecycleStatus.ARCHIVED:
            return APIResponse(
                success=False,
                message="Archived inspirations cannot be analysed.",
                status=status.HTTP_400_BAD_REQUEST,
            )
        return APIResponse(
            success=False,
            message="Inspiration analysis is not implemented until PR6.",
            error={
                "code": "NOT_IMPLEMENTED",
                "message": "Inspiration analysis is not implemented until PR6.",
            },
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )

    @action(
        detail=False,
        methods=['post'],
        parser_classes=[MultiPartParser, FormParser],
        url_path='upload',
    )
    def upload(self, request):
        """Multipart entry path for image/screenshot references.

        Deliberately runs the same relation validation as the JSON path before
        anything reaches storage (PR1-007).
        """
        workspace = self._authorised_workspace()
        serializer = BrandInspirationUploadSerializer(
            data=request.data, context={'request': request}
        )
        if not serializer.is_valid():
            return APIResponse(
                success=False, error=serializer.errors, status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data
        file_obj = data['file']
        mime_type = mimetypes.guess_type(file_obj.name)[0] or 'application/octet-stream'

        try:
            stored = SupabaseStorageService.upload_and_describe(
                str(workspace.id), file_obj, file_obj.name, prefix='inspirations'
            )
        except StorageError as exc:
            # No row is written: a reference with no reachable file would be a
            # dead record that later analysis cannot explain.
            return APIResponse(
                success=False, message=str(exc), status=status.HTTP_502_BAD_GATEWAY
            )

        inspiration = BrandInspiration.objects.create(
            workspace=workspace,
            brand=data['brand'],
            source=data.get('source'),
            inspiration_type=data.get(
                'inspiration_type', BrandInspiration.InspirationType.IMAGE
            ),
            title=data.get('title') or file_obj.name,
            annotation=data.get('annotation', ''),
            external_platform=data.get('external_platform', ''),
            usage_scope=data.get('usage_scope', BrandInspiration.UsageScope.FULL_REFERENCE),
            focus_areas=data.get('focus_areas') or [],
            file_url=stored['url'],
            storage_path=stored['path'],
            mime_type=mime_type,
            file_name=file_obj.name,
            created_by=request.user,
        )
        return APIResponse(
            success=True,
            data=BrandInspirationSerializer(
                inspiration, context=self.get_serializer_context()
            ).data,
            status=status.HTTP_201_CREATED,
        )


class InspirationSignalViewSet(WorkspaceScopedMixin, WorkspaceResolvedViewSet):
    queryset = InspirationSignal.objects.all()
    serializer_class = InspirationSignalSerializer
    # Signals hold no workspace column; tenancy is read through the parent.
    workspace_field = 'inspiration__workspace'

    def get_queryset(self):
        queryset = super().get_queryset()
        inspiration_id = self.request.query_params.get('inspiration_id')
        if inspiration_id:
            queryset = queryset.filter(inspiration_id=inspiration_id)
        brand_id = self.request.query_params.get('brand_id')
        if brand_id:
            queryset = queryset.filter(inspiration__brand_id=brand_id)
        if self.request.query_params.get('eligible_only') == 'true':
            queryset = queryset.eligible_for_retrieval()
        return queryset

    def perform_create(self, serializer):
        # Origin is decided here, never by the payload: a signal that arrives
        # through the authenticated API is something a person stated, and it
        # is confirmed by definition.
        serializer.save(
            origin=InspirationSignal.Origin.USER,
            user_confirmation=InspirationSignal.UserConfirmation.CONFIRMED,
            created_by=self.request.user,
            confirmed_by=self.request.user,
            confirmed_at=timezone.now(),
        )

    def destroy(self, request, *args, **kwargs):
        return APIResponse(
            success=False,
            message="Hard deletion is disabled. Use the reject action instead.",
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """A human agrees with a signal.

        This is the authorised path referenced by the PR2 integrity rules. It
        records the human verdict and who gave it — and leaves `origin`
        untouched, so an inference that a user agreed with is still visibly an
        inference.
        """
        signal = self.get_object()
        signal.user_confirmation = InspirationSignal.UserConfirmation.CONFIRMED
        signal.confirmed_by = request.user
        signal.confirmed_at = timezone.now()
        # Agreeing with the inference settles the disagreement it was held for.
        signal.conflicts_with = None
        signal.save(
            update_fields=[
                'user_confirmation', 'confirmed_by', 'confirmed_at', 'conflicts_with',
            ]
        )
        return APIResponse(
            success=True,
            message="Signal confirmed.",
            data=InspirationSignalSerializer(
                signal, context=self.get_serializer_context()
            ).data,
        )

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        signal = self.get_object()
        signal.user_confirmation = InspirationSignal.UserConfirmation.REJECTED
        signal.confirmed_by = request.user
        signal.confirmed_at = timezone.now()
        signal.save(update_fields=['user_confirmation', 'confirmed_by', 'confirmed_at'])
        return APIResponse(
            success=True,
            message="Signal rejected. It is no longer eligible for retrieval.",
            data=InspirationSignalSerializer(
                signal, context=self.get_serializer_context()
            ).data,
        )
