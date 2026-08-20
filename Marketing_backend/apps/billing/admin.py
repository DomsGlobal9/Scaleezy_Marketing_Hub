from django.contrib import admin

from .models import Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'key', 'monthly_generations', 'monthly_spend_cap', 'price', 'is_default',
    )
    list_filter = ('is_default',)
    search_fields = ('key', 'name')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('workspace', 'plan', 'status', 'period_start', 'period_end')
    list_filter = ('status', 'plan')
    search_fields = ('workspace__workspace_name',)
    autocomplete_fields = ()
