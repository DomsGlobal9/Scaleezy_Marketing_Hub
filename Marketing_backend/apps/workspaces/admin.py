from django.contrib import admin

from .models import MarketingWorkspace, WorkspaceMember


class WorkspaceMemberInline(admin.TabularInline):
    """Who is on the client — to look at, not to change.

    Membership is how a person reaches a tenant's data, so it is granted only
    through the product (Client Admin, bounded by the actor's own role) or the
    platform console (attach-user, audited). An inline that let Django staff
    add themselves to an approved client would be a tenant-isolation bypass.
    """

    model = WorkspaceMember
    extra = 0
    can_delete = False
    fields = ('user', 'role', 'status', 'last_active_at')
    readonly_fields = ('user', 'role', 'status', 'last_active_at')

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


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

    # A workspace created here would be born APPROVED (the column default for
    # pre-existing rows) with no approval record — a second front door around
    # signup. Clients are created by signup or add-client, never here.
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Members')
    def member_count(self, obj):
        return obj.members.count()


@admin.register(WorkspaceMember)
class WorkspaceMemberAdmin(admin.ModelAdmin):
    """View-only. See WorkspaceMemberInline for why."""

    list_display = ('user', 'workspace', 'role', 'status', 'last_active_at', 'created_at')
    list_filter = ('role', 'status')
    search_fields = ('user__username', 'user__email', 'workspace__workspace_name')
    readonly_fields = ('user', 'workspace', 'role', 'status', 'invited_by', 'last_active_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
