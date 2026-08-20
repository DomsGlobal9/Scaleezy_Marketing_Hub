from django.contrib import admin

from .models import AuthAuditLog


@admin.register(AuthAuditLog)
class AuthAuditLogAdmin(admin.ModelAdmin):
    """Read-only view of the authentication trail."""

    list_display = ('created_at', 'event', 'who', 'succeeded', 'ip_address', 'reason')
    list_filter = ('event', 'succeeded', 'created_at')
    search_fields = ('attempted_username', 'user__username', 'user__email', 'ip_address')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    @admin.display(description='User')
    def who(self, obj):
        return obj.user or obj.attempted_username or 'anonymous'

    # An audit trail that can be edited is not an audit trail.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
