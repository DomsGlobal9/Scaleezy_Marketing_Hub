from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BrandInspirationViewSet, InspirationSignalViewSet

router = DefaultRouter()
# The reference and the signals derived from it are addressed separately on
# purpose: a consumer must be able to fetch one without dragging in the other.
router.register(r'inspirations', BrandInspirationViewSet, basename='inspiration')
router.register(
    r'inspiration-signals', InspirationSignalViewSet, basename='inspiration-signal'
)

urlpatterns = [
    path('', include(router.urls)),
]
