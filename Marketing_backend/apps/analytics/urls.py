from django.urls import path
from .views import AnalyticsDashboardView, AnalyticsKPIView

urlpatterns = [
    path('dashboard/', AnalyticsDashboardView.as_view(), name='analytics_dashboard'),
    path('kpis/', AnalyticsKPIView.as_view(), name='analytics_kpis'),
]
