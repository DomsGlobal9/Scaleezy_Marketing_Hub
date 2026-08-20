from django.contrib import admin

from .models import TaskRun


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = ('task_path', 'status', 'queue_name', 'attempts', 'enqueued_at', 'finished_at')
    list_filter = ('status', 'queue_name', 'task_path')
    search_fields = ('id', 'task_path')
    readonly_fields = (
        'id', 'task_path', 'args', 'kwargs', 'worker_ids', 'errors', 'return_value',
        'enqueued_at', 'started_at', 'last_attempted_at', 'finished_at',
    )
