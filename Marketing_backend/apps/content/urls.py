from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ContentItemViewSet

router = DefaultRouter()
router.register(r'content', ContentItemViewSet, basename='content')

urlpatterns = [path("", include(router.urls))]
