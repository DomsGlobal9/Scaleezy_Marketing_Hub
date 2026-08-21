from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BrandPreferenceViewSet, BrandRuleViewSet, LearningEventViewSet

router = DefaultRouter()
router.register(r'learning-events', LearningEventViewSet, basename='learning-event')
router.register(r'brand-preferences', BrandPreferenceViewSet, basename='brand-preference')
router.register(r'brand-rules', BrandRuleViewSet, basename='brand-rule')

urlpatterns = [
    path('', include(router.urls)),
]
