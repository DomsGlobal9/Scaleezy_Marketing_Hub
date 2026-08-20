from django.contrib import admin

from .models import ContentItem


@admin.register(ContentItem)
class ContentItemAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'workspace', 'brand', 'content_format', 'status', 'version', 'created_at')
    list_filter = ('status', 'content_format', 'created_at')
    search_fields = ('headline', 'caption', 'workspace__workspace_name')
    readonly_fields = ('created_at', 'updated_at', 'reviewed_at')
