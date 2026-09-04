from django.urls import path

from .views_patterns import (
    PatternCompileStatusView,
    PatternCompileView,
    PatternContributorsView,
    PatternLifecycleView,
    PatternListView,
)

urlpatterns = [
    path('patterns/', PatternListView.as_view(), name='patterns'),
    path('patterns/compile/', PatternCompileView.as_view(), name='patterns_compile'),
    path(
        'patterns/compile/<str:task_id>/',
        PatternCompileStatusView.as_view(),
        name='patterns_compile_status',
    ),
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
