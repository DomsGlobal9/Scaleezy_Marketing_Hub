import logging

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.workspaces.models import WorkspaceMember

from .models import ContentItem
from .serializers import ContentItemSerializer, ReviewActionSerializer

logger = logging.getLogger(__name__)


class ContentItemViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    """
    Generated content and its review workflow.

    Approving is a MANAGER decision — it is the gate that lets something reach
    a real audience — while EDITORs can create and edit drafts.
    """

    queryset = ContentItem.objects.select_related('brand', 'asset').all()
    serializer_class = ContentItemSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def get_queryset(self):
        qs = super().get_queryset()
        wanted = self.request.query_params.get('status')
        return qs.filter(status=wanted) if wanted else qs

    def perform_create(self, serializer):
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        serializer.save(workspace=workspace, created_by=self.request.user)

    # ── review workflow ──────────────────────────────────────────────────
    def _review(self, request, new_status, require_manager=True):
        item = self.get_object()

        membership = getattr(request, 'workspace_membership', None)
        if require_manager and (
            membership is None or not membership.has_at_least(WorkspaceMember.Role.MANAGER)
        ):
            return None, APIResponse(
                success=False,
                message="Only a marketing manager can approve or reject content.",
                error={"code": "FORBIDDEN", "message": "Manager role required."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if item.status == ContentItem.Status.PUBLISHED:
            return None, APIResponse(
                success=False,
                message="Published content cannot be re-reviewed.",
                status=status.HTTP_409_CONFLICT,
            )

        payload_serializer = ReviewActionSerializer(data=request.data)
        payload_serializer.is_valid(raise_exception=True)
        payload = payload_serializer.validated_data
        note = payload.get('note', '')

        item.status = new_status
        item.review_note = note
        item.reviewed_by = request.user
        item.reviewed_at = timezone.now()
        item.save(
            update_fields=['status', 'review_note', 'reviewed_by', 'reviewed_at', 'updated_at']
        )
        logger.info("Content %s -> %s by user %s", item.pk, new_status, request.user.pk)
        self._capture_feedback(request, item, new_status, payload)
        return item, None

    @staticmethod
    def _capture_feedback(request, item, new_status, payload):
        """
        Records the verdict for the training engine.

        Submitting for review is not a verdict, so it is skipped. Everything
        else is best-effort inside `capture()` — a training failure must not
        cost the reviewer their decision.
        """
        from apps.feedback.services import VERDICT_FOR_STATUS, capture

        verdict = VERDICT_FOR_STATUS.get(new_status)
        if verdict is None:
            return

        capture(
            content_item=item,
            user=request.user,
            verdict=verdict,
            element_keys=payload.get('elements'),
            feedback_text=payload.get('note', ''),
            fix_request=payload.get('fix_request', ''),
            urgency=payload.get('urgency', 'NORMAL'),
        )

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """Move a draft into the review queue. Any editor may do this."""
        item, error = self._review(
            request, ContentItem.Status.PENDING_REVIEW, require_manager=False
        )
        return error or APIResponse(success=True, data=ContentItemSerializer(item).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        item, error = self._review(request, ContentItem.Status.APPROVED)
        return error or APIResponse(success=True, data=ContentItemSerializer(item).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        item, error = self._review(request, ContentItem.Status.REJECTED)
        return error or APIResponse(success=True, data=ContentItemSerializer(item).data)

    @action(detail=True, methods=['post'], url_path='request-edits')
    def request_edits(self, request, pk=None):
        """
        Mark as needing edits and open a new version, so the original survives
        as a record of what was rejected and why.
        """
        item, error = self._review(request, ContentItem.Status.NEEDS_EDITS)
        if error:
            return error

        revision = ContentItem.objects.create(
            workspace=item.workspace,
            brand=item.brand,
            asset=item.asset,
            content_format=item.content_format,
            status=ContentItem.Status.DRAFT,
            version=item.version + 1,
            parent=item,
            headline=item.headline,
            caption=item.caption,
            cta=item.cta,
            hashtags=item.hashtags,
            preview_url=item.preview_url,
            slides=item.slides,
            created_by=request.user,
        )
        return APIResponse(
            success=True,
            data={
                "reviewed": ContentItemSerializer(item).data,
                "revision": ContentItemSerializer(revision).data,
            },
        )
