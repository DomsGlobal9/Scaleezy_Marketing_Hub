from django.tasks import task


@task
def sync_performance_task(run_id: str):
    from .services import sync_performance

    return sync_performance(run_id)
