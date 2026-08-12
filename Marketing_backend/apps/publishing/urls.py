from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PublishingJobViewSet

router = DefaultRouter()
router.register(r'publishing/jobs', PublishingJobViewSet, basename='publishing_job')

urlpatterns = [
    path('', include(router.urls)),
]
