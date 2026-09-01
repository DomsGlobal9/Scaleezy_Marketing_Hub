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

    #: The fields a person rewrites when they disagree with what was generated.
    CORRECTABLE = ('headline', 'caption', 'cta', 'hashtags')

    def update(self, request, *args, **kwargs):
        item = self.get_object()
        if item.status != ContentItem.Status.DRAFT:
            return APIResponse(
                success=False,
                message="Only a draft can be edited. Open a new revision first.",
                error={"code": "CONTENT_LOCKED", "message": item.get_status_display()},
                status=status.HTTP_409_CONFLICT,
            )

        before = {field: getattr(item, field, '') for field in self.CORRECTABLE}
        response = super().update(request, *args, **kwargs)

        # Somebody rewriting the generated copy is the most precise statement
        # of intent the product ever receives — not "this is wrong" but "this
        # is what it should have said". It used to be written straight over
        # the original with no record that a correction had happened at all.
        item.refresh_from_db()
        changed = {
            field: {'from': before[field], 'to': getattr(item, field, '')}
            for field in self.CORRECTABLE
            if before[field] != getattr(item, field, '')
        }
        if changed:
            self._record_rewrite(item, changed)
        return response

    def _record_rewrite(self, item, changed):
        from apps.learning.models import LearningEvent, SubjectType
        from apps.learning.services import record_event_safely

        # Keep the first generated wording on the item, so the pair
        # (what the machine wrote, what the human wanted) survives the edit.
        config = dict(item.layout_config or {})
        original = config.get('original_generated')
        if original is None:
            config['original_generated'] = {
                field: change['from'] for field, change in changed.items()
            }
            item.layout_config = config
            item.save(update_fields=['layout_config'])

        record_event_safely(
            workspace=item.workspace,
            brand=item.brand,
            event_type=LearningEvent.EventType.EDITED,
            outcome=LearningEvent.Outcome.NEGATIVE,
            subject_type=SubjectType.CONTENT_ITEM,
            subject_id=item.pk,
            context={
                'action': 'DRAFT_REWRITTEN',
                'fields': sorted(changed),
                'changes': {
                    field: {
                        'from': str(change['from'])[:300],
                        'to': str(change['to'])[:300],
                    }
                    for field, change in changed.items()
                },
            },
            created_by=self.request.user,
        )

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
        item = self.get_object()
        if item.status != ContentItem.Status.DRAFT:
            return APIResponse(
                success=False,
                message="Only a draft can be submitted for review.",
                error={"code": "INVALID_CONTENT_TRANSITION", "message": item.get_status_display()},
                status=status.HTTP_409_CONFLICT,
            )
        if item.asset_id is None:
            return APIResponse(
                success=False,
                message="Attach the final media before submitting for review.",
                error={"code": "CONTENT_MEDIA_REQUIRED", "message": "No media asset attached."},
                status=status.HTTP_409_CONFLICT,
            )
        item, error = self._review(
            request, ContentItem.Status.PENDING_REVIEW, require_manager=False
        )
        return error or APIResponse(success=True, data=ContentItemSerializer(item).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        item = self.get_object()
        if item.status != ContentItem.Status.PENDING_REVIEW:
            return APIResponse(
                success=False,
                message="Only content pending review can be approved.",
                error={"code": "INVALID_CONTENT_TRANSITION", "message": item.get_status_display()},
                status=status.HTTP_409_CONFLICT,
            )
        item, error = self._review(request, ContentItem.Status.APPROVED)
        return error or APIResponse(success=True, data=ContentItemSerializer(item).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        item = self.get_object()
        if item.status != ContentItem.Status.PENDING_REVIEW:
            return APIResponse(
                success=False,
                message="Only content pending review can be rejected.",
                error={"code": "INVALID_CONTENT_TRANSITION", "message": item.get_status_display()},
                status=status.HTTP_409_CONFLICT,
            )
        item, error = self._review(request, ContentItem.Status.REJECTED)
        return error or APIResponse(success=True, data=ContentItemSerializer(item).data)

    @action(detail=True, methods=['post'], url_path='request-edits')
    def request_edits(self, request, pk=None):
        """
        Mark as needing edits and open a new version, so the original survives
        as a record of what was rejected and why.
        """
        item = self.get_object()
        if item.status != ContentItem.Status.PENDING_REVIEW:
            return APIResponse(
                success=False,
                message="Only content pending review can be sent back for edits.",
                error={"code": "INVALID_CONTENT_TRANSITION", "message": item.get_status_display()},
                status=status.HTTP_409_CONFLICT,
            )
        item, error = self._review(request, ContentItem.Status.NEEDS_EDITS)
        if error:
            return error

        # The revision inherits the layout and the original photograph's id —
        # without them, re-composing the revision would build from the already
        # composed poster and bake the words on twice. The generation trace is
        # deliberately NOT copied: it describes the parent's generation, and
        # carrying it would double-count rule usage.
        parent_config = item.layout_config if isinstance(item.layout_config, dict) else {}
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
            layout_plugin=item.layout_plugin,
            # source_asset and the studio's saved copy travel to the revision;
            # the generation trace does not — it describes the parent's
            # generation, and carrying it would double-count rule usage.
            layout_config={
                key: parent_config[key]
                for key in ('source_asset', 'copy')
                if parent_config.get(key)
            },
            created_by=request.user,
        )

        # The feedback now drives work instead of waiting for a human: the
        # revision is queued for regeneration with the reviewer's note, tags
        # and fix request as the instruction. Best-effort — if the queue or
        # the spend gate refuses, the revision stays an editable copy.
        queued = self._queue_regeneration(revision)

        return APIResponse(
            success=True,
            data={
                "reviewed": ContentItemSerializer(item).data,
                "revision": ContentItemSerializer(revision).data,
                "regeneration_queued": queued,
            },
        )

    @staticmethod
    def _queue_regeneration(revision):
        try:
            from apps.brands.services.approval import enforce_spend_approved
            from apps.gemini.tasks import regenerate_revision

            # Refused before anything is queued: a pending client must not
            # leave a task behind that spends the moment they are approved.
            enforce_spend_approved(revision.workspace)

            revision.layout_config = {
                **(revision.layout_config or {}), 'regenerating': True,
            }
            revision.save(update_fields=['layout_config', 'updated_at'])
            regenerate_revision.enqueue(str(revision.pk))
            return True
        except Exception:
            logger.info(
                "Revision %s left for manual edits (regeneration not queued)",
                revision.pk,
            )
            config = dict(revision.layout_config or {})
            if config.pop('regenerating', None) is not None:
                revision.layout_config = config
                revision.save(update_fields=['layout_config', 'updated_at'])
            return False
