"""
P4 master controls + P7 platform admins — included by `apps.platform.urls`.

Lifecycle transitions are three fixed routes onto one view (the transition is
bound in the URL, never read from the body).
"""
from django.urls import path

from .views_controls import (
    ClientLifecycleView,
    ClientLimitsView,
    ClientPlanView,
    ClientQualityView,
    ClientRecompileBrainView,
    ClientSpendCapView,
    ClientUniversalView,
    PlatformAdminRevokeView,
    PlatformAdminsView,
    ProviderAvailabilityView,
    PlatformProviderListView,
)

urlpatterns = [
    # ── P4 master controls, per client
    path(
        'clients/<uuid:workspace_id>/limits/',
        ClientLimitsView.as_view(), name='client_limits',
    ),
    path(
        'clients/<uuid:workspace_id>/suspend/',
        ClientLifecycleView.as_view(transition='suspend'), name='client_suspend',
    ),
    path(
        'clients/<uuid:workspace_id>/reactivate/',
        ClientLifecycleView.as_view(transition='reactivate'), name='client_reactivate',
    ),
    path(
        'clients/<uuid:workspace_id>/archive/',
        ClientLifecycleView.as_view(transition='archive'), name='client_archive',
    ),
    path(
        'clients/<uuid:workspace_id>/universal/',
        ClientUniversalView.as_view(), name='client_universal',
    ),
    path(
        'clients/<uuid:workspace_id>/quality/',
        ClientQualityView.as_view(), name='client_quality',
    ),
    path(
        'clients/<uuid:workspace_id>/plan/',
        ClientPlanView.as_view(), name='client_plan',
    ),
    path(
        'clients/<uuid:workspace_id>/spend-cap/',
        ClientSpendCapView.as_view(), name='client_spend_cap',
    ),
    path(
        'clients/<uuid:workspace_id>/recompile-brain/',
        ClientRecompileBrainView.as_view(), name='client_recompile_brain',
    ),
    # ── P4 platform-wide kill switch
    path('providers/', PlatformProviderListView.as_view(), name='provider_list'),
    path(
        'providers/<uuid:provider_id>/availability/',
        ProviderAvailabilityView.as_view(), name='provider_availability',
    ),
    # ── P7 platform admins
    path('admins/', PlatformAdminsView.as_view(), name='admins'),
    path(
        'admins/<int:user_id>/revoke/',
        PlatformAdminRevokeView.as_view(), name='admin_revoke',
    ),
]
