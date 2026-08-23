"""
/api/platform/ — the Scaleezy console. Its own namespace, its own gate.

Add P2–P7 here. Never register a platform view under /api/marketing/.
"""
from django.urls import path

from .views import (
    AttachUserView,
    PlatformHealthView,
    SignupDecisionView,
    SignupQueueView,
)

app_name = 'platform'

urlpatterns = [
    path('health/', PlatformHealthView.as_view(), name='health'),
    path('signups/', SignupQueueView.as_view(), name='signups'),
    path(
        'signups/<uuid:brand_id>/<str:decision>/',
        SignupDecisionView.as_view(), name='signup_decision',
    ),
    path(
        'clients/<uuid:workspace_id>/attach-user/',
        AttachUserView.as_view(), name='attach_user',
    ),
]
