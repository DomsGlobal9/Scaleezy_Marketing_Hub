"""
Brand in Django admin: a window, not a control panel.

Approval and rejection are platform decisions. They are made in the Scaleezy
console by a `PlatformAdmin` and written to `PlatformAuditLog`; a Django
`is_staff` flag is a different, weaker thing and must not be able to make
them. So `status`, `reviewed_at` and `reviewed_by` are read-only here and
there are no approve/reject actions — an earlier interim version had them,
which let ordinary staff approve customers outside the audited boundary.

(A Django superuser can always do anything through the ORM; that is inherent
to superuser and is why there should be almost none of them.)
"""
from django.contrib import admin

from .models import Brand


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace', 'industry', 'is_default', 'has_logo', 'status')
    list_filter = ('status', 'is_default')
    search_fields = ('name', 'industry', 'instagram_handle', 'workspace__workspace_name')
    readonly_fields = (
        'created_at', 'updated_at', 'logo_url', 'logo_storage_path',
        # Platform-owned. Changed only by apps.brands.services.approval,
        # only from the console, always audited.
        'status', 'reviewed_at', 'reviewed_by',
        # Tenancy is not editable from a Django form: moving a brand between
        # workspaces would move its intelligence across a tenant boundary.
        'workspace',
    )

    # A brand added here would be born ACTIVE in whatever workspace staff
    # picked. Brands are created through the product, inside an authorised
    # workspace, with the status the client's approval dictates.
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    fieldsets = (
        (None, {'fields': ('workspace', 'name', 'industry', 'status', 'is_default')}),
        ('Visual identity', {'fields': ('palette', 'fonts')}),
        ('Logo', {'fields': ('logo_url', 'logo_file_name', 'logo_storage_path',
                             'show_logo_on_posters')}),
        ('Voice', {'fields': ('tagline', 'cta_keyword', 'brand_tone')}),
        ('Contact', {'fields': ('contact_phone', 'show_phone_on_posters')}),
        ('Market', {'fields': ('instagram_handle', 'competitors')}),
        ('Learned rules', {'fields': ('creative_brain',),
                           'description': 'Populated by the training engine.'}),
        ('Approval', {'fields': ('reviewed_at', 'reviewed_by'),
                      'description': 'Decided in the Scaleezy console, not here.'}),
        ('Meta', {'fields': ('created_by', 'created_at', 'updated_at')}),
    )

    @admin.display(boolean=True, description='Logo')
    def has_logo(self, obj):
        return obj.has_logo
