from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import MarketingAssetViewSet

router = DefaultRouter()
router.register(r'assets', MarketingAssetViewSet, basename='marketing_asset')

urlpatterns = [
    path('', include(router.urls)),
]
