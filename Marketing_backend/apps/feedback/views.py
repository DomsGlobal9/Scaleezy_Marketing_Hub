import logging

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.content.models import ContentItem
from apps.workspaces.models import WorkspaceMember

from .models import Feedback, FeedbackElement
from .serializers import FeedbackElementSerializer, FeedbackSerializer
from .services import capture
from .training import training_report as build_training_report

logger = logging.getLogger(__name__)


class FeedbackViewSet(
    WorkspaceScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Structured reviewer feedback, and what the training engine made of it.

    Deliberately append-only: feedback is evidence. Editing or deleting it
    after rules have been learned from it would leave the brain citing sources
    that no longer say what it claims.
    """

    queryset = Feedback.objects.select_related('content_item', 'brand', 'user').all()
    serializer_class = FeedbackSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def get_queryset(self):
        qs = super().get_queryset()
        content_item = self.request.query_params.get('content_item')
        if content_item:
            qs = qs.filter(content_item_id=content_item)
        verdict = self.request.query_params.get('verdict')
        if verdict:
            qs = qs.filter(verdict=verdict)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # The content item decides the workspace, and it is re-fetched through
        # the scoped queryset so feedback cannot be attached to another
        # tenant's content by id.
        item = data['content_item']
        if not ContentItem.objects.filter(
            pk=item.pk, workspace_id__in=self.accessible_workspace_ids()
        ).exists():
            return APIResponse(
                success=False,
                message="Content not found.",
                error={"code": "NOT_FOUND", "message": "Content not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        feedback = capture(
            content_item=item,
            user=request.user,
            verdict=data['verdict'],
            element_keys=data.get('element_keys'),
            feedback_text=data.get('feedback_text', ''),
            fix_request=data.get('fix_request', ''),
            urgency=data.get('urgency', Feedback.Urgency.NORMAL),
        )
        if feedback is None:
            return APIResponse(
                success=False,
                message="Could not record feedback.",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return APIResponse(
            success=True,
            data=FeedbackSerializer(feedback).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def elements(self, request):
        """
        The tag vocabulary, grouped for the review card.

        Open to any authenticated user and not workspace-scoped: the
        vocabulary is a global catalogue, the same for every tenant.
        """
        rows = FeedbackElement.objects.filter(is_active=True)
        grouped = {}
        for row in rows:
            bucket = grouped.setdefault(
                row.group, {'group': row.group, 'label': row.get_group_display(), 'elements': []}
            )
            bucket['elements'].append(FeedbackElementSerializer(row).data)

        return APIResponse(
            success=True,
            data={
                'groups': list(grouped.values()),
                'count': rows.count(),
                'provisional': rows.filter(is_provisional=True).exists(),
            },
        )

    @action(detail=False, methods=['get'], url_path='training-report')
    def training_report(self, request):
        """Feedback volume, the elements raised most, and the rules in force."""
        workspace, error = get_request_workspace(request)
        if error:
            return error
        return APIResponse(success=True, data=build_training_report(workspace))
