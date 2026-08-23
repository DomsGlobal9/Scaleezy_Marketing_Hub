"""
Signup approval.

A brand that arrived through public signup is PENDING until a Scaleezy
operator approves it. Approve and reject live here rather than in a view so
that the Django admin action today and the platform console later run the
same code and record the same columns.

Reject archives. Archive, never destroy: the decision is reversible, and the
brand's knowledge, inspirations, learning and audit rows stay exactly where
they are.
"""
from django.db import transaction
from django.utils import timezone

from apps.common.responses import APIResponse

from ..models import Brand


class SpendNotApproved(Exception):
    """The client may not incur provider spend until Scaleezy has approved it.

    Shaped like billing.quota.QuotaExceeded so callers can treat "not allowed
    to spend" uniformly: `.code` for the envelope, `.message` for the human.
    """

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def spend_block(workspace):
    """Why this workspace may not spend on AI right now, or None if it may.

    A client is approved when at least one of its brands is ACTIVE. A
    workspace with no brand row at all predates approval and is not blocked —
    a table appearing in a deploy must not stop existing people working.
    """
    brands = Brand.objects.filter(workspace=workspace)
    if not brands.exists():
        return None
    if brands.filter(status=Brand.Status.ACTIVE).exists():
        return None
    if brands.filter(status=Brand.Status.PENDING).exists():
        return SpendNotApproved(
            'CLIENT_NOT_APPROVED',
            "This client is awaiting Scaleezy approval. AI generation, calibration "
            "and analysis unlock once it has been approved.",
        )
    return SpendNotApproved(
        'CLIENT_ARCHIVED',
        "This client is archived; AI generation is unavailable.",
    )


def enforce_spend_approved(workspace):
    """`spend_block`, but raises, so the AI router and services can refuse."""
    block = spend_block(workspace)
    if block is not None:
        raise block


def approval_gate_response(workspace):
    """The 403 envelope a user-facing endpoint returns when spend is blocked,
    or None to proceed. Mirrors the quota check in the same endpoints."""
    block = spend_block(workspace)
    if block is None:
        return None
    return APIResponse(
        success=False,
        message=block.message,
        error={'code': block.code, 'message': block.message},
        status=403,
    )


def ensure_subscription(workspace, *, plan=None):
    """Every approved client is on a plan. Returns (subscription, created).

    Without this, approval only flips a status: `quota.check()` treats a
    workspace with no subscription as unlimited, so an approved client would
    generate forever for free. Approval is the moment entitlement begins, so
    it is the moment the subscription row appears.

    Never changes an existing subscription — re-approving a client must not
    silently move them off the plan they negotiated.
    """
    from apps.billing.models import Subscription
    from apps.billing.quota import default_plan

    existing = Subscription.objects.filter(workspace=workspace).first()
    if existing is not None:
        return existing, False

    chosen = plan or default_plan()
    if chosen is None:
        # No catalogue yet. Report it rather than inventing a plan: an
        # entitlement guessed by code is one nobody agreed to.
        return None, False
    return Subscription.objects.create(workspace=workspace, plan=chosen), True


@transaction.atomic
def approve_brand(brand, *, by=None, plan=None):
    """PENDING -> ACTIVE, and the client becomes entitled.

    One transaction: the brand goes live and the subscription that meters it
    exists together, or neither does. Approving an already-active brand still
    ensures the subscription, because brands approved before this existed have
    none.
    """
    subscription, _ = ensure_subscription(brand.workspace, plan=plan)

    if brand.status != Brand.Status.ACTIVE:
        brand.status = Brand.Status.ACTIVE
        brand.reviewed_at = timezone.now()
        brand.reviewed_by = by
        brand.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'updated_at'])

    from apps.audit.models import record_platform_event

    record_platform_event(
        actor=by, action='BRAND_APPROVED', workspace=brand.workspace,
        target=f'brand:{brand.pk}',
        detail={'brand_name': brand.name,
                'subscription': str(subscription.pk) if subscription else None},
    )
    return brand


@transaction.atomic
def reject_brand(brand, *, by=None, reason=''):
    """-> ARCHIVED, reversibly. Archiving an archived brand changes nothing."""
    if brand.status == Brand.Status.ARCHIVED:
        return brand
    brand.status = Brand.Status.ARCHIVED
    brand.reviewed_at = timezone.now()
    brand.reviewed_by = by
    brand.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'updated_at'])

    from apps.audit.models import record_platform_event

    record_platform_event(
        actor=by, action='BRAND_REJECTED', workspace=brand.workspace,
        target=f'brand:{brand.pk}',
        detail={'brand_name': brand.name, 'reason': reason},
    )
    return brand
