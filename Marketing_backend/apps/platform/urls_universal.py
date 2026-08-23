"""
P6 — /api/platform/standards/ and /api/platform/inspirations/.

Picked up by `apps.platform.urls` because this module exists; every view
inherits the IsPlatformAdmin gate from `PlatformView`.
"""
from django.urls import path

from .views_universal import (
    InspirationDetailView,
    InspirationLifecycleView,
    InspirationListView,
    StandardDetailView,
    StandardLifecycleView,
    StandardListView,
)

urlpatterns = [
    path('standards/', StandardListView.as_view(), name='standards'),
    path('standards/<uuid:standard_id>/', StandardDetailView.as_view(), name='standard_detail'),
    path(
        'standards/<uuid:standard_id>/<str:move>/',
        StandardLifecycleView.as_view(), name='standard_move',
    ),
    path('inspirations/', InspirationListView.as_view(), name='inspirations'),
    path(
        'inspirations/<uuid:inspiration_id>/',
        InspirationDetailView.as_view(), name='inspiration_detail',
    ),
    path(
        'inspirations/<uuid:inspiration_id>/<str:move>/',
        InspirationLifecycleView.as_view(), name='inspiration_move',
    ),
]
