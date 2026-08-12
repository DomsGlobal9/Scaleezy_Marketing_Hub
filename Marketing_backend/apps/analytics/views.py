from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.workspaces.models import MarketingWorkspace
from .models import DailyMetric, PlatformPerformance, CampaignROI
from .serializers import DailyMetricSerializer, PlatformPerformanceSerializer, CampaignROISerializer

class AnalyticsDashboardView(APIView):
    # permission_classes = [IsAuthenticated] # Temporarily removed for easier dev

    def get(self, request):
        workspace = MarketingWorkspace.objects.first()
        if not workspace:
            return Response({"error": "No workspace found"}, status=404)
            
        metrics = DailyMetric.objects.filter(workspace=workspace).order_by('date')
        performance = PlatformPerformance.objects.filter(workspace=workspace).order_by('-conversions')
        roi = CampaignROI.objects.filter(workspace=workspace).order_by('-roi_multiplier')
        
        return Response({
            "trend": DailyMetricSerializer(metrics, many=True).data,
            "platform_perf": PlatformPerformanceSerializer(performance, many=True).data,
            "roi": CampaignROISerializer(roi, many=True).data
        })

class AnalyticsKPIView(APIView):
    def get(self, request):
        workspace = MarketingWorkspace.objects.first()
        if not workspace:
            return Response({"error": "No workspace found"}, status=404)
        
        # Calculate aggregations or just return mock format for now
        # so frontend Overview tab has real API data structure
        
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
        
        return Response({"kpis": kpis})
