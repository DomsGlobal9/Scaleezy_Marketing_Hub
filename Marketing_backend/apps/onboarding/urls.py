from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CalibrationDirectionViewSet, OnboardingViewSet

router = DefaultRouter()
router.register(r"onboarding", OnboardingViewSet, basename="onboarding")
router.register(
    r"calibration-directions", CalibrationDirectionViewSet,
    basename="calibration-direction",
)

urlpatterns = [path("", include(router.urls))]
