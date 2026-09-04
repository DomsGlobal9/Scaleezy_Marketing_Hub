"""
Brand Master and Context Gateway APIs.

Brand Master is a read surface over intelligence that already exists: it
aggregates rather than duplicating, so the Knowledge, Inspirations, Learning
and Rules tabs go on reading the endpoints their own PRs already shipped. Only
what nothing else answers lives here — readiness, the overview roll-up, and a
look at the context a generation would actually receive.
"""
import logging

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.brands.models import Brand
from apps.brands.serializers import BrandSerializer
from apps.brands.services.brand_brain import compile_brand_brain, rebuild_brand_brain
from apps.brands.services.current_brand import get_current_brand
from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.workspaces.models import WorkspaceMember

from .services.context_gateway import (
    ContextError,
    TaskType,
    build_generation_context,
    resolved_brain,
)
from .services.generation import NoProviderConfigured, generate_with_context
from .services.readiness import brand_readiness

logger = logging.getLogger(__name__)


def build_brand_master_overview(brand):
    """Build the stable overview payload used by both Brand Master reads."""
    brain = resolved_brain(brand)
    readiness = brand_readiness(brand, brain=brain)

    return {
        'brand': {
            'id': str(brand.pk),
            'name': brand.name,
            'industry': brand.industry,
            'tagline': brand.tagline,
            'brand_tone': brand.brand_tone,
            'logo_url': brand.logo_url,
            'palette': brand.palette or {},
            'status': brand.status,
        },
        'readiness': readiness,
        'brain': {
            'compiled': bool(brand.creative_brain),
            'needs_refresh': bool(brand.brain_last_error) or not bool(brand.creative_brain),
            'brain_version': brain.get('brain_version', ''),
            'schema_version': brain.get('schema_version'),
            'compiled_at': (brand.creative_brain or {}).get('compiled_at'),
            'positioning': brain.get('positioning', {}),
            'unresolved_conflict_count': brain.get('unresolved_conflict_count', 0),
        },
        'conflicts': brain.get('conflicts', []),
    }


class BrandMasterViewSet(
    WorkspaceScopedMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Everything the Brand Master screen needs, scoped to one brand."""

    queryset = Brand.objects.all()
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def _workspace(self):
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        return workspace

    def retrieve(self, request, pk=None):
        """The overview: how well Scaleezy understands this brand."""
        return APIResponse(success=True, data=build_brand_master_overview(self.get_object()))

    @action(detail=False, methods=['get'])
    def current(self, request):
        """One selected-workspace bootstrap for the complete Brand Master."""
        workspace, error = get_request_workspace(request)
        if error:
            return error
        brand = get_current_brand(workspace, request.user)
        return APIResponse(success=True, data={
            'brand': BrandSerializer(brand).data,
            'overview': build_brand_master_overview(brand),
        })

    @action(detail=True, methods=['get'])
    def readiness(self, request, pk=None):
        return APIResponse(success=True, data=brand_readiness(self.get_object()))

    @action(detail=True, methods=['get'])
    def context(self, request, pk=None):
        """What a generation for this task would actually be told.

        A preview of the gateway output, so "why did it write that?" has an
        answer that is not a guess.
        """
        brand = self.get_object()
        task = (request.query_params.get('task') or TaskType.COPY).upper()
        try:
            context = build_generation_context(
                self._workspace(), brand, task,
                instruction=request.query_params.get('instruction', ''),
                channel=request.query_params.get('channel', ''),
            )
        except ContextError as exc:
            return APIResponse(
                success=False, message=str(exc),
                error={'code': 'CONTEXT_UNAVAILABLE', 'message': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return APIResponse(success=True, data=context)

    @action(detail=True, methods=['post'], url_path='preview-generation')
    def preview_generation(self, request, pk=None):
        """Run one real generation through the whole chain.

        Gateway to router to provider. A workspace with no provider routed is
        told so; it does not get an empty success.
        """
        brand = self.get_object()
        task = (request.data.get('task') or TaskType.COPY).upper()
        try:
            outcome = generate_with_context(
                self._workspace(), brand, task,
                instruction=request.data.get('instruction', ''),
            )
        except ContextError as exc:
            return APIResponse(
                success=False, message=str(exc),
                error={'code': 'CONTEXT_UNAVAILABLE', 'message': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except NoProviderConfigured as exc:
            return APIResponse(
                success=False,
                message="No AI provider is routed to this capability yet.",
                error={'code': 'NO_PROVIDER', 'message': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return APIResponse(success=True, data=outcome)

    @action(detail=True, methods=['post'], url_path='rebuild-brain')
    def rebuild_brain(self, request, pk=None):
        """Delegates to PR4 so there is one compiler and one protected path."""
        brain = rebuild_brand_brain(self.get_object())
        return APIResponse(success=True, message="Brand Brain recompiled.", data={
            'brain_version': brain['brain_version'],
            'compiled_at': brain['compiled_at'],
            'unresolved_conflict_count': brain['unresolved_conflict_count'],
        })

    @action(detail=True, methods=['get'])
    def brain(self, request, pk=None):
        brand = self.get_object()
        return APIResponse(
            success=True, data=brand.creative_brain or compile_brand_brain(brand)
        )
