from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BrandPreferenceViewSet,
    BrandRuleViewSet,
    LearningEventViewSet,
    LearningUsageView,
)

router = DefaultRouter()
router.register(r'learning-events', LearningEventViewSet, basename='learning-event')
router.register(r'brand-preferences', BrandPreferenceViewSet, basename='brand-preference')
router.register(r'brand-rules', BrandRuleViewSet, basename='brand-rule')

urlpatterns = [
    # Before the router: a plain path, so no viewset detail route can claim it.
    path('learning/usage/', LearningUsageView.as_view(), name='learning-usage'),
    path('', include(router.urls)),
]
