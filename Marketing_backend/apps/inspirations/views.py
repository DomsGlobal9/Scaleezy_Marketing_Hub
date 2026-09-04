"""
Inspiration APIs.

Follows the shape established by `apps.knowledge`: workspace-scoped queryset,
role-gated writes, lifecycle changes through named actions rather than PATCH,
and no hard delete on anything that carries provenance.
"""
import logging

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.brands.services.brand_brain import rebuild_brand_brain_safely
from apps.marketing.services.storage import StorageError, SupabaseStorageService
from apps.workspaces.models import WorkspaceMember

from .models import BrandInspiration, InspirationSignal, ResearchFinding, ResearchRun
from .serializers import (
    BrandInspirationSerializer,
    BrandInspirationUploadSerializer,
    InspirationSignalSerializer,
    ResearchFindingSerializer,
    ResearchRunSerializer,
)
from .research import ResearchError, adopt_finding
from .services import (
    InspirationSignalError,
    confirm_signal,
    record_user_signal,
    reject_signal,
)


logger = logging.getLogger(__name__)

INSPIRATION_QUEUE_FAILURE = (
    'Inspiration analysis could not enter the task queue. Try again.'
)
RESEARCH_QUEUE_FAILURE = 'Research could not enter the task queue. Try again.'


class ResearchQueueUnavailable(Exception):
    """Carries the persisted failed run back through DRF's create flow."""

    def __init__(self, run):
        self.run = run
        super().__init__(RESEARCH_QUEUE_FAILURE)


class WorkspaceResolvedViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def _authorised_workspace(self):
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        return workspace


