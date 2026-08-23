"""
/api/platform/clients/ — P2 portfolio and P3 client detail.

Picked up by apps.platform.urls, which includes this module by name; nothing
here is reachable under /api/marketing/.
"""
from django.urls import path

from .views_clients import ClientDetailView, ClientPortfolioView

urlpatterns = [
    path('clients/', ClientPortfolioView.as_view(), name='clients'),
    path('clients/<uuid:workspace_id>/', ClientDetailView.as_view(), name='client_detail'),
]
