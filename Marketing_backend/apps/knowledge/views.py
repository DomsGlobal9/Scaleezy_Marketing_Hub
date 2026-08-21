from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.workspaces.models import WorkspaceMember
from .models import BrandSource, BrandMemory
from .serializers import BrandSourceSerializer, BrandMemorySerializer
from .tasks import process_source

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

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        source = self.get_object()
        if source.status in [BrandSource.SourceStatus.PROCESSING, BrandSource.SourceStatus.QUEUED]:
            return APIResponse(success=False, message="Source is already processing", status=status.HTTP_400_BAD_REQUEST)
            
        source.status = BrandSource.SourceStatus.QUEUED
        source.save(update_fields=['status'])
        
        # Enqueue the background task
        process_source.enqueue(str(source.id))
        
        return APIResponse(success=True, message="Source processing queued")


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
        return APIResponse(success=True, message="Memory confirmed")

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        memory = self.get_object()
        memory.status = BrandMemory.MemoryStatus.REJECTED
        memory.save(update_fields=['status'])
        return APIResponse(success=True, message="Memory rejected")
        
    @action(detail=True, methods=['post'])
    def resolve_conflict(self, request, pk=None):
        # Placeholder for conflict resolution logic (superseding, etc.)
        memory = self.get_object()
        memory.status = BrandMemory.MemoryStatus.CONFIRMED
        memory.save(update_fields=['status'])
        return APIResponse(success=True, message="Conflict resolved")
