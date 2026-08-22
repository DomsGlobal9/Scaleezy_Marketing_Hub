from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import GeminiGenerationViewSet

router = DefaultRouter()
router.register(r'ai-generation', GeminiGenerationViewSet, basename='ai-generation')
# Backward-compatible alias for older clients. New product code uses the
# provider-neutral endpoint above; both paths dispatch through AIRouter.
router.register(r'gemini', GeminiGenerationViewSet, basename='legacy-gemini')

urlpatterns = [
    path('', include(router.urls)),
]
