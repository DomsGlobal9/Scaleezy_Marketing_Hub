from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('apps.users.urls')),
    path('api/marketing/', include('apps.workspaces.urls')),
    path('api/marketing/', include('apps.social_accounts.urls')),
    path('api/marketing/', include('apps.marketing.urls')),
    path('api/marketing/', include('apps.brands.urls')),
    path('api/marketing/', include('apps.content.urls')),
    path('api/marketing/', include('apps.feedback.urls')),
    path('api/marketing/', include('apps.layouts.urls')),
    path('api/marketing/', include('apps.billing.urls')),
    path('api/marketing/', include('apps.ai.urls')),
    path('api/marketing/', include('apps.gemini.urls')),
    path('api/marketing/publishing/', include('apps.publishing.urls')),
    path('api/marketing/analytics/', include('apps.analytics.urls')),
    path('api/marketing/knowledge/', include('apps.knowledge.urls')),
    path('api/marketing/', include('apps.inspirations.urls')),
    path('api/marketing/', include('apps.learning.urls')),
    path('api/marketing/', include('apps.context.urls')),
    path('api/marketing/', include('apps.onboarding.urls')),
    path('api/marketing/', include('apps.universal.urls')),
    # The Scaleezy console. Its own namespace and its own gate (IsPlatformAdmin);
    # nothing under /api/marketing/ ever grants cross-tenant access.
    path('api/platform/', include('apps.platform.urls')),
    # Other paths will be added here
]
