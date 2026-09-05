"""
Quota and spend checks.

Counted, never accumulated: generations come from ContentItem rows and spend
from AIUsageLog, both of which are written anyway. A stored counter would be
one bug away from letting a workspace generate forever, or from locking one
out that had done nothing.

A workspace with no subscription is *not* blocked. Every existing workspace
predates this table, and a billing table appearing in a deploy must not stop
people working. `DEFAULT_PLAN_KEY` covers them if a default plan exists;
otherwise they are unlimited and Phase 8 is opt-in per customer.
"""
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .models import Plan, Subscription

logger = logging.getLogger(__name__)

DEFAULT_PLAN_KEY = 'free'

#: How a per-capability ceiling is described to a human. "You have used all
#: 100 IMAGE" is not a sentence anybody outside this codebase should read.
CAPABILITY_LABELS = {
    'TEXT': 'copy generations',
    'IMAGE': 'poster generations',
    'VIDEO': 'video generations',
    'IMAGE_ANALYSIS': 'image analyses',
    'IMAGE_CAPTION': 'caption generations',
    'VIDEO_ANALYSIS': 'video analyses',
    'EMBEDDING': 'embeddings',
}

#: Money crosses the API as a string, and `str(Decimal)` keeps whatever scale
#: the database happened to return — "1.5" on SQLite, "1.5000" on Postgres.
#: Everything monetary is quantised so the wire format does not depend on the
#: backend.
CENTS = Decimal('0.01')


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Verdict:
    """The answer to "may this workspace generate right now?"."""

    allowed: bool
    code: str = ''
    message: str = ''
    used: int = 0
    limit: int = 0
    spend: Decimal = Decimal('0.00')
    spend_cap: Decimal = Decimal('0.00')
    #: Set only when a per-capability ceiling is what blocked (or was checked).
    capability: str = ''
    capability_used: int = 0
    capability_limit: int = 0

    def as_dict(self):
        payload = {
            'allowed': self.allowed,
            'code': self.code,
            'message': self.message,
            'generations_used': self.used,
            'generations_limit': self.limit,
            'spend': str(money(self.spend)),
            'spend_cap': str(money(self.spend_cap)),
        }
        if self.capability:
            payload.update({
                'capability': self.capability,
                'capability_used': self.capability_used,
                'capability_limit': self.capability_limit,
            })
        return payload


class QuotaExceeded(Exception):
    """Raised by `enforce` when the workspace is out of allowance."""

    def __init__(self, verdict: Verdict):
        super().__init__(verdict.message)
        self.verdict = verdict


def subscription_for(workspace):
    """
    The workspace's subscription, or None.

    Never creates one implicitly — an unsubscribed workspace is unlimited, and
    silently enrolling it would be a billing decision made by a quota check.
    """
    return Subscription.objects.select_related('plan').filter(workspace=workspace).first()


def usage(workspace, subscription=None):
    """(generations, spend) for the current period."""
    from apps.ai.models import AIUsageLog
    from apps.content.models import ContentItem
    from django.db.models import Sum

    subscription = subscription or subscription_for(workspace)
    if subscription is None:
        return 0, Decimal('0')

    start, end = subscription.current_period()

    generations = ContentItem.objects.filter(
        workspace=workspace, created_at__gte=start, created_at__lt=end
    ).count()

    spend = AIUsageLog.objects.filter(
        workspace=workspace, created_at__gte=start, created_at__lt=end
    ).aggregate(total=Sum('cost'))['total'] or Decimal('0')

    return generations, money(spend)


def capability_usage(workspace, subscription=None, capability=None):
    """How many billable calls this workspace made per capability this period.

    Counted from AIUsageLog, like spend — never accumulated in a column, for
    the reason at the top of this module.

    `success=True, selected=True` is the definition of a billable unit: a
    provider that failed produced nothing to charge for, and a BEST_OF loser
    is spend, not a unit. Platform QA dispatches (the copy judge, the focus
    vision call — rows flagged is_internal) DO count as customer units:
    founder decision, 2026-09-03 ("option b") — every call a generation
    causes is part of that generation's price in units as well as money.
    The is_internal flag stays on the rows purely for reporting, so "how
    much of a client's usage is QA" remains answerable.
    """
    from apps.ai.models import AIUsageLog
    from django.db.models import Sum

    subscription = subscription or subscription_for(workspace)
    if subscription is None:
        return {}

    start, end = subscription.current_period()
    rows = AIUsageLog.objects.filter(
        workspace=workspace, created_at__gte=start, created_at__lt=end,
        success=True, selected=True,
    )
    if capability is not None:
        rows = rows.filter(capability=capability)
    return {
        # Sum of units, not a row count: an Ultra (4K) poster's image call is
        # worth 2 units — the founder's pricing (2026-09-05).
        row['capability']: row['n']
        for row in rows.values('capability').annotate(n=Sum('units'))
    }


