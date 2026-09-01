from rest_framework.routers import DefaultRouter

from .views import AutopilotPolicyViewSet, AutopilotRunViewSet

router = DefaultRouter()
router.register('autopilot/policies', AutopilotPolicyViewSet, basename='autopilot-policy')
router.register('autopilot/runs', AutopilotRunViewSet, basename='autopilot-run')

urlpatterns = router.urls
