"""
Generation through the gateway.

The chain the architecture requires, in one function:

    source systems -> Brand Brain -> Context Gateway -> AI Router -> adapter

Nothing here knows a provider exists. The router picks one from what the
workspace has routed, and the adapter turns the provider-neutral brief into
whatever that API wants.
"""
import logging

from apps.ai.models import Capability
from apps.ai.router import AIRouter, NoProviderAvailable

from .context_gateway import TaskType, build_generation_context, context_as_brief

logger = logging.getLogger(__name__)

CAPABILITY_FOR_TASK = {
    TaskType.COPY: Capability.TEXT,
    TaskType.IMAGE: Capability.IMAGE,
    TaskType.VIDEO: Capability.VIDEO,
    TaskType.IMAGE_ANALYSIS: Capability.TEXT,
}


class NoProviderConfigured(Exception):
    """The workspace has not routed a provider to this capability."""


def generate_with_context(workspace, brand, task_type=TaskType.COPY, *, instruction='',
                          channel='', content_format='', objective='',
                          content_item_id=None):
    """Build brand context, then dispatch it through the router.

    Returns the provider result alongside the context that produced it, so a
    generation can always be explained by the brain version it was cut from.
    """
    context = build_generation_context(
        workspace, brand, task_type,
        instruction=instruction, channel=channel,
        content_format=content_format, objective=objective,
    )
    brief = context_as_brief(context)
    capability = CAPABILITY_FOR_TASK[task_type]

    try:
        result = AIRouter(workspace).dispatch(capability, brief, content_item_id)
    except NoProviderAvailable as exc:
        # Reported as unavailable rather than dressed up as an empty success:
        # a workspace with no provider routed has not generated anything.
        raise NoProviderConfigured(str(exc)) from exc

    return {
        'result': result,
        'brain_version': context['brain_version'],
        'task_type': task_type,
        'context_summary': {
            'hard_rules': len(context['hard_rules']),
            'soft_rules': len(context['soft_rules']),
            'preferences': len(context['preferences']),
            'verified_truth': len(context['verified_truth']),
            'unresolved_conflicts': context['unresolved_conflict_count'],
        },
    }
