from django.contrib import admin

from .models import Brand


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace', 'industry', 'is_default', 'has_logo', 'status')
    list_filter = ('status', 'is_default', 'layout_preference')
    search_fields = ('name', 'industry', 'instagram_handle', 'workspace__workspace_name')
    readonly_fields = ('created_at', 'updated_at', 'logo_url', 'logo_storage_path')
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
        ('Meta', {'fields': ('created_by', 'created_at', 'updated_at')}),
    )

    @admin.display(boolean=True, description='Logo')
    def has_logo(self, obj):
        return obj.has_logo
