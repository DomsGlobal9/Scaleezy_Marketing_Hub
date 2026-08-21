from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BrandMasterViewSet

router = DefaultRouter()
router.register(r"brand-master", BrandMasterViewSet, basename="brand-master")

urlpatterns = [path("", include(router.urls))]
