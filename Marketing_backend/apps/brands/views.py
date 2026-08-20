import logging

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

from .models import Brand
from .serializers import BrandLogoUploadSerializer, BrandSerializer

logger = logging.getLogger(__name__)

MAX_LOGO_BYTES = 2 * 1024 * 1024


class BrandViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    """
    Brands belonging to the caller's workspaces.

    Reads are open to any member; writes require EDITOR or above, since brand
    identity drives every generated poster.
    """

    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    # Lists are scoped by WorkspaceScopedMixin; writes resolve and authorise
    # the workspace explicitly in perform_create.
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def _authorised_workspace(self):
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        return workspace

    def perform_create(self, serializer):
        serializer.save(
            workspace=self._authorised_workspace(),
            created_by=self.request.user,
        )

    @action(detail=False, methods=['get'])
    def current(self, request):
        """
        The workspace's default brand, creating one on first use.

        The frontend has a single brand kit today, so this gives it a stable
        endpoint that does not need to know a brand id.
        """
        workspace, error = get_request_workspace(request)
        if error:
            return error

        brand = (
            Brand.objects.filter(workspace=workspace, status=Brand.Status.ACTIVE)
            .order_by('-is_default', 'created_at')
            .first()
        )
        if brand is None:
            brand = Brand.objects.create(
                workspace=workspace,
                name=workspace.workspace_name or 'My Brand',
                is_default=True,
                created_by=request.user,
            )
            logger.info("Created default brand %s for workspace %s", brand.pk, workspace.pk)

        return APIResponse(success=True, data=BrandSerializer(brand).data)

    @action(
        detail=True,
        methods=['post', 'delete'],
        parser_classes=[MultiPartParser, FormParser],
        url_path='logo',
    )
    def logo(self, request, pk=None):
        """Upload or remove the brand logo."""
        # get_object() goes through the scoped queryset, so a brand in another
        # workspace is a 404 here rather than an authorisation bypass.
        brand = self.get_object()

        if request.method == 'DELETE':
            brand.logo_url = ''
            brand.logo_storage_path = ''
            brand.logo_file_name = ''
            brand.show_logo_on_posters = False
            brand.save(update_fields=[
                'logo_url', 'logo_storage_path', 'logo_file_name',
                'show_logo_on_posters', 'updated_at',
            ])
            return APIResponse(success=True, data=BrandSerializer(brand).data)

        serializer = BrandLogoUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                success=False, error=serializer.errors, status=status.HTTP_400_BAD_REQUEST
            )

        file_obj = serializer.validated_data['file']
        if file_obj.size > MAX_LOGO_BYTES:
            return APIResponse(
                success=False,
                message="Logo must be 2 MB or smaller.",
                error={"code": "FILE_TOO_LARGE", "message": "Logo must be 2 MB or smaller."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # strict=True: a failed upload must not leave the brand pointing at
            # a placeholder URL that serves nothing.
            stored = SupabaseStorageService.upload_and_describe(
                str(brand.workspace_id), file_obj, file_obj.name, prefix='brand-logos'
            )
        except StorageError as exc:
            logger.error("Brand logo upload failed for brand %s: %s", brand.pk, exc)
            return APIResponse(
                success=False,
                message=str(exc),
                error={"code": "STORAGE_UNAVAILABLE", "message": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        brand.logo_url = stored['url']
        brand.logo_storage_path = stored['path']
        brand.logo_file_name = file_obj.name[:255]
        brand.show_logo_on_posters = True
        brand.save(update_fields=[
            'logo_url', 'logo_storage_path', 'logo_file_name',
            'show_logo_on_posters', 'updated_at',
        ])
        logger.info("Logo uploaded for brand %s by user %s", brand.pk, request.user.pk)
        return APIResponse(success=True, data=BrandSerializer(brand).data)
