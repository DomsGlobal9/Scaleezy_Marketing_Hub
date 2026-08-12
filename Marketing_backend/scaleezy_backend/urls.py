from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/marketing/', include('apps.workspaces.urls')),
    path('api/marketing/', include('apps.social_accounts.urls')),
    path('api/marketing/', include('apps.marketing.urls')),
    path('api/marketing/', include('apps.gemini.urls')),
    path('api/marketing/publishing/', include('apps.publishing.urls')),
    path('api/marketing/analytics/', include('apps.analytics.urls')),
    # Other paths will be added here
]
