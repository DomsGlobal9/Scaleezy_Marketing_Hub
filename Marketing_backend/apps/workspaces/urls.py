from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import WorkspaceSettingsView, MarketingWorkspaceViewSet

router = DefaultRouter()
router.register(r'workspaces', MarketingWorkspaceViewSet, basename='workspace')

urlpatterns = [
    path('settings/', WorkspaceSettingsView.as_view(), name='workspace_settings'),
    path('', include(router.urls)),
]
