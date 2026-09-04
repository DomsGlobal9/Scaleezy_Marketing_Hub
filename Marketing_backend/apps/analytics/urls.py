from django.urls import path
from .views import (
    AnalyticsDashboardView,
    AnalyticsKPIView,
    GrowthLeadView,
    PerformanceImportView,
    PerformanceSyncView,
    RevenueEventView,
)

urlpatterns = [
    path('dashboard/', AnalyticsDashboardView.as_view(), name='analytics_dashboard'),
    path('kpis/', AnalyticsKPIView.as_view(), name='analytics_kpis'),
    path('performance/sync/', PerformanceSyncView.as_view(), name='performance_sync'),
    path('performance/sync/<uuid:run_id>/', PerformanceSyncView.as_view(), name='performance_sync_detail'),
    path('performance/import/', PerformanceImportView.as_view(), name='performance_import'),
    path('leads/', GrowthLeadView.as_view(), name='growth_leads'),
    path('revenue/', RevenueEventView.as_view(), name='revenue_events'),
]
