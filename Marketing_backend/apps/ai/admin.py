from django.contrib import admin

from .models import AIProvider, AIUsageLog, WorkspaceAIProvider, WorkspaceAIRoute


@admin.register(AIProvider)
class AIProviderAdmin(admin.ModelAdmin):
    """Operator-level catalogue. is_available is the global kill switch."""

    list_display = ('display_name', 'key', 'is_available', 'default_model', 'unit_cost')
    list_filter = ('is_available',)
    search_fields = ('key', 'display_name')
    list_editable = ('is_available',)


@admin.register(WorkspaceAIProvider)
class WorkspaceAIProviderAdmin(admin.ModelAdmin):
    list_display = ('provider', 'workspace', 'enabled', 'has_credentials',
                    'last_health_ok', 'last_health_check_at')
    list_filter = ('enabled', 'provider', 'last_health_ok')
    search_fields = ('workspace__workspace_name', 'provider__key')
    # Ciphertext is never editable by hand — a mistyped value would be
    # undetectable until a generation failed.
    readonly_fields = ('credentials_encrypted', 'last_health_check_at',
                       'last_health_ok', 'last_error')

    @admin.display(boolean=True, description='Key set')
    def has_credentials(self, obj):
        return obj.has_credentials


@admin.register(WorkspaceAIRoute)
class WorkspaceAIRouteAdmin(admin.ModelAdmin):
    list_display = ('workspace', 'capability', 'provider', 'priority', 'strategy', 'enabled')
    list_filter = ('capability', 'strategy', 'enabled')
    search_fields = ('workspace__workspace_name', 'provider__key')
    list_editable = ('priority', 'enabled')


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'workspace', 'provider', 'capability',
                    'success', 'selected', 'cost', 'latency_ms')
    list_filter = ('capability', 'success', 'selected', 'provider')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
