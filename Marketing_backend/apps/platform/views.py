"""
Super Admin console — the HTTP surface over services that already exist.

Two slices are implemented here as the pattern for the rest:

* P5 `GET  /api/platform/health/`        — `platform_health()` verbatim.
* P1 `GET  /api/platform/signups/`       — the approval queue.
     `POST /api/platform/signups/{brand}/approve/` | `/reject/`
     `POST /api/platform/clients/{ws}/attach-user/`

Every view: `permission_classes = [IsAuthenticated, IsPlatformAdmin]`, reads
from real queries, and ends with `record_platform_event`. Copy this shape for
P2–P7; do not add a cross-tenant mode to the tenant permission classes.
"""
import logging

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.audit.models import record_platform_event
from apps.brands.models import Brand
from apps.brands.services.approval import approve_brand, reject_brand
from apps.common.platform_health import platform_health
from apps.common.responses import APIResponse
from apps.inspirations.models import BrandInspiration
from apps.knowledge.models import BrandSource
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember
from apps.workspaces.services.team import TeamError, attach_user_to_workspace

from .permissions import IsPlatformAdmin

logger = logging.getLogger(__name__)
User = get_user_model()


class PlatformView(APIView):
    """Base for every console endpoint. The gate lives here, once."""

    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def audit(self, action, *, workspace=None, target='', detail=None):
        record_platform_event(
            actor=self.request.user, action=action, workspace=workspace,
            target=target, detail=detail or {}, request=self.request,
        )

    @staticmethod
    def not_found(what):
        return APIResponse(
            success=False, message=f"{what} not found.",
            error={'code': 'NOT_FOUND', 'message': f"{what} not found."},
            status=status.HTTP_404_NOT_FOUND,
        )


# ───────────────────────────────────────────────────────── P5 — health

class PlatformHealthView(PlatformView):
    def get(self, request):
        payload = platform_health()
        # A read of platform state is still a platform action.
        self.audit('PLATFORM_HEALTH_VIEWED', detail={
            'needs_attention': payload['needs_attention'],
        })
        return APIResponse(success=True, data=payload)


# ───────────────────────────────────────────────────── P1 — approval queue

class QueueStats:
    """Per-brand figures for a page of queue rows, one query per table.

    `_signup_row` used to answer these with four queries per brand — owner,
    two content counts, team size — an N+1 that reached ~800 queries on a
    full 200-row page. Same numbers, grouped once per table, exactly as
    `PortfolioStats` does for the client portfolio.
    """

    def __init__(self, brands):
        brand_ids = [b.pk for b in brands]
        workspace_ids = [b.workspace_id for b in brands]

        # First OWNER by created_at per workspace — the signer-upper.
        self.owner = {}
        for member in (
            WorkspaceMember.objects.filter(
                workspace_id__in=workspace_ids, role=WorkspaceMember.Role.OWNER
            ).select_related('user').order_by('created_at')
        ):
            self.owner.setdefault(member.workspace_id, member.user.get_username())

        def grouped(queryset, key):
            return {
                row[key]: row['n']
                for row in queryset.order_by().values(key).annotate(n=Count('id'))
            }

        self.knowledge = grouped(
            BrandSource.objects.filter(brand_id__in=brand_ids), 'brand_id')
        self.inspirations = grouped(
            BrandInspiration.objects.filter(brand_id__in=brand_ids), 'brand_id')
        self.team = grouped(
            WorkspaceMember.objects.filter(workspace_id__in=workspace_ids),
            'workspace_id')


def _signup_row(brand, stats):
    """One queue row. Every count comes from `stats`, never a per-row query."""
    workspace = brand.workspace
    return {
        'brand_id': str(brand.pk),
        'workspace_id': str(workspace.pk),
        'client_code': workspace.client_code,
        'name': brand.name,
        'website': brand.website,
        'industry': brand.industry,
        'status': brand.status,
        'signed_up_at': brand.created_at.isoformat(),
        'signed_up_by': stats.owner.get(workspace.pk, ''),
        # What they built while pending — real counts, so the reviewer can see
        # a serious client from a drive-by.
        'knowledge_sources': stats.knowledge.get(brand.pk, 0),
        'inspirations': stats.inspirations.get(brand.pk, 0),
        'team_size': stats.team.get(workspace.pk, 0),
        'reviewed_at': brand.reviewed_at.isoformat() if brand.reviewed_at else None,
        'reviewed_by': brand.reviewed_by.get_username() if brand.reviewed_by_id else '',
    }


class SignupQueueView(PlatformView):
    """Pending clients, newest first. `?status=` to see ACTIVE/ARCHIVED too."""

    def get(self, request):
        pending_total = Brand.objects.filter(status=Brand.Status.PENDING).count()

        if request.query_params.get('count_only'):
            # The Overview tile needs one number, not two hundred built rows.
            self.audit('SIGNUP_QUEUE_VIEWED', detail={'count_only': True})
            return APIResponse(success=True, data={'pending_total': pending_total})

        wanted = str(request.query_params.get('status', Brand.Status.PENDING)).upper()
        if wanted not in Brand.Status.values:
            wanted = Brand.Status.PENDING
        brands = list(
            Brand.objects.filter(status=wanted)
            .select_related('workspace', 'reviewed_by')
            .order_by('-created_at')[:200]
        )
        stats = QueueStats(brands)
        rows = [_signup_row(b, stats) for b in brands]
        self.audit('SIGNUP_QUEUE_VIEWED', detail={'status': wanted, 'count': len(rows)})
        return APIResponse(success=True, data={
            'status': wanted,
            'count': len(rows),
            'pending_total': pending_total,
            'signups': rows,
        })


