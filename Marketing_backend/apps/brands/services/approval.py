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


PENDING_MESSAGE = (
    "This client is awaiting Scaleezy approval. AI generation, calibration "
    "and analysis unlock once it has been approved."
)


def spend_block(workspace):
    """Why this workspace may not spend on AI right now, or None if it may.

    Approval is the WORKSPACE's `approval_status`, set only by the approval
    service. It is deliberately not derived from brand rows: "any ACTIVE brand
    means approved" let a pending customer approve themselves by creating a
    second brand. The brand-based check below remains only as a stricter
    fallback for approved workspaces whose every brand is pending/archived.
    """
    from apps.workspaces.models import MarketingWorkspace

    # Rejection also archives the client, so the approval verdict is checked
    # first: "not approved" is the more useful answer than "archived".
    if workspace.approval_status == MarketingWorkspace.Approval.REJECTED:
        return SpendNotApproved(
            'CLIENT_REJECTED',
            "This client's signup was not approved; AI generation is unavailable.",
        )
    if workspace.approval_status == MarketingWorkspace.Approval.PENDING:
        return SpendNotApproved('CLIENT_NOT_APPROVED', PENDING_MESSAGE)
    if workspace.status == MarketingWorkspace.Status.ARCHIVED:
        return SpendNotApproved(
            'CLIENT_ARCHIVED', "This client is archived; AI generation is unavailable."
        )

    brands = Brand.objects.filter(workspace=workspace)
    if not brands.exists():
        return None
    if brands.filter(status=Brand.Status.ACTIVE).exists():
        return None
    if brands.filter(status=Brand.Status.PENDING).exists():
        return SpendNotApproved('CLIENT_NOT_APPROVED', PENDING_MESSAGE)
    return SpendNotApproved(
        'CLIENT_ARCHIVED', "This client is archived; AI generation is unavailable."
    )


def initial_brand_status(workspace):
    """What a brand created inside this workspace starts as.

    PENDING unless the client is approved — so a customer awaiting approval
    cannot mint an ACTIVE brand for themselves, from any creation path.
    """
    from apps.workspaces.models import MarketingWorkspace

    if workspace.approval_status == MarketingWorkspace.Approval.APPROVED:
        return Brand.Status.ACTIVE
    return Brand.Status.PENDING


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
    from apps.workspaces.models import MarketingWorkspace

    # Approving a previously rejected (archived) client brings it back first,
    # so routes and the schedule are live when the approval lands.
    if brand.workspace.status == MarketingWorkspace.Status.ARCHIVED:
        from apps.workspaces.services.lifecycle import reactivate_workspace

        reactivate_workspace(brand.workspace, by=by, reason='Approved after rejection')

    subscription, _ = ensure_subscription(brand.workspace, plan=plan)

    if brand.status != Brand.Status.ACTIVE:
        brand.status = Brand.Status.ACTIVE
        brand.reviewed_at = timezone.now()
        brand.reviewed_by = by
        brand.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'updated_at'])

    # The client itself becomes approved — this is what the spend gate reads.
    workspace = brand.workspace
    if workspace.approval_status != MarketingWorkspace.Approval.APPROVED:
        workspace.approval_status = MarketingWorkspace.Approval.APPROVED
        workspace.save(update_fields=['approval_status', 'updated_at'])

    # A reactivated subscription, if rejection or archive had cancelled it.
    if subscription is not None and subscription.status != subscription.Status.ACTIVE:
        subscription.status = subscription.Status.ACTIVE
        subscription.save(update_fields=['status', 'updated_at'])

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
    from apps.users.models import SignupWebsiteClaim
    from apps.workspaces.models import MarketingWorkspace

    brand.status = Brand.Status.ARCHIVED
    brand.reviewed_at = timezone.now()
    brand.reviewed_by = by
    brand.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'updated_at'])

    # The client is no longer approved (it may never have been): no spend, and
    # no new ACTIVE brands. Reversible through approve_brand.
    workspace = brand.workspace
    if workspace.approval_status != MarketingWorkspace.Approval.REJECTED:
        workspace.approval_status = MarketingWorkspace.Approval.REJECTED
        workspace.save(update_fields=['approval_status', 'updated_at'])

    # A rejected signup frees its website for a genuine future enrolment.
    SignupWebsiteClaim.objects.filter(workspace=workspace).delete()

    # Rejection archives the CLIENT, not only the brand: an ACTIVE workspace
    # keeps its scheduled posts firing and its routes live. Archive stops all
    # of that, reversibly — approving later reactivates it.
    if workspace.status != MarketingWorkspace.Status.ARCHIVED:
        from apps.workspaces.services.lifecycle import archive_workspace

        archive_workspace(workspace, by=by, reason=f'Signup rejected: {reason}'[:255])

    from apps.audit.models import record_platform_event

    record_platform_event(
        actor=by, action='BRAND_REJECTED', workspace=brand.workspace,
        target=f'brand:{brand.pk}',
        detail={'brand_name': brand.name, 'reason': reason},
    )
    return brand
