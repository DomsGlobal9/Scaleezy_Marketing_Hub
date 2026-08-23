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

# One module per console slice, so slices can be built and reviewed alone:
#   urls_clients   — P2 portfolio, P3 client detail
#   urls_controls  — P4 master controls, P7 platform admins
#   urls_universal — P6 standards & inspiration library authoring
# Checked for existence rather than imported blindly, so a slice that is not
# written yet is simply absent — while a real import error inside a slice
# that does exist still fails loudly.
import importlib
import importlib.util

for _slice in ('urls_clients', 'urls_controls', 'urls_universal', 'urls_patterns'):
    if importlib.util.find_spec(f'apps.platform.{_slice}') is not None:
        urlpatterns += importlib.import_module(f'apps.platform.{_slice}').urlpatterns
