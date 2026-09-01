"""Operational visibility only; policy changes use the audited product console."""
from django.contrib import admin

from .models import AutopilotPolicy, AutopilotRun, AutopilotStep


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AutopilotPolicy)
class AutopilotPolicyAdmin(ReadOnlyAdmin):
    list_display = ('name', 'workspace', 'brand', 'mode', 'enabled', 'paused')
    list_filter = ('mode', 'enabled', 'paused', 'emergency_stop')
    search_fields = ('name', 'workspace__workspace_name', 'brand__name')


@admin.register(AutopilotRun)
class AutopilotRunAdmin(ReadOnlyAdmin):
    list_display = ('policy', 'workspace', 'status', 'scheduled_for', 'created_at')
    list_filter = ('status',)
    search_fields = ('policy__name', 'workspace__workspace_name', 'dedupe_key')


@admin.register(AutopilotStep)
class AutopilotStepAdmin(ReadOnlyAdmin):
    list_display = ('run', 'key', 'status', 'created_at')
    list_filter = ('status', 'key')
