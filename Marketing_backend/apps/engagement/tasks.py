from django.tasks import task


@task
def sync_engagement_task(run_id: str):
    from .services import sync_inbox

    return sync_inbox(run_id)


@task
def draft_engagement_reply_task(item_id: str):
    from .services import draft_reply

    return draft_reply(item_id)
