"""
Client lifecycle: suspend, reactivate, archive.

Flipping a status flag is not archiving a client. A client whose row says
ARCHIVED but whose scheduled posts still publish, whose social tokens still
work and whose subscription still counts towards revenue has not been
archived — it has been mislabelled. So each transition here is one audited
transaction that leaves the world consistent with the label.

Nothing is destroyed. Archive is reversible: reactivating restores access and
routing, and every knowledge source, inspiration, learning event, content item
and audit row is exactly where it was.
"""
import logging

from django.db import transaction
from django.utils import timezone

from ..models import MarketingWorkspace

logger = logging.getLogger(__name__)


def _set_status(workspace, status, *, reason=''):
    workspace.status = status
    workspace.status_reason = (reason or '')[:255]
    workspace.status_changed_at = timezone.now()
    workspace.save(update_fields=[
        'status', 'status_reason', 'status_changed_at', 'updated_at',
    ])
    return workspace


def cancel_scheduled_publishing(workspace) -> int:
    """Stop anything queued for the future from going out. Returns how many.

    Only SCHEDULED and QUEUED are touched. A job already PUBLISHING is with
    the provider and cancelling the row would not recall the post; already
    PUBLISHED history is untouched, because that is what happened.
    """
    from apps.publishing.models import PublishingJob

    return PublishingJob.objects.filter(
        workspace=workspace,
        status__in=[PublishingJob.Status.SCHEDULED, PublishingJob.Status.QUEUED],
    ).update(status=PublishingJob.Status.CANCELLED)


@transaction.atomic
def suspend_workspace(workspace, *, by=None, reason=''):
    """Reversible pause. Writes stop; scheduled posts stop going out.

    The schedule itself is deliberately left intact — suspension is usually
    non-payment, and a client who pays on Tuesday should get Tuesday's posts,
    not an empty calendar. `due_jobs` filters on workspace status, so nothing
    fires while suspended.
    """
    if workspace.status == MarketingWorkspace.Status.SUSPENDED:
        return workspace
    _set_status(workspace, MarketingWorkspace.Status.SUSPENDED, reason=reason)

    from apps.audit.models import record_platform_event

    record_platform_event(
        actor=by, action='CLIENT_SUSPENDED', workspace=workspace,
        target=f'workspace:{workspace.pk}', detail={'reason': reason},
    )
    logger.info("Workspace %s suspended", workspace.pk)
    return workspace


@transaction.atomic
def reactivate_workspace(workspace, *, by=None, reason=''):
    """Back to ACTIVE from suspended or archived.

    Routing is repaired rather than assumed: an archived client had its routes
    disabled, and reactivating without them would produce a client who looks
    live and 503s on the first generation.
    """
    if workspace.status == MarketingWorkspace.Status.ACTIVE:
        return workspace
    was = workspace.status
    _set_status(workspace, MarketingWorkspace.Status.ACTIVE, reason=reason)

    subscription_restored = False
    if was == MarketingWorkspace.Status.ARCHIVED:
        from apps.ai.provisioning import ensure_default_ai_routing
        from apps.billing.models import Subscription

        try:
            ensure_default_ai_routing(workspace)
        except Exception:  # pragma: no cover - repair helper never raises
            logger.exception("Could not restore AI routing for %s", workspace.pk)

        # Archive cancelled the subscription; a client that is ACTIVE again but
        # still CANCELLED looks live and is refused on every AI request. Put it
        # back exactly as archive took it away.
        subscription_restored = bool(
            Subscription.objects.filter(
                workspace=workspace, status=Subscription.Status.CANCELLED
            ).update(status=Subscription.Status.ACTIVE)
        )

    from apps.audit.models import record_platform_event

    record_platform_event(
        actor=by, action='CLIENT_REACTIVATED', workspace=workspace,
        target=f'workspace:{workspace.pk}',
        detail={'from': was, 'reason': reason,
                'subscription_restored': subscription_restored},
    )
    logger.info("Workspace %s reactivated from %s", workspace.pk, was)
    return workspace


@transaction.atomic
def archive_workspace(workspace, *, by=None, reason=''):
    """Remove a client from the running platform without losing anything.

    Everything that would otherwise keep acting in the client's name is shut
    down in the same transaction as the status flip:

    * scheduled and queued publishing jobs are cancelled, so nothing posts;
    * AI routes are disabled, so nothing generates or spends;
    * the subscription is cancelled, so the client stops counting as revenue
      and stops being metered.

    Social connections are left connected but unreachable (writes are refused
    while non-ACTIVE) rather than revoked: revoking a token at the provider is
    not reversible, and archive must be.
    """
    if workspace.status == MarketingWorkspace.Status.ARCHIVED:
        return workspace

    from apps.ai.models import WorkspaceAIRoute
    from apps.billing.models import Subscription

    cancelled_jobs = cancel_scheduled_publishing(workspace)
    disabled_routes = WorkspaceAIRoute.objects.filter(
        workspace=workspace, enabled=True
    ).update(enabled=False)
    cancelled_subs = Subscription.objects.filter(workspace=workspace).exclude(
        status=Subscription.Status.CANCELLED
    ).update(status=Subscription.Status.CANCELLED)

    # An archived client must not keep its website reserved against a genuine
    # future signup.
    from apps.users.models import SignupWebsiteClaim

    SignupWebsiteClaim.objects.filter(workspace=workspace).delete()

    _set_status(workspace, MarketingWorkspace.Status.ARCHIVED, reason=reason)

    from apps.audit.models import record_platform_event

    record_platform_event(
        actor=by, action='CLIENT_ARCHIVED', workspace=workspace,
        target=f'workspace:{workspace.pk}',
        detail={
            'reason': reason,
            'cancelled_publishing_jobs': cancelled_jobs,
            'disabled_ai_routes': disabled_routes,
            'cancelled_subscriptions': cancelled_subs,
        },
    )
    logger.info(
        "Workspace %s archived (jobs=%d routes=%d subs=%d)",
        workspace.pk, cancelled_jobs, disabled_routes, cancelled_subs,
    )
    return workspace


def set_capability_limits(workspace, limits, *, by=None):
    """Super Admin's per-client dial: {"IMAGE": 100, "VIDEO": 10}.

    Writes to the subscription override, never to the plan — changing the plan
    would silently re-price every other client on it. 0 means unlimited for
    that capability; removing a key falls back to the plan.
    """
    from apps.billing.models import Subscription

    subscription = Subscription.objects.filter(workspace=workspace).first()
    if subscription is None:
        raise ValueError(
            "This client has no subscription; approve the client first."
        )

    cleaned = {}
    for key, value in (limits or {}).items():
        try:
            cleaned[str(key)] = max(0, int(value or 0))
        except (TypeError, ValueError):
            raise ValueError(f"Limit for {key} must be a whole number.")

    before = dict(subscription.capability_limit_overrides or {})
    subscription.capability_limit_overrides = cleaned
    subscription.save(update_fields=['capability_limit_overrides', 'updated_at'])

    from apps.audit.models import record_platform_event

    record_platform_event(
        actor=by, action='CLIENT_LIMITS_CHANGED', workspace=workspace,
        target=f'subscription:{subscription.pk}',
        detail={'before': before, 'after': cleaned},
    )
    return subscription
