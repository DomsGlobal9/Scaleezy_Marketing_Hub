from django.contrib import admin

from .models import Brand
from .services.approval import approve_brand, reject_brand


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace', 'industry', 'is_default', 'has_logo', 'status')
    list_filter = ('status', 'is_default', 'layout_preference')
    search_fields = ('name', 'industry', 'instagram_handle', 'workspace__workspace_name')
    readonly_fields = (
        'created_at', 'updated_at', 'logo_url', 'logo_storage_path',
        'reviewed_at', 'reviewed_by',
    )
    # Interim approval control for signups until the platform console (Super
    # Admin B9a) exists. Both actions go through the same service the console
    # will call, so moving them later changes the surface, not the rules.
    actions = ('approve_brands', 'reject_brands')
    fieldsets = (
        (None, {'fields': ('workspace', 'name', 'industry', 'status', 'is_default')}),
        ('Visual identity', {'fields': ('palette', 'fonts', 'layout_preference')}),
        ('Logo', {'fields': ('logo_url', 'logo_file_name', 'logo_storage_path',
                             'show_logo_on_posters')}),
        ('Voice', {'fields': ('tagline', 'cta_keyword', 'brand_tone')}),
        ('Contact', {'fields': ('contact_phone', 'show_phone_on_posters')}),
        ('Market', {'fields': ('instagram_handle', 'competitors')}),
        ('Learned rules', {'fields': ('creative_brain',),
                           'description': 'Populated by the training engine.'}),
        ('Approval', {'fields': ('reviewed_at', 'reviewed_by'),
                      'description': 'Set by the approve / reject actions.'}),
        ('Meta', {'fields': ('created_by', 'created_at', 'updated_at')}),
    )

    @admin.display(boolean=True, description='Logo')
    def has_logo(self, obj):
        return obj.has_logo

    @admin.action(description='Approve selected pending brands')
    def approve_brands(self, request, queryset):
        approved = 0
        for brand in queryset.filter(status=Brand.Status.PENDING):
            approve_brand(brand, by=request.user)
            approved += 1
        self.message_user(request, f"{approved} brand(s) approved.")

    @admin.action(description='Reject selected brands (archive, reversible)')
    def reject_brands(self, request, queryset):
        rejected = 0
        for brand in queryset.exclude(status=Brand.Status.ARCHIVED):
            reject_brand(brand, by=request.user)
            rejected += 1
        self.message_user(request, f"{rejected} brand(s) archived.")
