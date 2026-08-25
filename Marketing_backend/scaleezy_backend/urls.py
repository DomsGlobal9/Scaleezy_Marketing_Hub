from django.conf import settings
from django.conf.urls.static import static
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
    path('api/marketing/', include('apps.universal.urls')),
    path('api/marketing/', include('apps.inspirations.urls')),
    path('api/marketing/', include('apps.learning.urls')),
    path('api/marketing/', include('apps.context.urls')),
    path('api/marketing/', include('apps.onboarding.urls')),
    path('api/platform/', include('apps.platform.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
