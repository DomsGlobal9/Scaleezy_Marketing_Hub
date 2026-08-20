from django.contrib import admin

from .models import Feedback, FeedbackElement


@admin.register(FeedbackElement)
class FeedbackElementAdmin(admin.ModelAdmin):
    list_display = ('label', 'group', 'key', 'position', 'is_active', 'is_provisional')
    list_filter = ('group', 'is_active', 'is_provisional')
    search_fields = ('key', 'label', 'description')
    list_editable = ('position', 'is_active', 'is_provisional')


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'workspace', 'verdict', 'sentiment', 'urgency', 'created_at')
    list_filter = ('verdict', 'sentiment', 'urgency', 'created_at')
    search_fields = ('feedback_text', 'fix_request', 'workspace__workspace_name')
    readonly_fields = (
        'embedding_model', 'pattern_extracted', 'rules_updated', 'created_at',
    )
    # The embedding is a few hundred floats; rendering it helps nobody.
    exclude = ('embedding',)
