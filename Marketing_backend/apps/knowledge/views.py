from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
import mimetypes

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.workspaces.models import WorkspaceMember
from apps.brands.services.brand_brain import rebuild_brand_brain_safely
from apps.marketing.services.storage import StorageError, SupabaseStorageService
from .models import BrandSource, BrandMemory
from .serializers import BrandSourceSerializer, BrandMemorySerializer, BrandSourceUploadSerializer

class BrandSourceViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    queryset = BrandSource.objects.all()
    serializer_class = BrandSourceSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def _authorised_workspace(self):
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        return workspace

    def get_queryset(self):
        queryset = super().get_queryset()
        brand_id = self.request.query_params.get('brand_id')
        if brand_id:
            queryset = queryset.filter(brand_id=brand_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(
            workspace=self._authorised_workspace(),
            created_by=self.request.user
        )

    def destroy(self, request, *args, **kwargs):
        # Hard deletion is disabled to maintain provenance. Use revoke instead.
        return APIResponse(success=False, message="Hard deletion is disabled. Use the revoke action instead.", status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        source = self.get_object()
        if source.status == BrandSource.SourceStatus.ARCHIVED:
            return APIResponse(success=False, message="Source is already archived", status=status.HTTP_400_BAD_REQUEST)
        
        source.status = BrandSource.SourceStatus.ARCHIVED
        source.save(update_fields=['status'])

        # Memories from an archived source stop influencing the brain on the
        # next compile (PR1-010); compile now so the snapshot reflects it.
        rebuild_brand_brain_safely(source.brand)
        return APIResponse(success=True, message="Source archived successfully")

    @action(
        detail=False,
        methods=['post'],
        parser_classes=[MultiPartParser, FormParser],
        url_path='upload',
    )
    def upload(self, request):
        workspace = self._authorised_workspace()
        serializer = BrandSourceUploadSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return APIResponse(success=False, error=serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        file_obj = serializer.validated_data['file']
        brand = serializer.validated_data['brand']
        brand_id = brand.id

        # Basic mime type guess
        mime_type, _ = mimetypes.guess_type(file_obj.name)
        if not mime_type:
            mime_type = 'application/octet-stream'

        try:
            stored = SupabaseStorageService.upload_and_describe(
                str(workspace.id), file_obj, file_obj.name, prefix='knowledge-sources'
            )
        except StorageError as exc:
            return APIResponse(success=False, message=str(exc), status=status.HTTP_502_BAD_GATEWAY)

        # Create source
        source = BrandSource.objects.create(
            workspace=workspace,
            brand_id=brand_id,
            source_type=serializer.validated_data.get(
                'source_type', BrandSource.SourceType.DOCUMENT
            ),
            title=(serializer.validated_data.get('title') or file_obj.name)[:255],
            file_url=stored['url'],
            storage_path=stored['path'],
            mime_type=mime_type,
            file_name=file_obj.name,
            status=BrandSource.SourceStatus.UPLOADED,
            created_by=request.user
        )
        return APIResponse(success=True, data=BrandSourceSerializer(source).data)

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        source = self.get_object()
        if source.status == BrandSource.SourceStatus.ARCHIVED:
            return APIResponse(success=False, message="Archived sources cannot be processed", status=status.HTTP_400_BAD_REQUEST)
            
        return APIResponse(
            success=False, 
            message="Processing is not implemented until PR6.", 
            status=status.HTTP_501_NOT_IMPLEMENTED
        )


class BrandMemoryViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    queryset = BrandMemory.objects.all()
    serializer_class = BrandMemorySerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def _authorised_workspace(self):
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        return workspace

    def get_queryset(self):
        queryset = super().get_queryset()
        brand_id = self.request.query_params.get('brand_id')
        if brand_id:
            queryset = queryset.filter(brand_id=brand_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(workspace=self._authorised_workspace())

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        memory = self.get_object()
        memory.status = BrandMemory.MemoryStatus.CONFIRMED
        memory.save(update_fields=['status'])
        # A confirmed fact is intelligence; the snapshot must carry it.
        rebuild_brand_brain_safely(memory.brand)
        return APIResponse(success=True, message="Memory confirmed")

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        memory = self.get_object()
        memory.status = BrandMemory.MemoryStatus.REJECTED
        memory.save(update_fields=['status'])
        rebuild_brand_brain_safely(memory.brand)
        return APIResponse(success=True, message="Memory rejected")
