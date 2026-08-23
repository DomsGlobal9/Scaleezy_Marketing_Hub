from django.tasks import task


@task
def process_source_task(source_id: str):
    from .processing import process_source

    return process_source(source_id)
