from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SocialConnectionViewSet

router = DefaultRouter()
router.register(r'social-accounts', SocialConnectionViewSet, basename='social_connection')

urlpatterns = [
    path('', include(router.urls)),
]
