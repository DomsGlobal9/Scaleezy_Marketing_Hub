import hashlib
import json
import logging
import mimetypes

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils import timezone

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
from apps.learning.models import LearningEvent, SubjectType
from apps.learning.services import record_event_safely

from .models import BrandSource, BrandMemory
from .serializers import BrandSourceSerializer, BrandMemorySerializer, BrandSourceUploadSerializer

logger = logging.getLogger(__name__)


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
            
        if source.status in (
            BrandSource.SourceStatus.QUEUED,
            BrandSource.SourceStatus.PROCESSING,
        ):
            return APIResponse(
                success=True,
                message="Source processing is already in progress.",
                data=BrandSourceSerializer(source).data,
                status=status.HTTP_202_ACCEPTED,
            )

        from .tasks import process_source_task

        source.status = BrandSource.SourceStatus.QUEUED
        metadata = dict(source.metadata or {})
        metadata['processing'] = {
            **dict(metadata.get('processing') or {}),
            'queued_at': timezone.now().isoformat(),
            'queued_by': str(request.user.pk),
            'error': '',
        }
        source.metadata = metadata
        source.save(update_fields=['status', 'metadata', 'updated_at'])
        try:
            task_result = process_source_task.enqueue(str(source.pk))
        except Exception:
            failure_message = "Source processing could not enter the task queue. Try again."
            logger.exception(
                "Knowledge source could not enter the durable task queue.",
                extra={
                    'knowledge_source_id': str(source.pk),
                    'workspace_id': str(source.workspace_id),
                },
            )
            failed_at = timezone.now()
            metadata = dict(source.metadata or {})
            metadata['processing'] = {
                **dict(metadata.get('processing') or {}),
                'failed_at': failed_at.isoformat(),
                'error': failure_message,
            }
            BrandSource.objects.filter(
                pk=source.pk,
                status=BrandSource.SourceStatus.QUEUED,
            ).update(
                status=BrandSource.SourceStatus.FAILED,
                metadata=metadata,
                updated_at=failed_at,
            )
            source.refresh_from_db()
            return APIResponse(
                success=False,
                message=failure_message,
                error={
                    'code': 'QUEUE_ENQUEUE_FAILED',
                    'message': failure_message,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return APIResponse(
            success=True,
            message="Source queued for processing.",
            data={'source': BrandSourceSerializer(source).data, 'task_id': str(task_result.id)},
            status=status.HTTP_202_ACCEPTED,
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

    def _record_verdict(self, memory, *, event_type, outcome):
        """A person ruling on a candidate fact is evidence in its own right.

        Until now confirm and reject moved a status and nothing else: the
        ledger never heard that somebody had decided, and the row never said
        who. Both event types were already declared and already counted as
        judgment by universal learning — nothing was emitting them.
        """
        record_event_safely(
            workspace=memory.workspace,
            brand=memory.brand,
            event_type=event_type,
            outcome=outcome,
            subject_type=SubjectType.BRAND_MEMORY,
            subject_id=memory.pk,
            source_type=SubjectType.BRAND_SOURCE if memory.source_id else '',
            source_id=memory.source_id,
            context={
                'memory_type': memory.memory_type,
                'normalized_key': memory.normalized_key,
                'content': (memory.content or '')[:500],
            },
            dedupe_key=(
                f'memory-verdict:{memory.pk}:{memory.status}:'
                + hashlib.sha256(json.dumps({
                    field: str(getattr(memory, field, ''))
                    for field in self.REVIEWED_FIELDS
                }, sort_keys=True).encode()).hexdigest()[:24]
            ),
            created_by=self.request.user,
        )

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        memory = self.get_object()
        now = timezone.now()
        if (
            memory.status in (BrandMemory.MemoryStatus.SUPERSEDED, BrandMemory.MemoryStatus.EXPIRED)
            or (memory.source_id and memory.source.status == BrandSource.SourceStatus.ARCHIVED)
            or (memory.valid_until and memory.valid_until <= now)
            or (memory.valid_from and memory.valid_from > now)
        ):
            raise ValidationError("This evidence is not current. Add a new fact or restore its source through the owning workflow.")
        memory.status = BrandMemory.MemoryStatus.CONFIRMED
        memory.reviewed_by = request.user
        memory.reviewed_at = timezone.now()
        memory.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
        self._record_verdict(
            memory,
            event_type=LearningEvent.EventType.MEMORY_CONFIRMED,
            outcome=LearningEvent.Outcome.POSITIVE,
        )
        # A confirmed fact is intelligence; the snapshot must carry it.
        rebuild_brand_brain_safely(memory.brand)
        self._finish_source_review(memory)
        return APIResponse(success=True, message="Memory confirmed")

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        memory = self.get_object()
        memory.status = BrandMemory.MemoryStatus.REJECTED
        memory.reviewed_by = request.user
        memory.reviewed_at = timezone.now()
        memory.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
        self._record_verdict(
            memory,
            event_type=LearningEvent.EventType.MEMORY_REJECTED,
            outcome=LearningEvent.Outcome.NEGATIVE,
        )
        rebuild_brand_brain_safely(memory.brand)
        self._finish_source_review(memory)
        return APIResponse(success=True, message="Memory rejected")

    def destroy(self, request, *args, **kwargs):
        """A fact somebody confirmed is provenance, not a scratch row.

        Every other record that carries a verdict in this codebase refuses
        hard deletion; this one was a plain ModelViewSet and did not.
        """
        return APIResponse(
            success=False,
            message="Facts are not deleted. Reject it instead, which keeps the record.",
            error={'code': 'DELETE_DISABLED', 'message': 'Use reject.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    REVIEWED_FIELDS = ('content', 'memory_type', 'scope', 'valid_from', 'valid_until')

    def perform_update(self, serializer):
        """Editing what a confirmed fact SAYS withdraws the confirmation.

        Otherwise the text a person approved can be replaced afterwards while
        the CONFIRMED stamp — and its place in the Brand Brain — carries over
        to words nobody ever agreed to.
        """
        before = serializer.instance
        was_confirmed = before.status == BrandMemory.MemoryStatus.CONFIRMED
        old_values = {field: getattr(before, field) for field in self.REVIEWED_FIELDS}
        memory = serializer.save()
        if was_confirmed and any(getattr(memory, field) != value for field, value in old_values.items()):
            memory.status = BrandMemory.MemoryStatus.CANDIDATE
            memory.reviewed_by = None
            memory.reviewed_at = None
            memory.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
            rebuild_brand_brain_safely(memory.brand)

    @staticmethod
    def _finish_source_review(memory):
        if not memory.source_id:
            return
        waiting = BrandMemory.objects.filter(
            source_id=memory.source_id,
            status=BrandMemory.MemoryStatus.CANDIDATE,
        ).exists()
        if not waiting:
            BrandSource.objects.filter(
                pk=memory.source_id,
                status=BrandSource.SourceStatus.NEEDS_REVIEW,
            ).update(status=BrandSource.SourceStatus.READY)
