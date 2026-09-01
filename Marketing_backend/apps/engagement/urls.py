from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import EngagementItemViewSet, EngagementSyncRunViewSet, SavedReplyViewSet


router = DefaultRouter()
router.register(r'engagement/items', EngagementItemViewSet, basename='engagement-item')
router.register(r'engagement/sync-runs', EngagementSyncRunViewSet, basename='engagement-sync')
router.register(r'engagement/saved-replies', SavedReplyViewSet, basename='saved-reply')

urlpatterns = [path('', include(router.urls))]
