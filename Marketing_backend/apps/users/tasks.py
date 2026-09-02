from django.tasks import task


@task
def send_signup_alerts_task(brand_id: str):
    from .alerts import send_signup_alerts

    return send_signup_alerts(brand_id)
