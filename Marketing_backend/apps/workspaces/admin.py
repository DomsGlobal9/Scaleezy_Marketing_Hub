from django.contrib import admin

from .models import MarketingWorkspace, WorkspaceMember


class WorkspaceMemberInline(admin.TabularInline):
    model = WorkspaceMember
    extra = 0
    autocomplete_fields = ('user',)
    fields = ('user', 'role', 'status', 'last_active_at')
    readonly_fields = ('last_active_at',)


@admin.register(MarketingWorkspace)
class MarketingWorkspaceAdmin(admin.ModelAdmin):
    list_display = (
        'workspace_name', 'client_code', 'approval_status', 'status',
        'customer_id', 'member_count', 'created_at',
    )
    search_fields = ('workspace_name', 'customer_id', 'client_code')
    list_filter = ('approval_status', 'status', 'timezone', 'default_language')
    inlines = [WorkspaceMemberInline]
    # Approval, lifecycle and identity are platform decisions, made in the
    # console by a PlatformAdmin and written to PlatformAuditLog. Django admin
    # may look, not decide: a staff flag is not platform authority.
    readonly_fields = (
        'client_code', 'approval_status', 'status', 'status_reason',
        'status_changed_at', 'created_at', 'updated_at',
    )

    @admin.display(description='Members')
    def member_count(self, obj):
        return obj.members.count()


@admin.register(WorkspaceMember)
class WorkspaceMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'workspace', 'role', 'status', 'last_active_at', 'created_at')
    list_filter = ('role', 'status')
    search_fields = ('user__username', 'user__email', 'workspace__workspace_name')
    autocomplete_fields = ('user', 'invited_by')
