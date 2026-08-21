from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BrandSourceViewSet, BrandMemoryViewSet

router = DefaultRouter()
router.register(r'sources', BrandSourceViewSet, basename='knowledge-source')
router.register(r'memories', BrandMemoryViewSet, basename='knowledge-memory')

urlpatterns = [
    path('', include(router.urls)),
]
