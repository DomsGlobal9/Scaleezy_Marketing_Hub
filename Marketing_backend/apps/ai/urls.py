from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AIProviderCatalogueView,
    AIUsageViewSet,
    WorkspaceAIProviderViewSet,
    WorkspaceAIRouteViewSet,
)

router = DefaultRouter()
router.register(r'ai/providers', WorkspaceAIProviderViewSet, basename='ai_provider')
router.register(r'ai/routes', WorkspaceAIRouteViewSet, basename='ai_route')
router.register(r'ai/usage', AIUsageViewSet, basename='ai_usage')

urlpatterns = [
    path('ai/catalogue/', AIProviderCatalogueView.as_view(), name='ai_catalogue'),
    path('', include(router.urls)),
]
