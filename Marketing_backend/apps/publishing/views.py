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
from .tasks import publish_job
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

        # Review gate is mandatory for every media source. Optional content
        # ids let manual uploads bypass approval entirely.
        from apps.content.models import ContentItem

        content_item = ContentItem.objects.filter(
            id=data['content_item_id'], workspace_id=data['workspace_id']
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
            if content_item.asset_id != asset.id:
                return APIResponse(
                    success=False,
                    message="The approved content does not own this media asset.",
                    error={
                        "code": "CONTENT_ASSET_MISMATCH",
                        "message": "Submit the exact saved content version and media for review.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            requested_connection_ids = set(data['social_connection_ids'])
            connections = list(
                SocialConnection.objects.filter(
                    id__in=requested_connection_ids,
                    workspace=workspace,
                )
            )
            if len(connections) != len(requested_connection_ids):
                return APIResponse(
                    success=False,
                    message="One or more selected social accounts are unavailable for this client.",
                    error={"code": "INVALID_SOCIAL_ACCOUNT", "message": "Selection rejected."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            unavailable = [
                connection for connection in connections
                if not connection.publishing_enabled
                or connection.status != SocialConnection.Status.CONNECTED
            ]
            if unavailable:
                return APIResponse(
                    success=False,
                    message="Reconnect or enable every selected account before publishing.",
                    error={"code": "SOCIAL_ACCOUNT_NOT_READY", "message": "Selection rejected."},
                    status=status.HTTP_409_CONFLICT,
                )
            
            # Atomic transaction as requested by user
            with transaction.atomic():
                job = PublishingJob.objects.create(
                    workspace=workspace,
                    asset=asset,
                    content_item=content_item,
                    publish_mode=data['publish_mode'],
                    scheduled_at=data.get('scheduled_at'),
                    timezone=data.get('timezone', 'UTC'),
                    caption=data.get('caption', ''),
                    status=PublishingJob.Status.QUEUED if data['publish_mode'] == PublishingJob.PublishMode.NOW else PublishingJob.Status.SCHEDULED,
                    created_by=request.user if request.user.is_authenticated else None
                )
                
                for connection in connections:
                    PublishingJobItem.objects.create(
                        publishing_job=job,
                        social_connection=connection,
                        status=PublishingJobItem.Status.QUEUED
                    )
            
            # Immediate publishing goes on the queue rather than running
            # inside this request. A multi-channel post with a video upload
            # takes long enough to hit a gateway timeout, and when it did the
            # connection died mid-publish with some channels posted, some not,
            # and nothing to resume it. The job row is the progress record.
            if job.publish_mode == PublishingJob.PublishMode.NOW:
                publish_job.enqueue(str(job.id))
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
        publish_job.enqueue(str(job.id))

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
            
            # Re-runs the job on the worker. Items already PUBLISHED are
            # skipped there, so only the one just reset is republished.
            publish_job.enqueue(str(job.id))
            return APIResponse(success=True, message="Item retried.")
        except PublishingJobItem.DoesNotExist:
            return APIResponse(success=False, message="Item not found.", status=404)
