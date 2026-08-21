"""
Onboarding APIs.

Thin over the services: the orchestration state, the calibration round, the
verdicts, the skip. Everything else the onboarding screen shows comes from
the endpoints the other layers already own.
"""
import logging

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.brands.models import Brand
from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.context.services.generation import NoProviderConfigured
from apps.workspaces.models import WorkspaceMember

from .models import CalibrationDirection
from .services import (
    CalibrationError,
    ensure_onboarding,
    generate_calibration_round,
    onboarding_summary,
    record_calibration_verdict,
    refresh_stage,
    skip_stage,
)

logger = logging.getLogger(__name__)


class OnboardingViewSet(
    WorkspaceScopedMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Keyed by brand id: onboarding is a property of a brand, not a thing of
    its own the client has to track ids for."""

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
        """State + readiness + latest calibration round, resumable any time."""
        return APIResponse(success=True, data=onboarding_summary(self.get_object()))

    @action(detail=True, methods=['post'])
    def skip(self, request, pk=None):
        brand = self.get_object()
        try:
            onboarding = skip_stage(
                refresh_stage(ensure_onboarding(brand)),
                request.data.get('stage', ''),
            )
        except CalibrationError as exc:
            return APIResponse(
                success=False, message=str(exc),
                status=status.HTTP_400_BAD_REQUEST,
            )
        return APIResponse(success=True, data=onboarding_summary(brand))

    @action(detail=True, methods=['post'])
    def calibrate(self, request, pk=None):
        """Generate the three directions through the real generation chain."""
        brand = self.get_object()
        try:
            directions = generate_calibration_round(
                self._workspace(), brand, user=request.user
            )
        except NoProviderConfigured as exc:
            return APIResponse(
                success=False,
                message="No AI provider is routed for generation yet.",
                error={'code': 'NO_PROVIDER', 'message': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return APIResponse(success=True, data={
            'round_id': str(directions[0].round_id),
            'directions': [
                {
                    'id': str(d.pk),
                    'label': d.label,
                    'tests_dimension': d.tests_dimension,
                    'headline': d.headline,
                    'caption': d.caption,
                    'preview_url': d.preview_url,
                    'verdict': d.verdict,
                }
                for d in directions
            ],
        }, status=status.HTTP_201_CREATED)


class CalibrationDirectionViewSet(
    WorkspaceScopedMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = CalibrationDirection.objects.all()
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    @action(detail=True, methods=['post'])
    def react(self, request, pk=None):
        """Like / Not us / Adjust. Idempotent: a second click is a no-op."""
        direction = self.get_object()
        verdict = {
            'like': CalibrationDirection.Verdict.LIKED,
            'not_us': CalibrationDirection.Verdict.NOT_US,
            'adjust': CalibrationDirection.Verdict.ADJUSTED,
        }.get(str(request.data.get('reaction', '')).lower())
        if verdict is None:
            return APIResponse(
                success=False,
                message="reaction must be one of: like, not_us, adjust.",
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            direction, learned = record_calibration_verdict(
                direction, verdict,
                user=request.user, note=str(request.data.get('note', '')),
            )
        except CalibrationError as exc:
            return APIResponse(
                success=False, message=str(exc), status=status.HTTP_400_BAD_REQUEST
            )
        return APIResponse(success=True, data={
            'id': str(direction.pk),
            'verdict': direction.verdict,
            'learned': learned,
            'summary': onboarding_summary(direction.brand),
        })
