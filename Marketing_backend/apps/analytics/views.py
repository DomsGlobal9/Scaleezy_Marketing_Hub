from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsWorkspaceMember, get_request_workspace
from apps.content.models import ContentItem
from apps.publishing.models import PublishingJob, PublishingJobItem
from apps.social_accounts.models import SocialConnection

from .models import CampaignROI, DailyMetric, PlatformPerformance
from .serializers import (
    CampaignROISerializer,
    DailyMetricSerializer,
    PlatformPerformanceSerializer,
)


class AnalyticsDashboardView(APIView):
    permission_classes = [IsWorkspaceMember]

    def get(self, request):
        # Was MarketingWorkspace.objects.first(), which served whichever
        # workspace the database returned first to any caller.
        workspace, error = get_request_workspace(request)
        if error:
            return error

        metrics = DailyMetric.objects.filter(workspace=workspace).order_by('date')
        performance = PlatformPerformance.objects.filter(workspace=workspace).order_by(
            '-conversions'
        )
        roi = CampaignROI.objects.filter(workspace=workspace).order_by('-roi_multiplier')

        # Deliberately NOT the APIResponse envelope: the frontend reads
        # data.trend / data.platform_perf / data.roi at the top level.
        # Reshaping this is a separate change with matching frontend edits.
        return Response(
            {
                "trend": DailyMetricSerializer(metrics, many=True).data,
                "platform_perf": PlatformPerformanceSerializer(performance, many=True).data,
                "roi": CampaignROISerializer(roi, many=True).data,
            }
        )


ACCOUNT_ATTENTION_STATUSES = (
    SocialConnection.Status.TOKEN_EXPIRED,
    SocialConnection.Status.REAUTHORIZATION_REQUIRED,
    SocialConnection.Status.PERMISSION_MISSING,
    SocialConnection.Status.REVOKED,
    SocialConnection.Status.CONNECTION_FAILED,
)


def workspace_kpis(workspace):
    """Counts that exist, from the tables that own them.

    This used to return eight fixed numbers ("24.8K reach", "3.8x ROI") to
    every workspace. Nothing ingests reach, engagement or revenue yet, so
    those are not reported at all rather than invented. What IS known is the
    state of the pipeline - accounts, review queue, scheduled and published
    posts - and each tile names the screen that owns it.
    """
    content = ContentItem.objects.filter(workspace=workspace)
    jobs = PublishingJob.objects.filter(workspace=workspace)
    items = PublishingJobItem.objects.filter(publishing_job__workspace=workspace)
    connections = SocialConnection.objects.filter(workspace=workspace)

    attention = connections.filter(status__in=ACCOUNT_ATTENTION_STATUSES).count()
    attention_hint = None
    if attention:
        attention_hint = "%d need%s attention" % (attention, "s" if attention == 1 else "")

    return [
        {
            "key": "awaiting_review",
            "label": "Awaiting review",
            "value": content.filter(status=ContentItem.Status.PENDING_REVIEW).count(),
            "icon": "CheckCircle2",
            "hint": "Generated content waiting for a decision",
        },
        {
            "key": "approved",
            "label": "Approved, not yet published",
            "value": content.filter(status=ContentItem.Status.APPROVED).count(),
            "icon": "Send",
            "accent": "gold",
        },
        {
            "key": "scheduled",
            "label": "Scheduled posts",
            "value": jobs.filter(status__in=[
                PublishingJob.Status.SCHEDULED, PublishingJob.Status.QUEUED,
            ]).count(),
            "icon": "CalendarClock",
        },
        {
            "key": "published",
            "label": "Published posts",
            "value": items.filter(status=PublishingJobItem.Status.PUBLISHED).count(),
            "icon": "Megaphone",
            "accent": "gold",
            "hint": "Per platform, all time",
        },
        {
            "key": "failed",
            "label": "Failed publishes",
            "value": jobs.filter(status=PublishingJob.Status.FAILED).count(),
            "icon": "AlertTriangle",
        },
        {
            "key": "connected_accounts",
            "label": "Connected accounts",
            "value": connections.filter(status=SocialConnection.Status.CONNECTED).count(),
            "icon": "Share2",
            "hint": attention_hint,
        },
    ]


class AnalyticsKPIView(APIView):
    permission_classes = [IsWorkspaceMember]

    def get(self, request):
        workspace, error = get_request_workspace(request)
        if error:
            return error
        # Top-level shape preserved for the same reason as the dashboard.
        return Response({"kpis": workspace_kpis(workspace)})