def _base_verdict(subscription, generations=0, spend=Decimal('0')) -> Verdict:
    """The workspace-wide verdict from already-counted period usage.

    Keeping this arithmetic separate from the queries lets bulk operator read
    models use the exact billing verdict without re-querying every tenant.
    """
    if subscription is None:
        return Verdict(allowed=True, code='NO_SUBSCRIPTION')

    if not subscription.is_active:
        return Verdict(
            allowed=False,
            code='SUBSCRIPTION_INACTIVE',
            message=(
                f"This workspace's subscription is "
                f"{subscription.get_status_display().lower()}."
            ),
        )

    limit = subscription.generation_limit
    cap = money(subscription.spend_cap)
    if limit and generations >= limit:
        return Verdict(
            allowed=False,
            code='GENERATION_QUOTA_EXCEEDED',
            message=(
                f'This workspace has used all {limit} generations in the current '
                'period.'
            ),
            used=generations, limit=limit, spend=spend, spend_cap=cap,
        )
    if cap and spend >= cap:
        return Verdict(
            allowed=False,
            code='SPEND_CAP_REACHED',
            message=f'This workspace has reached its spend cap of {cap} for the period.',
            used=generations, limit=limit, spend=spend, spend_cap=cap,
        )
    return Verdict(
        allowed=True, used=generations, limit=limit, spend=spend, spend_cap=cap,
    )


def check(workspace, capability=None) -> Verdict:
    """Whether this workspace may start another generation.

    `capability` is the unit the caller is about to spend on (see
    apps.ai.models.Capability). Supplying it applies that capability's own
    ceiling in addition to the overall generation limit and the spend cap —
    which is how "100 posters for this client, 10 videos for that one" is
    enforced. Omitting it checks only the workspace-wide limits.
    """
    subscription = subscription_for(workspace)
    if subscription is None or not subscription.is_active:
        return _base_verdict(subscription)

    generations, spend = usage(workspace, subscription)
    verdict = _base_verdict(subscription, generations, spend)
    if not verdict.allowed:
        return verdict

    limit = subscription.generation_limit
    cap = money(subscription.spend_cap)

    capability_used = 0
    capability_limit = 0
    if capability:
        capability_limit = subscription.limit_for(capability)
        if capability_limit:
            capability_used = capability_usage(
                workspace, subscription, capability
            ).get(capability, 0)
            if capability_used >= capability_limit:
                return Verdict(
                    allowed=False,
                    code='CAPABILITY_QUOTA_EXCEEDED',
                    message=(
                        f"This workspace has used all {capability_limit} "
                        f"{CAPABILITY_LABELS.get(capability, capability)} "
                        f"for the current period."
                    ),
                    used=generations, limit=limit, spend=spend, spend_cap=cap,
                    capability=capability, capability_used=capability_used,
                    capability_limit=capability_limit,
                )

    return Verdict(
        allowed=True, used=generations, limit=limit, spend=spend, spend_cap=cap,
        capability=capability or '', capability_used=capability_used,
        capability_limit=capability_limit,
    )


def enforce(workspace, capability=None):
    """`check`, but raises QuotaExceeded so a caller can let it propagate."""
    verdict = check(workspace, capability=capability)
    if not verdict.allowed:
        logger.info(
            "Quota block: workspace=%s capability=%s code=%s",
            getattr(workspace, 'pk', None), capability or '-', verdict.code,
        )
        raise QuotaExceeded(verdict)
    return verdict


def summary_from_aggregates(
    subscription, *, generations=0, spend=Decimal('0'), per_capability_used=None
):
    """Shape the public summary from an authoritative, already-counted period.

    This is the single formatting and verdict owner for both the normal
    one-workspace settings read and the platform operator's bulk portfolio.
    """
    spend = money(spend)
    verdict = _base_verdict(subscription, generations, spend)
    if subscription is None:
        return {
            'subscribed': False,
            'plan': None,
            **verdict.as_dict(),
        }

    start, end = subscription.current_period()
    limit = subscription.generation_limit
    cap = money(subscription.spend_cap)

    per_capability_used = per_capability_used or {}
    capabilities = []
    for capability, capability_limit in sorted(subscription.all_capability_limits().items()):
        used_here = per_capability_used.get(capability, 0)
        capabilities.append({
            'capability': capability,
            'label': CAPABILITY_LABELS.get(capability, capability),
            'used': used_here,
            'limit': capability_limit,
            'remaining': max(0, capability_limit - used_here) if capability_limit else None,
            'overridden': capability in (subscription.capability_limit_overrides or {}),
        })

    return {
        'subscribed': True,
        'capabilities': capabilities,
        'plan': {
            'key': subscription.plan.key,
            'name': subscription.plan.name,
            'description': subscription.plan.description,
            'price': str(subscription.plan.price),
        },
        'status': subscription.status,
        'period_start': start.isoformat(),
        'period_end': end.isoformat(),
        'generations_used': generations,
        'generations_limit': limit,
        'generations_remaining': max(0, limit - generations) if limit else None,
        'spend': str(money(spend)),
        'spend_cap': str(cap),
        'spend_remaining': str(money(max(Decimal('0'), cap - spend))) if cap else None,
        'allowed': verdict.allowed,
        'code': verdict.code,
        'message': verdict.message,
    }


def summary(workspace):
    """The whole picture, for the settings screen."""
    subscription = subscription_for(workspace)
    if subscription is None:
        return summary_from_aggregates(None)

    generations, spend = usage(workspace, subscription)
    return summary_from_aggregates(
        subscription,
        generations=generations,
        spend=spend,
        per_capability_used=capability_usage(workspace, subscription),
    )


def default_plan():
    return Plan.objects.filter(key=DEFAULT_PLAN_KEY).first() or Plan.objects.filter(
        is_default=True
    ).first()
