from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BillingViewSet

router = DefaultRouter()
router.register(r'billing', BillingViewSet, basename='billing')

urlpatterns = [path("", include(router.urls))]
