from django.urls import path

from .views_patterns import (
    PatternCompileView,
    PatternContributorsView,
    PatternLifecycleView,
    PatternListView,
)

urlpatterns = [
    path('patterns/', PatternListView.as_view(), name='patterns'),
    path('patterns/compile/', PatternCompileView.as_view(), name='patterns_compile'),
    path(
        'patterns/<uuid:pattern_id>/contributors/',
        PatternContributorsView.as_view(),
        name='pattern_contributors',
    ),
    path(
        'patterns/<uuid:pattern_id>/<str:move>/',
        PatternLifecycleView.as_view(),
        name='pattern_move',
    ),
]
