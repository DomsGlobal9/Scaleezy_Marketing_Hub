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

    def as_dict(self):
        return {
            'allowed': self.allowed,
            'code': self.code,
            'message': self.message,
            'generations_used': self.used,
            'generations_limit': self.limit,
            'spend': str(money(self.spend)),
            'spend_cap': str(money(self.spend_cap)),
        }


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


def check(workspace) -> Verdict:
    """Whether this workspace may start another generation."""
    subscription = subscription_for(workspace)
    if subscription is None:
        return Verdict(allowed=True, code='NO_SUBSCRIPTION')

    if not subscription.is_active:
        return Verdict(
            allowed=False,
            code='SUBSCRIPTION_INACTIVE',
            message=f"This workspace's subscription is {subscription.get_status_display().lower()}.",
        )

    generations, spend = usage(workspace, subscription)
    limit = subscription.generation_limit
    cap = money(subscription.spend_cap)

    if limit and generations >= limit:
        return Verdict(
            allowed=False,
            code='GENERATION_QUOTA_EXCEEDED',
            message=(
                f"This workspace has used all {limit} generations in the current "
                f"period."
            ),
            used=generations, limit=limit, spend=spend, spend_cap=cap,
        )

    if cap and spend >= cap:
        return Verdict(
            allowed=False,
            code='SPEND_CAP_REACHED',
            message=f"This workspace has reached its spend cap of {cap} for the period.",
            used=generations, limit=limit, spend=spend, spend_cap=cap,
        )

    return Verdict(
        allowed=True, used=generations, limit=limit, spend=spend, spend_cap=cap
    )


def enforce(workspace):
    """`check`, but raises QuotaExceeded so a caller can let it propagate."""
    verdict = check(workspace)
    if not verdict.allowed:
        logger.info(
            "Quota block: workspace=%s code=%s", getattr(workspace, 'pk', None), verdict.code
        )
        raise QuotaExceeded(verdict)
    return verdict


def summary(workspace):
    """The whole picture, for the settings screen."""
    subscription = subscription_for(workspace)
    verdict = check(workspace)

    if subscription is None:
        return {
            'subscribed': False,
            'plan': None,
            **verdict.as_dict(),
        }

    start, end = subscription.current_period()
    generations, spend = usage(workspace, subscription)
    limit = subscription.generation_limit
    cap = money(subscription.spend_cap)

    return {
        'subscribed': True,
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


def default_plan():
    return Plan.objects.filter(key=DEFAULT_PLAN_KEY).first() or Plan.objects.filter(
        is_default=True
    ).first()