class BrandInspirationViewSet(WorkspaceScopedMixin, WorkspaceResolvedViewSet):
    queryset = BrandInspiration.objects.all()
    serializer_class = BrandInspirationSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        brand_id = self.request.query_params.get('brand_id')
        if brand_id:
            queryset = queryset.filter(brand_id=brand_id)
        # Lets a caller ask for exactly what a future retrieval step would see,
        # instead of reimplementing the eligibility rule client-side.
        if self.request.query_params.get('eligible_only') == 'true':
            queryset = queryset.eligible_for_retrieval()
        return queryset

    def perform_create(self, serializer):
        serializer.save(
            workspace=self._authorised_workspace(), created_by=self.request.user
        )

    def perform_update(self, serializer):
        inspiration = serializer.save()
        # Scope/focus and user annotations are editable direction, not source
        # identity. Recompile immediately so the snapshot respects the change.
        rebuild_brand_brain_safely(inspiration.brand)

    def destroy(self, request, *args, **kwargs):
        return APIResponse(
            success=False,
            message="Hard deletion is disabled. Use the archive action instead.",
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        inspiration = self.get_object()
        if inspiration.lifecycle_status == BrandInspiration.LifecycleStatus.ARCHIVED:
            return APIResponse(
                success=False,
                message="Inspiration is already archived.",
                status=status.HTTP_400_BAD_REQUEST,
            )
        inspiration.lifecycle_status = BrandInspiration.LifecycleStatus.ARCHIVED
        inspiration.archived_by = request.user
        inspiration.archived_at = timezone.now()
        inspiration.save(update_fields=['lifecycle_status', 'archived_by', 'archived_at'])
        # Its signals left the eligible set; the snapshot must stop citing them.
        rebuild_brand_brain_safely(inspiration.brand)
        return APIResponse(
            success=True,
            message="Inspiration archived. It is no longer eligible for retrieval.",
            data=BrandInspirationSerializer(
                inspiration, context=self.get_serializer_context()
            ).data,
        )

    @action(detail=True, methods=['post'])
    def analyze(self, request, pk=None):
        inspiration = self.get_object()
        if inspiration.lifecycle_status == BrandInspiration.LifecycleStatus.ARCHIVED:
            return APIResponse(
                success=False,
                message="Archived inspirations cannot be analysed.",
                status=status.HTTP_400_BAD_REQUEST,
            )
        if inspiration.analysis_status in (
            BrandInspiration.AnalysisStatus.QUEUED,
            BrandInspiration.AnalysisStatus.PROCESSING,
        ):
            return APIResponse(
                success=True,
                message="Inspiration analysis is already in progress.",
                data=BrandInspirationSerializer(
                    inspiration, context=self.get_serializer_context()
                ).data,
                status=status.HTTP_202_ACCEPTED,
            )

        from .tasks import analyze_inspiration_task

        inspiration.analysis_status = BrandInspiration.AnalysisStatus.QUEUED
        metadata = dict(inspiration.metadata or {})
        metadata['analysis'] = {
            **dict(metadata.get('analysis') or {}),
            'queued_at': timezone.now().isoformat(),
            'queued_by': str(request.user.pk),
            'error': '',
        }
        inspiration.metadata = metadata
        inspiration.save(update_fields=['analysis_status', 'metadata', 'updated_at'])
        try:
            task_result = analyze_inspiration_task.enqueue(str(inspiration.pk))
        except Exception:
            logger.exception(
                'Inspiration analysis could not enter the durable task queue.',
                extra={
                    'inspiration_id': str(inspiration.pk),
                    'workspace_id': str(inspiration.workspace_id),
                },
            )
            failed_at = timezone.now()
            metadata = dict(inspiration.metadata or {})
            metadata['analysis'] = {
                **dict(metadata.get('analysis') or {}),
                'failed_at': failed_at.isoformat(),
                'error': INSPIRATION_QUEUE_FAILURE,
            }
            BrandInspiration.objects.filter(
                pk=inspiration.pk,
                analysis_status=BrandInspiration.AnalysisStatus.QUEUED,
            ).update(
                analysis_status=BrandInspiration.AnalysisStatus.FAILED,
                metadata=metadata,
                updated_at=failed_at,
            )
            inspiration.refresh_from_db()
            return APIResponse(
                success=False,
                message=INSPIRATION_QUEUE_FAILURE,
                error={
                    'code': 'QUEUE_ENQUEUE_FAILED',
                    'message': INSPIRATION_QUEUE_FAILURE,
                },
                data={
                    'inspiration': BrandInspirationSerializer(
                        inspiration, context=self.get_serializer_context()
                    ).data,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return APIResponse(
            success=True,
            message="Inspiration queued for analysis.",
            data={
                'inspiration': BrandInspirationSerializer(
                    inspiration, context=self.get_serializer_context()
                ).data,
                'task_id': str(task_result.id),
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(
        detail=False,
        methods=['post'],
        parser_classes=[MultiPartParser, FormParser],
        url_path='upload',
    )
    def upload(self, request):
        """Multipart entry path for image/screenshot references.

        Deliberately runs the same relation validation as the JSON path before
        anything reaches storage (PR1-007).
        """
        workspace = self._authorised_workspace()
        serializer = BrandInspirationUploadSerializer(
            data=request.data, context={'request': request}
        )
        if not serializer.is_valid():
            return APIResponse(
                success=False, error=serializer.errors, status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data
        file_obj = data['file']
        mime_type = file_obj.content_type

        try:
            stored = SupabaseStorageService.upload_and_describe(
                str(workspace.id), file_obj, file_obj.name, prefix='inspirations'
            )
        except StorageError as exc:
            # No row is written: a reference with no reachable file would be a
            # dead record that later analysis cannot explain.
            return APIResponse(
                success=False, message=str(exc), status=status.HTTP_502_BAD_GATEWAY
            )

        inspiration = BrandInspiration.objects.create(
            workspace=workspace,
            brand=data['brand'],
            source=data.get('source'),
            inspiration_type=data.get(
                'inspiration_type', BrandInspiration.InspirationType.IMAGE
            ),
            title=data.get('title') or file_obj.name,
            annotation=data.get('annotation', ''),
            external_platform=data.get('external_platform', ''),
            usage_scope=data.get('usage_scope', BrandInspiration.UsageScope.FULL_REFERENCE),
            focus_areas=data.get('focus_areas') or [],
            file_url=stored['url'],
            storage_path=stored['path'],
            mime_type=mime_type,
            file_name=file_obj.name,
            created_by=request.user,
        )
        return APIResponse(
            success=True,
            data=BrandInspirationSerializer(
                inspiration, context=self.get_serializer_context()
            ).data,
            status=status.HTTP_201_CREATED,
        )


class InspirationSignalViewSet(WorkspaceScopedMixin, WorkspaceResolvedViewSet):
    queryset = InspirationSignal.objects.all()
    serializer_class = InspirationSignalSerializer
    # Signals hold no workspace column; tenancy is read through the parent.
    workspace_field = 'inspiration__workspace'

    def get_queryset(self):
        queryset = super().get_queryset()
        inspiration_id = self.request.query_params.get('inspiration_id')
        if inspiration_id:
            queryset = queryset.filter(inspiration_id=inspiration_id)
        brand_id = self.request.query_params.get('brand_id')
        if brand_id:
            queryset = queryset.filter(inspiration__brand_id=brand_id)
        if self.request.query_params.get('eligible_only') == 'true':
            queryset = queryset.eligible_for_retrieval()
        return queryset

    def perform_create(self, serializer):
        # Origin is decided in the service, never by the payload: a signal that
        # arrives through the authenticated API is something a person stated,
        # and it is confirmed by definition. The service also retires whatever
        # preference this one replaces, so the attribute never has two.
        record_user_signal(serializer, user=self.request.user)
        # A stated preference is explicit intelligence: compile it in now.
        rebuild_brand_brain_safely(serializer.instance.inspiration.brand)

    def perform_update(self, serializer):
        signal = serializer.save()
        # Weight/confidence are intentionally editable in PR2; the compiled
        # snapshot must follow that edit without changing signal provenance.
        rebuild_brand_brain_safely(signal.inspiration.brand)

    def destroy(self, request, *args, **kwargs):
        return APIResponse(
            success=False,
            message="Hard deletion is disabled. Use the reject action instead.",
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """A human agrees with a signal.

        This is the authorised path referenced by the PR2 integrity rules. It
        records the human verdict and who gave it — and leaves `origin`
        untouched, so an inference that a user agreed with is still visibly an
        inference.

        When the inference contradicts a stated preference, agreeing with it
        also explicitly supersedes that preference: the alternative is a brand
        that holds two opposite active truths about one attribute.
        """
        try:
            signal = confirm_signal(self.get_object(), user=request.user)
        except InspirationSignalError as exc:
            return APIResponse(
                success=False,
                message=str(exc),
                error={"code": "PREFERENCE_CONFLICT", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rebuild_brand_brain_safely(signal.inspiration.brand)
        self._finish_analysis_review(signal.inspiration)
        superseded = signal.supersedes.first()
        message = "Signal confirmed."
        if superseded is not None:
            message = (
                "Signal confirmed. It supersedes the previous stated preference "
                f"for {signal.category}/{signal.attribute}."
            )
        return APIResponse(
            success=True,
            message=message,
            data=InspirationSignalSerializer(
                signal, context=self.get_serializer_context()
            ).data,
        )

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """A human withdraws a signal.

        Rejecting a stated preference leaves the attribute without one; it does
        not revive whatever that preference replaced.
        """
        try:
            signal = reject_signal(self.get_object(), user=request.user)
        except InspirationSignalError as exc:
            return APIResponse(
                success=False,
                message=str(exc),
                error={"code": "PREFERENCE_CONFLICT", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rebuild_brand_brain_safely(signal.inspiration.brand)
        self._finish_analysis_review(signal.inspiration)
        return APIResponse(
            success=True,
            message="Signal rejected. It is no longer eligible for retrieval.",
            data=InspirationSignalSerializer(
                signal, context=self.get_serializer_context()
            ).data,
        )

    @staticmethod
    def _finish_analysis_review(inspiration):
        waiting = InspirationSignal.objects.filter(
            inspiration=inspiration,
            origin=InspirationSignal.Origin.AI,
            user_confirmation=InspirationSignal.UserConfirmation.PENDING,
            superseded_at__isnull=True,
        ).exists()
        if not waiting:
            BrandInspiration.objects.filter(
                pk=inspiration.pk,
                analysis_status=BrandInspiration.AnalysisStatus.NEEDS_REVIEW,
            ).update(analysis_status=BrandInspiration.AnalysisStatus.READY)


class ResearchRunViewSet(WorkspaceScopedMixin, WorkspaceResolvedViewSet):
    queryset = ResearchRun.objects.select_related('workspace', 'brand', 'initiated_by').prefetch_related(
        'findings'
    )
    serializer_class = ResearchRunSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        brand_id = self.request.query_params.get('brand_id')
        if brand_id:
            queryset = queryset.filter(brand_id=brand_id)
        return queryset

    @staticmethod
    def _mark_queue_failed(run):
        failed_at = timezone.now()
        run.status = ResearchRun.Status.FAILED
        run.task_id = ''
        run.error = RESEARCH_QUEUE_FAILURE
        run.completed_at = failed_at
        run.save(
            update_fields=['status', 'task_id', 'error', 'completed_at', 'updated_at']
        )

    def _queue_failure_response(self, run):
        return APIResponse(
            success=False,
            message=RESEARCH_QUEUE_FAILURE,
            error={
                'code': 'QUEUE_ENQUEUE_FAILED',
                'message': RESEARCH_QUEUE_FAILURE,
            },
            data=self.get_serializer(run).data,
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except ResearchQueueUnavailable as exc:
            return self._queue_failure_response(exc.run)

    def perform_create(self, serializer):
        from .tasks import research_creative_task

        run = serializer.save(
            workspace=self._authorised_workspace(), initiated_by=self.request.user
        )
        try:
            task_result = research_creative_task.enqueue(str(run.pk))
        except Exception:
            logger.exception(
                'Research run could not enter the durable task queue.',
                extra={
                    'research_run_id': str(run.pk),
                    'workspace_id': str(run.workspace_id),
                },
            )
            self._mark_queue_failed(run)
            raise ResearchQueueUnavailable(run)
        run.task_id = str(task_result.id)
        run.save(update_fields=['task_id', 'updated_at'])

    def update(self, request, *args, **kwargs):
        return APIResponse(
            success=False,
            message='Research runs are immutable. Start a new run instead.',
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def destroy(self, request, *args, **kwargs):
        return APIResponse(
            success=False,
            message='Research history cannot be deleted.',
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        from .tasks import research_creative_task

        run = self.get_object()
        if run.status != ResearchRun.Status.FAILED:
            return APIResponse(
                success=False, message='Only a failed research run can be retried.',
                status=status.HTTP_409_CONFLICT,
            )
        run.status = ResearchRun.Status.QUEUED
        run.error = ''
        run.task_id = ''
        run.completed_at = None
        try:
            task_result = research_creative_task.enqueue(str(run.pk))
        except Exception:
            logger.exception(
                'Research retry could not enter the durable task queue.',
                extra={
                    'research_run_id': str(run.pk),
                    'workspace_id': str(run.workspace_id),
                },
            )
            self._mark_queue_failed(run)
            return self._queue_failure_response(run)
        run.task_id = str(task_result.id)
        run.save(
            update_fields=[
                'status', 'error', 'task_id', 'completed_at', 'updated_at',
            ]
        )
        return APIResponse(
            success=True,
            message='Research queued again.',
            data=self.get_serializer(run).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        run = self.get_object()
        if run.status not in (ResearchRun.Status.NEEDS_REVIEW, ResearchRun.Status.COMPLETED):
            return APIResponse(
                success=False, message='This run is not ready to close.',
                status=status.HTTP_409_CONFLICT,
            )
        run.status = ResearchRun.Status.COMPLETED
        run.save(update_fields=['status', 'updated_at'])
        return APIResponse(success=True, data=self.get_serializer(run).data)


class ResearchFindingViewSet(WorkspaceScopedMixin, viewsets.ReadOnlyModelViewSet):
    queryset = ResearchFinding.objects.select_related(
        'workspace', 'brand', 'run', 'adopted_inspiration'
    )
    serializer_class = ResearchFindingSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def get_queryset(self):
        queryset = super().get_queryset()
        run_id = self.request.query_params.get('run_id')
        brand_id = self.request.query_params.get('brand_id')
        if run_id:
            queryset = queryset.filter(run_id=run_id)
        if brand_id:
            queryset = queryset.filter(brand_id=brand_id)
        return queryset

    @action(detail=True, methods=['post'], url_path='set-rights')
    def set_rights(self, request, pk=None):
        finding = self.get_object()
        value = str(request.data.get('rights_status') or '').upper()
        if value not in ResearchFinding.RightsStatus.values:
            return APIResponse(
                success=False,
                error={'rights_status': 'Choose a valid rights status.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if finding.adopted_inspiration_id:
            return APIResponse(
                success=False,
                message='Rights cannot be rewritten after adoption.',
                status=status.HTTP_409_CONFLICT,
            )
        finding.rights_status = value
        finding.save(update_fields=['rights_status', 'updated_at'])
        return APIResponse(success=True, data=self.get_serializer(finding).data)

    @action(detail=True, methods=['post'])
    def adopt(self, request, pk=None):
        finding = self.get_object()
        usage_scope = request.data.get(
            'usage_scope', BrandInspiration.UsageScope.FULL_REFERENCE
        )
        focus_areas = request.data.get('focus_areas') or []
        from .serializers import validate_reference_graph
        try:
            validate_reference_graph(
                finding.workspace, finding.brand, None, usage_scope, focus_areas
            )
        except DRFValidationError as exc:
            return APIResponse(
                success=False, error=exc.detail, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            inspiration, created = adopt_finding(
                finding,
                user=request.user,
                annotation=request.data.get('annotation', ''),
                usage_scope=usage_scope,
                focus_areas=focus_areas,
            )
        except ResearchError as exc:
            return APIResponse(
                success=False, message=str(exc), status=status.HTTP_409_CONFLICT
            )
        return APIResponse(
            success=True,
            message='Reference adopted into Brand Master.' if created else 'Reference was already adopted.',
            data=BrandInspirationSerializer(
                inspiration, context=self.get_serializer_context()
            ).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
