from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny
from .models import MarketingAsset
from apps.workspaces.models import MarketingWorkspace
from .serializers import MarketingAssetSerializer, UploadAssetSerializer
from .services.storage import SupabaseStorageService
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from apps.common.permissions import (
    IsWorkspaceMember,
    authorize_workspace,
    get_request_workspace,
)
from apps.common.mixins import WorkspaceScopedMixin
from apps.common.responses import APIResponse

class MarketingAssetViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    queryset = MarketingAsset.objects.all()
    serializer_class = MarketingAssetSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember]
    requires_workspace = False


    def perform_create(self, serializer):
        # workspace is read-only on the serializer, so it is assigned here from
        # the caller's authorised workspace rather than the request payload.
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        serializer.save(workspace=workspace, created_by=self.request.user)

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def upload(self, request):
        serializer = UploadAssetSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(success=False, error=serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        workspace_id = serializer.validated_data['workspace_id']
        _membership, denied = authorize_workspace(request, workspace_id)
        if denied:
            return denied
        file_obj = serializer.validated_data['file']
        source = serializer.validated_data['source']
        
        try:
            workspace = MarketingWorkspace.objects.get(id=workspace_id)
        except MarketingWorkspace.DoesNotExist:
            return APIResponse(success=False, message="Workspace not found.", status=status.HTTP_404_NOT_FOUND)

        # Basic File Validation
        if file_obj.size > 50 * 1024 * 1024: # 50 MB limit
            return APIResponse(success=False, message="File too large.", status=status.HTTP_400_BAD_REQUEST)
            
        # Determine asset type
        content_type = file_obj.content_type
        asset_type = MarketingAsset.AssetType.OTHER_SUPPORTED_ASSET
        if content_type.startswith('image/'):
            asset_type = MarketingAsset.AssetType.IMAGE
        elif content_type.startswith('video/'):
            asset_type = MarketingAsset.AssetType.VIDEO
            
        try:
            file_url = SupabaseStorageService.upload_file(str(workspace_id), file_obj, file_obj.name)
            
            asset = MarketingAsset.objects.create(
                workspace=workspace,
                asset_type=asset_type,
                file_name=file_obj.name,
                file_url=file_url,
                mime_type=content_type,
                file_size=file_obj.size,
                source=source,
                created_by=request.user if request.user.is_authenticated else None
            )
            
            return APIResponse(success=True, data=MarketingAssetSerializer(asset).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return APIResponse(success=False, message=str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
