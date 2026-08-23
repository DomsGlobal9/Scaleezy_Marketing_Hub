from django.tasks import task


@task
def analyze_inspiration_task(inspiration_id: str):
    from .analysis import analyze_inspiration

    return analyze_inspiration(inspiration_id)