class SignupDecisionView(PlatformView):
    """POST .../signups/{brand_id}/approve/  or  .../reject/

    Approve accepts optional `name` / `website` corrections — the two fields a
    client can never change, so approval is the moment to fix them — and an
    optional `plan` key. Reject accepts `reason`.
    """

    def post(self, request, brand_id, decision):
        brand = Brand.objects.select_related('workspace').filter(pk=brand_id).first()
        if brand is None:
            return self.not_found("Brand")

        if decision == 'approve':
            # Validate everything first. Nothing about the customer changes
            # unless the whole approval goes through.
            plan = None
            plan_key = request.data.get('plan')
            if plan_key:
                from apps.billing.models import Plan

                plan = Plan.objects.filter(key=str(plan_key)).first()
                if plan is None:
                    return APIResponse(
                        success=False, message=f"No plan with key {plan_key!r}.",
                        error={'code': 'UNKNOWN_PLAN', 'message': 'Unknown plan.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            corrections = {}
            for field in ('name', 'website'):
                value = request.data.get(field)
                if isinstance(value, str) and value.strip() and value.strip() != getattr(brand, field):
                    corrections[field] = {'from': getattr(brand, field), 'to': value.strip()}

            from django.db import transaction

            from apps.users.models import SignupWebsiteClaim
            from apps.users.serializers import normalised_host

            corrected_host = ''
            if 'website' in corrections:
                corrected_host = normalised_host(corrections['website']['to'])
                if corrected_host:
                    # The corrected site must not already be another client's.
                    taken = SignupWebsiteClaim.objects.filter(
                        website_host=corrected_host
                    ).exclude(workspace=brand.workspace).select_related('workspace').first()
                    if taken is None:
                        other = next((
                            b for b in Brand.objects.exclude(workspace=brand.workspace)
                            .exclude(status=Brand.Status.ARCHIVED).exclude(website='')
                            .only('website', 'workspace_id')
                            if normalised_host(b.website) == corrected_host
                        ), None)
                        taken = other
                    if taken is not None:
                        return APIResponse(
                            success=False,
                            message=(
                                f"{corrected_host} already belongs to another client "
                                f"({taken.workspace.client_code}). Correct the website to "
                                "something else, or attach this person to that client."
                            ),
                            error={'code': 'WEBSITE_TAKEN', 'message': 'Website belongs to another client.'},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

            with transaction.atomic():
                if corrections:
                    for field, change in corrections.items():
                        setattr(brand, field, change['to'])
                    brand.save(update_fields=list(corrections) + ['updated_at'])
                    if 'website' in corrections:
                        # The enrolment claim follows the corrected website. We
                        # verified above that nobody else holds it; create, never
                        # silently adopt an existing row.
                        SignupWebsiteClaim.objects.filter(workspace=brand.workspace).delete()
                        if corrected_host:
                            SignupWebsiteClaim.objects.create(
                                website_host=corrected_host, workspace=brand.workspace
                            )
                approve_brand(brand, by=request.user, plan=plan)
                if corrections:
                    self.audit(
                        'BRAND_CORRECTED_AT_APPROVAL', workspace=brand.workspace,
                        target=f'brand:{brand.pk}', detail=corrections,
                    )
            fresh = Brand.objects.select_related('workspace', 'reviewed_by').get(pk=brand.pk)
            return APIResponse(
                success=True,
                message=f"{brand.name} approved.",
                data=_signup_row(fresh, QueueStats([fresh])),
            )

        if decision == 'reject':
            reject_brand(brand, by=request.user, reason=str(request.data.get('reason', ''))[:255])
            fresh = Brand.objects.select_related('workspace', 'reviewed_by').get(pk=brand.pk)
            return APIResponse(
                success=True,
                message=f"{brand.name} rejected and archived. Reversible.",
                data=_signup_row(fresh, QueueStats([fresh])),
            )

        return self.not_found("Decision")


class AttachUserView(PlatformView):
    """POST /api/platform/clients/{workspace_id}/attach-user/ {username, role?}

    The remedy for a colleague blocked by the duplicate-enrolment guard.
    """

    def post(self, request, workspace_id):
        workspace = MarketingWorkspace.objects.filter(pk=workspace_id).first()
        if workspace is None:
            return self.not_found("Client")

        username = str(request.data.get('username', '')).strip().lower()
        user = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).first()
        if not username or user is None:
            return self.not_found("User")

        role = str(request.data.get('role', WorkspaceMember.Role.EDITOR)).upper()
        try:
            membership, duplicate_candidates = attach_user_to_workspace(
                user, workspace, role=role, by=request.user,
            )
        except TeamError as exc:
            return APIResponse(
                success=False, message=str(exc),
                error={'code': 'ATTACH_REFUSED', 'message': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # attach_user_to_workspace audits itself. Nothing else was changed:
        # possible duplicate signups are listed for the operator to archive
        # deliberately, never archived on their behalf.
        return APIResponse(success=True, message=f"{user.get_username()} attached.", data={
            'membership_id': str(membership.pk),
            'role': membership.role,
            'status': membership.status,
            'duplicate_candidates': duplicate_candidates,
        })
