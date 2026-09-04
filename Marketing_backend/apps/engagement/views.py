from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import HasWorkspaceRole, IsWorkspaceMember, get_request_workspace
from apps.common.responses import APIResponse
from apps.learning.models import LearningEvent, SubjectType
from apps.learning.services import record_event_safely
from apps.workspaces.models import WorkspaceMember

from .models import EngagementItem, EngagementSyncRun, SavedReply
from .serializers import (
    EngagementItemSerializer,
    EngagementSyncRunSerializer,
    SavedReplySerializer,
)
from .services import EngagementError, send_approved_reply


class GovernedWorkspaceViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def workspace(self):
        workspace, error = get_request_workspace(self.request)
        if error:
            return None
        return workspace


class EngagementItemViewSet(GovernedWorkspaceViewSet):
    queryset = EngagementItem.objects.select_related(
        'workspace', 'brand', 'social_connection', 'assigned_to', 'locked_by',
        'approved_by',
    )
    serializer_class = EngagementItemSerializer
    http_method_names = ['get', 'head', 'options', 'post']

    def get_queryset(self):
        queryset = super().get_queryset()
        for parameter, field in (
            ('brand_id', 'brand_id'), ('status', 'status'),
            ('platform', 'platform'), ('assigned_to', 'assigned_to_id'),
        ):
            value = self.request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset

    def create(self, request, *args, **kwargs):
        return APIResponse(
            success=False, message='Inbox items are created only by verified platform sync.',
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=['post'])
    def claim(self, request, pk=None):
        with transaction.atomic():
            # of=('self',): the class queryset select_relates nullable user
            # FKs (assigned_to/locked_by/approved_by), and PostgreSQL refuses
            # FOR UPDATE on the nullable side of an outer join. Only the item
            # row needs the lock.
            item = get_object_or_404(
                self.get_queryset().select_for_update(of=('self',)), pk=pk
            )
            if item.status in (
                EngagementItem.Status.SENDING,
                EngagementItem.Status.RESOLVED,
                EngagementItem.Status.IGNORED,
            ):
                return APIResponse(
                    success=False,
                    message='Sending or closed engagement cannot be claimed.',
                    status=status.HTTP_409_CONFLICT,
                )
            now = timezone.now()
            if (
                item.locked_by_id and item.locked_by_id != request.user.pk
                and item.lock_expires_at and item.lock_expires_at > now
            ):
                return APIResponse(
                    success=False,
                    message=f'{item.locked_by.get_username()} is already working on this item.',
                    status=status.HTTP_409_CONFLICT,
                )
            item.assigned_to = request.user
            item.locked_by = request.user
            item.lock_expires_at = now + timedelta(minutes=15)
            if item.status == EngagementItem.Status.NEW:
                item.status = EngagementItem.Status.IN_PROGRESS
            item.save(update_fields=[
                'assigned_to', 'locked_by', 'lock_expires_at', 'status', 'updated_at'
            ])
        return APIResponse(success=True, data=self.get_serializer(item).data)

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        user_id = request.data.get('user_id')
        member = WorkspaceMember.objects.filter(
            workspace=self.workspace(), user_id=user_id, status=WorkspaceMember.Status.ACTIVE
        ).select_related('user').first()
        if member is None:
            return APIResponse(
                success=False, error={'user_id': 'Choose an active workspace member.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        item = self.get_object()
        item.assigned_to = member.user
        item.save(update_fields=['assigned_to', 'updated_at'])
        return APIResponse(success=True, data=self.get_serializer(item).data)

    @action(detail=True, methods=['post'])
    def release(self, request, pk=None):
        item = self.get_object()
        membership = getattr(request, 'workspace_membership', None)
        if item.locked_by_id not in (None, request.user.pk) and (
            membership is None or membership.role != WorkspaceMember.Role.ADMIN
        ):
            return APIResponse(
                success=False, message='Only the lock owner or an admin can release it.',
                status=status.HTTP_403_FORBIDDEN,
            )
        item.locked_by = None
        item.lock_expires_at = None
        item.save(update_fields=['locked_by', 'lock_expires_at', 'updated_at'])
        return APIResponse(success=True, data=self.get_serializer(item).data)

    @action(detail=True, methods=['post'], url_path='draft-reply')
    def draft_reply(self, request, pk=None):
        from .tasks import draft_engagement_reply_task

        item = self.get_object()
        if item.status in (EngagementItem.Status.RESOLVED, EngagementItem.Status.IGNORED):
            return APIResponse(
                success=False, message='Closed engagement cannot receive a draft.',
                status=status.HTTP_409_CONFLICT,
            )
        if item.draft_status in (
            EngagementItem.DraftStatus.QUEUED, EngagementItem.DraftStatus.PROCESSING
        ):
            return APIResponse(
                success=True, data=self.get_serializer(item).data,
                status=status.HTTP_202_ACCEPTED,
            )
        item.draft_status = EngagementItem.DraftStatus.QUEUED
        item.last_error = ''
        task_result = draft_engagement_reply_task.enqueue(str(item.pk))
        item.draft_task_id = str(task_result.id)
        item.save(update_fields=['draft_status', 'draft_task_id', 'last_error', 'updated_at'])
        return APIResponse(
            success=True, message='Reply draft queued.', data=self.get_serializer(item).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        with transaction.atomic():
            # of=('self',) for the same nullable-join reason as claim above.
            item = get_object_or_404(
                self.get_queryset().select_for_update(of=('self',)), pk=pk
            )
            response_text = str(
                request.data.get('response') or item.ai_draft or ''
            ).strip()[:5000]
            if not response_text:
                return APIResponse(
                    success=False, error={'response': 'A response is required.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if item.status in (
                EngagementItem.Status.SENDING,
                EngagementItem.Status.RESOLVED,
                EngagementItem.Status.IGNORED,
            ):
                return APIResponse(
                    success=False,
                    message='Sending or closed engagement cannot be approved.',
                    status=status.HTTP_409_CONFLICT,
                )
            item.approved_response = response_text
            item.approved_by = request.user
            item.approved_at = timezone.now()
            item.status = EngagementItem.Status.APPROVED
            item.last_error = ''
            item.save(update_fields=[
                'approved_response', 'approved_by', 'approved_at', 'status',
                'last_error', 'updated_at',
            ])
        record_event_safely(
            workspace=item.workspace,
            brand=item.brand,
            event_type=LearningEvent.EventType.APPROVED,
            outcome=LearningEvent.Outcome.POSITIVE,
            subject_type=SubjectType.OTHER,
            subject_id=item.pk,
            context={
                'kind': 'ENGAGEMENT_RESPONSE', 'platform': item.platform,
                'provider': item.ai_provider_key, 'risk_flags': item.ai_risk_flags,
            },
            dedupe_key=f'engagement-response-approved:{item.pk}',
            created_by=request.user,
        )
        return APIResponse(success=True, data=self.get_serializer(item).data)

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        now = timezone.now()
        claimed = EngagementItem.objects.filter(
            pk=pk, workspace=self.workspace(), status=EngagementItem.Status.APPROVED
        ).update(
            status=EngagementItem.Status.SENDING,
            last_error='',
            updated_at=now,
        )
        if not claimed:
            return APIResponse(
                success=False, message='This response is not approved or is already sending.',
                status=status.HTTP_409_CONFLICT,
            )
        item = self.get_queryset().get(pk=pk)
        try:
            result = send_approved_reply(item)
        except EngagementError as exc:
            EngagementItem.objects.filter(pk=item.pk, status=EngagementItem.Status.SENDING).update(
                status=EngagementItem.Status.APPROVED,
                last_error=str(exc)[:1000],
                updated_at=timezone.now(),
            )
            return APIResponse(
                success=False, message=str(exc), status=status.HTTP_409_CONFLICT
            )
        except Exception:
            EngagementItem.objects.filter(pk=item.pk, status=EngagementItem.Status.SENDING).update(
                status=EngagementItem.Status.APPROVED,
                last_error='The platform rejected the reply. Review the connection and try again.',
                updated_at=timezone.now(),
            )
            return APIResponse(
                success=False,
                message='The platform rejected the reply. Nothing was marked sent.',
                status=status.HTTP_502_BAD_GATEWAY,
            )
        EngagementItem.objects.filter(pk=item.pk, status=EngagementItem.Status.SENDING).update(
            status=EngagementItem.Status.RESOLVED,
            external_response_id=str(result.get('id') or '')[:255],
            responded_at=timezone.now(),
            locked_by=None,
            lock_expires_at=None,
            last_error='',
            updated_at=timezone.now(),
        )
        item.refresh_from_db()
        return APIResponse(success=True, message='Response sent.', data=self.get_serializer(item).data)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        item = self.get_object()
        if item.status == EngagementItem.Status.SENDING:
            return APIResponse(
                success=False, message='Wait for the active send to finish.',
                status=status.HTTP_409_CONFLICT,
            )
        item.status = EngagementItem.Status.RESOLVED
        item.locked_by = None
        item.lock_expires_at = None
        item.save(update_fields=['status', 'locked_by', 'lock_expires_at', 'updated_at'])
        return APIResponse(success=True, data=self.get_serializer(item).data)

    @action(detail=True, methods=['post'])
    def ignore(self, request, pk=None):
        item = self.get_object()
        if item.status == EngagementItem.Status.SENDING:
            return APIResponse(success=False, message='Wait for the active send to finish.', status=409)
        item.status = EngagementItem.Status.IGNORED
        item.locked_by = None
        item.lock_expires_at = None
        item.save(update_fields=['status', 'locked_by', 'lock_expires_at', 'updated_at'])
        return APIResponse(success=True, data=self.get_serializer(item).data)


class EngagementSyncRunViewSet(GovernedWorkspaceViewSet):
    queryset = EngagementSyncRun.objects.select_related('workspace', 'brand', 'social_connection')
    serializer_class = EngagementSyncRunSerializer
    http_method_names = ['get', 'head', 'options', 'post']

    def get_queryset(self):
        queryset = super().get_queryset()
        brand_id = self.request.query_params.get('brand_id')
        return queryset.filter(brand_id=brand_id) if brand_id else queryset

    def perform_create(self, serializer):
        from .tasks import sync_engagement_task

        run = serializer.save(workspace=self.workspace(), initiated_by=self.request.user)
        try:
            task_result = sync_engagement_task.enqueue(str(run.pk))
        except Exception:
            run.status = EngagementSyncRun.Status.FAILED
            run.error = 'Inbox sync could not be queued. Please try again.'
            run.completed_at = timezone.now()
            run.save(update_fields=['status', 'error', 'completed_at', 'updated_at'])
            error = APIException(run.error)
            error.status_code = 503
            raise error from None
        run.task_id = str(task_result.id)
        run.save(update_fields=['task_id', 'updated_at'])

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def retry(self, request, pk=None):
        from .tasks import sync_engagement_task

        run = self.get_object()
        run = EngagementSyncRun.objects.select_for_update().get(pk=run.pk)
        if not EngagementSyncRunSerializer.get_execution(run)['retry_allowed']:
            return APIResponse(success=False, message='Wait for the owned sync task to finish before retrying.', status=409)
        run.status = EngagementSyncRun.Status.QUEUED
        run.error = ''
        run.completed_at = None
        # Persist the queued transition before publishing work to the runner.
        # The final task-id save must not overwrite a fast worker's state.
        run.save(update_fields=['status', 'error', 'completed_at', 'updated_at'])
        try:
            result = sync_engagement_task.enqueue(str(run.pk))
        except Exception:
            run.status = EngagementSyncRun.Status.FAILED
            run.error = 'Inbox sync could not be queued. Please try again.'
            run.completed_at = timezone.now()
            run.save(update_fields=['status', 'error', 'completed_at', 'updated_at'])
            return APIResponse(success=False, message=run.error, status=503)
        run.task_id = str(result.id)
        run.save(update_fields=['task_id', 'updated_at'])
        run.refresh_from_db()
        return APIResponse(success=True, data=self.get_serializer(run).data, status=202)


class SavedReplyViewSet(GovernedWorkspaceViewSet):
    queryset = SavedReply.objects.all()
    serializer_class = SavedReplySerializer

    def perform_create(self, serializer):
        serializer.save(workspace=self.workspace(), created_by=self.request.user)
