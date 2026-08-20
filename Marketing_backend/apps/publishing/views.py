from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db import transaction
from .models import PublishingJob, PublishingJobItem
from apps.workspaces.models import MarketingWorkspace
from apps.marketing.models import MarketingAsset
from apps.social_accounts.models import SocialConnection
from .serializers import PublishingJobSerializer, CreatePublishingJobSerializer
from rest_framework.permissions import IsAuthenticated
from apps.common.permissions import authorize_workspace
from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import IsWorkspaceMember
from apps.common.responses import APIResponse
from .services import execute_publishing_job
from django.utils import timezone

class PublishingJobViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    queryset = PublishingJob.objects.all().prefetch_related('items')
    serializer_class = PublishingJobSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember]
    # Lists are scoped by WorkspaceScopedMixin, so an unresolvable workspace
    # is safe here; writes authorise the id they actually use, below.
    requires_workspace = False

    def create(self, request, *args, **kwargs):
        serializer = CreatePublishingJobSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(success=False, error=serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        data = serializer.validated_data

        # Authorise the workspace this request actually writes to. The
        # permission class checks whatever resolve_workspace_id returned,
        # which is not necessarily this value.
        _membership, denied = authorize_workspace(request, data['workspace_id'])
        if denied:
            return denied

        # Review gate: when the request names a content item, it must have been
        # approved. Nothing reaches a real audience without a human decision.
        content_item = None
        content_item_id = request.data.get('content_item_id')
        if content_item_id:
            from apps.content.models import ContentItem

            content_item = ContentItem.objects.filter(
                id=content_item_id, workspace_id=data['workspace_id']
            ).first()
            if content_item is None:
                return APIResponse(
                    success=False, message="Content not found.",
                    status=status.HTTP_404_NOT_FOUND,
                )
            if not content_item.is_publishable:
                return APIResponse(
                    success=False,
                    message="This content has not been approved for publishing.",
                    error={
                        "code": "NOT_APPROVED",
                        "message": f"Content is {content_item.get_status_display()}.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        try:
            workspace = MarketingWorkspace.objects.get(id=data['workspace_id'])
            asset = MarketingAsset.objects.get(id=data['asset_id'], workspace=workspace)
            
            # Atomic transaction as requested by user
            with transaction.atomic():
                job = PublishingJob.objects.create(
                    workspace=workspace,
                    asset=asset,
                    publish_mode=data['publish_mode'],
                    scheduled_at=data.get('scheduled_at'),
                    timezone=data.get('timezone', 'UTC'),
                    caption=data.get('caption', ''),
                    status=PublishingJob.Status.QUEUED if data['publish_mode'] == PublishingJob.PublishMode.NOW else PublishingJob.Status.SCHEDULED,
                    created_by=request.user if request.user.is_authenticated else None
                )
                
                connections = SocialConnection.objects.filter(
                    id__in=data['social_connection_ids'],
                    workspace=workspace
                )
                
                if not connections.exists():
                    raise ValueError("No valid social connections selected.")
                    
                for connection in connections:
                    # Basic validation
                    if not connection.publishing_enabled:
                        continue
                        
                    PublishingJobItem.objects.create(
                        publishing_job=job,
                        social_connection=connection,
                        status=PublishingJobItem.Status.QUEUED
                    )
            
            # If immediate publish mode, execute synchronously
            if job.publish_mode == PublishingJob.PublishMode.NOW:
                execute_publishing_job(job.id)
                # Refresh job from db to get latest status
                job.refresh_from_db()
                
            return APIResponse(success=True, data=PublishingJobSerializer(job).data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return APIResponse(success=False, message=str(e), status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """
        Retries all failed items in a job.
        """
        job = self.get_object()
        failed_items = job.items.filter(status=PublishingJobItem.Status.FAILED)
        
        for item in failed_items:
            item.status = PublishingJobItem.Status.QUEUED
            item.save()
        execute_publishing_job(job.id)
            
        if failed_items.exists():
            job.status = PublishingJob.Status.PUBLISHING
            job.save()
            
        return APIResponse(success=True, message=f"Queued {failed_items.count()} items for retry.")
        
    @action(detail=False, methods=['post'], url_path='items/(?P<item_id>[^/.]+)/retry')
    def retry_item(self, request, item_id=None):
        """
        Retries a specific failed item.
        """
        try:
            # IDOR fix: previously any caller with an item id could retry it,
            # publishing to a social account in someone else's workspace.
            item = PublishingJobItem.objects.select_related('publishing_job').get(
                id=item_id,
                publishing_job__workspace__in=self.accessible_workspace_ids(),
            )
            if item.status != PublishingJobItem.Status.FAILED:
                return APIResponse(success=False, message="Item is not in FAILED state.", status=400)
                
            item.status = PublishingJobItem.Status.QUEUED
            item.save()
            
            job = item.publishing_job
            job.status = PublishingJob.Status.PUBLISHING
            job.save()
            
            # For simplicity in MVP, we just execute the whole job again synchronously
            # Or execute a single item synchronous logic if needed. For now just doing the whole job if any fails.
            execute_publishing_job(job.id)
            return APIResponse(success=True, message="Item retried.")
        except PublishingJobItem.DoesNotExist:
            return APIResponse(success=False, message="Item not found.", status=404)
