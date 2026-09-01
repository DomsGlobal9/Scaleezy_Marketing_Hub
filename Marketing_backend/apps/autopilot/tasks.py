from django.tasks import task


@task
def execute_autopilot_run(run_id: str):
    from .services import execute_run

    return execute_run(run_id)
