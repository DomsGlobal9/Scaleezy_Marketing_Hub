from django.contrib.auth import get_user_model
from django.tasks import task

from apps.audit.models import record_platform_event

from .aggregation import compile_learned_patterns


@task
def compile_learned_patterns_task(actor_id=None):
    result = compile_learned_patterns()
    actor = get_user_model().objects.filter(pk=actor_id).first() if actor_id else None
    record_platform_event(
        actor=actor,
        action='LEARNED_PATTERNS_COMPILED',
        target=f"pattern-version:{result['pattern_version']}",
        detail=result,
    )
    return result
