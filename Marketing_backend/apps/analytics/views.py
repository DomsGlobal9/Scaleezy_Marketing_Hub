from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsWorkspaceMember, get_request_workspace
from apps.common.responses import APIResponse

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


class AnalyticsKPIView(APIView):
    permission_classes = [IsWorkspaceMember]

    def get(self, request):
        workspace, error = get_request_workspace(request)
        if error:
            return error

        # TODO: derive these from DailyMetric / PublishingJob rather than
        # returning fixed values. The shape is what the Overview tab consumes.
        kpis = [
            {"label": "Active Campaigns", "value": "2", "icon": "Megaphone", "hint": "This month"},
            {"label": "Scheduled Posts", "value": "8", "icon": "CalendarClock", "accent": "gold"},
            {"label": "Connected Accounts", "value": "4", "icon": "Share2"},
            {"label": "Published Posts", "value": "126", "icon": "Send", "accent": "gold"},
            {"label": "Campaign Reach", "value": "24.8K", "icon": "Users", "hint": "Last 30 days"},
            {"label": "Engagement Rate", "value": "6.8%", "icon": "Heart", "accent": "gold"},
            {"label": "Repeat Purchase Rate", "value": "40%", "icon": "Repeat"},
            {"label": "Marketing ROI", "value": "3.8x", "icon": "CircleDollarSign", "accent": "gold"},
        ]
        # Top-level shape preserved for the same reason as the dashboard.
        return Response({"kpis": kpis})
