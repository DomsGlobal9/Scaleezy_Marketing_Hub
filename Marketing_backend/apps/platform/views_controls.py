"""
P4 master controls + P7 platform admins.

The dials Super Admin turns on one client — limits, lifecycle, plan, spend
cap, the universal layer, a brain recompile — plus the two platform-wide
switches: a provider kill switch and who holds platform authority at all.

Nothing here implements a rule. Every endpoint is a thin HTTP skin over a
service that already exists and already audits itself (`set_capability_limits`,
`suspend/reactivate/archive_workspace`, `set_client_universal`,
`grant/revoke_platform_admin`). The four actions that have no service of their
own — plan change, spend cap, recompile, provider availability — audit here,
so the console never writes a platform change the log cannot explain.

Same gate as every console view: `IsPlatformAdmin`, checked live. No
cross-tenant mode is added to the tenant permission classes.
"""
import logging
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status

from apps.ai.models import AIProvider
from apps.audit.models import PlatformAdmin
from apps.audit.services import (
    PlatformAdminError,
    grant_platform_admin,
    revoke_platform_admin,
)
from apps.billing import quota
from apps.billing.models import Plan, Subscription
from apps.brands.models import Brand
from apps.brands.services.approval import ensure_subscription
from apps.brands.services.brand_brain import rebuild_brand_brain_safely
from apps.common.responses import APIResponse
from apps.universal.services import (
    quality_settings_for,
    set_client_quality,
    set_client_universal,
)
from apps.workspaces.models import MarketingWorkspace
from apps.workspaces.services.lifecycle import (
    archive_workspace,
    reactivate_workspace,
    set_capability_limits,
    suspend_workspace,
)

from .views import PlatformView

logger = logging.getLogger(__name__)
User = get_user_model()


def _bad_request(message, code='INVALID'):
    return APIResponse(
        success=False, message=message,
        error={'code': code, 'message': message},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _as_bool(value):
    """JSON `true` and form `"true"` both mean yes; anything else is an error.

    `None` means "not supplied". A silent `bool("false") is True` would flip a
    client's universal layer the wrong way, so strings are parsed explicitly.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ('true', '1', 'yes', 'on'):
            return True
        if lowered in ('false', '0', 'no', 'off'):
            return False
    raise ValueError("Expected true or false.")


def _workspace_status(workspace):
    return {
        'workspace_id': str(workspace.pk),
        'client_code': workspace.client_code,
        'status': workspace.status,
        'status_reason': workspace.status_reason,
        'status_changed_at': (
            workspace.status_changed_at.isoformat() if workspace.status_changed_at else None
        ),
    }


class ClientControlView(PlatformView):
    """Every master control addresses one client by workspace id."""

    @staticmethod
    def load_workspace(workspace_id):
        return MarketingWorkspace.objects.filter(pk=workspace_id).first()


# ───────────────────────────────────────────────────────── P4 — limits

class ClientLimitsView(ClientControlView):
    """POST /api/platform/clients/{ws}/limits/  {limits: {"IMAGE": 100, "VIDEO": 10}}

    Writes the per-client override, never the plan. The response is the same
    `quota.summary` the client's own settings screen reads, so the operator
    sees exactly what the client will see.
    """

    def post(self, request, workspace_id):
        workspace = self.load_workspace(workspace_id)
        if workspace is None:
            return self.not_found("Client")

        limits = request.data.get('limits')
        if not isinstance(limits, dict):
            return _bad_request(
                'Send {"limits": {"IMAGE": 100, "VIDEO": 10}}.', code='INVALID_LIMITS'
            )
        try:
            set_capability_limits(workspace, limits, by=request.user)
        except ValueError as exc:
            return _bad_request(str(exc), code='LIMITS_REFUSED')
        # set_capability_limits audits itself (CLIENT_LIMITS_CHANGED).
        return APIResponse(
            success=True, message="Limits updated.",
            data={'usage': quota.summary(workspace)},
        )


# ──────────────────────────────────────────────────────── P4 — lifecycle

class ClientLifecycleView(ClientControlView):
    """POST .../suspend/ | .../reactivate/ | .../archive/   {reason}

    One view, three routes: the transition is fixed per URL rather than read
    from the body, so a request can never be replayed as a different one.
    """

    TRANSITIONS = {
        'suspend': suspend_workspace,
        'reactivate': reactivate_workspace,
        'archive': archive_workspace,
    }
    transition = None

    def post(self, request, workspace_id):
        apply = self.TRANSITIONS.get(self.transition)
        if apply is None:
            return self.not_found("Transition")
        workspace = self.load_workspace(workspace_id)
        if workspace is None:
            return self.not_found("Client")

        reason = str(request.data.get('reason', '') or '')[:255]
        # Each lifecycle service audits itself (CLIENT_SUSPENDED / _REACTIVATED / _ARCHIVED).
        apply(workspace, by=request.user, reason=reason)
        workspace.refresh_from_db()
        return APIResponse(
            success=True,
            message=f"{workspace.client_code} is now {workspace.get_status_display().lower()}.",
            data=_workspace_status(workspace),
        )


# ──────────────────────────────────────────────────────── P4 — universal

class ClientUniversalView(ClientControlView):
    """POST .../universal/  {standards?: bool, inspirations?: bool}"""

    def post(self, request, workspace_id):
        workspace = self.load_workspace(workspace_id)
        if workspace is None:
            return self.not_found("Client")

        try:
            standards = _as_bool(request.data.get('standards'))
            inspirations = _as_bool(request.data.get('inspirations'))
        except ValueError:
            return _bad_request(
                "standards and inspirations must be true or false.", code='INVALID_TOGGLE'
            )
        if standards is None and inspirations is None:
            return _bad_request(
                "Send at least one of standards / inspirations.", code='NOTHING_TO_CHANGE'
            )

        # set_client_universal audits itself (CLIENT_UNIVERSAL_TOGGLED).
        row = set_client_universal(
            workspace, standards=standards, inspirations=inspirations, by=request.user,
        )
        return APIResponse(success=True, message="Universal layer updated.", data={
            'standards_enabled': row.standards_enabled,
            'inspirations_enabled': row.inspirations_enabled,
        })


# ───────────────────────────────────────────────────────── P4 — quality

def _quality_flags(row):
    return {
        'critique_enabled': row.critique_enabled,
        'focus_crop_enabled': row.focus_crop_enabled,
        'variety_enabled': row.variety_enabled,
        'image_text_check_enabled': row.image_text_check_enabled,
    }


class ClientQualityView(ClientControlView):
    """GET .../quality/ — the four switches, defaults when no row exists.
    POST .../quality/  {critique?: bool, focus_crop?: bool, variety?: bool,
                        image_text_check?: bool}
    """

    def get(self, request, workspace_id):
        workspace = self.load_workspace(workspace_id)
        if workspace is None:
            return self.not_found("Client")
        # Read-only and unaudited: the visit is already recorded as
        # CLIENT_VIEWED by the detail view this panel sits on.
        return APIResponse(
            success=True, data=_quality_flags(quality_settings_for(workspace)),
        )

    def post(self, request, workspace_id):
        workspace = self.load_workspace(workspace_id)
        if workspace is None:
            return self.not_found("Client")

        try:
            critique = _as_bool(request.data.get('critique'))
            focus_crop = _as_bool(request.data.get('focus_crop'))
            variety = _as_bool(request.data.get('variety'))
            image_text_check = _as_bool(request.data.get('image_text_check'))
        except ValueError:
            return _bad_request(
                "critique, focus_crop, variety and image_text_check must be true or false.",
                code='INVALID_TOGGLE',
            )
        if (
            critique is None and focus_crop is None and variety is None
            and image_text_check is None
        ):
            return _bad_request(
                "Send at least one of critique / focus_crop / variety / image_text_check.",
                code='NOTHING_TO_CHANGE',
            )

        # set_client_quality audits itself (CLIENT_QUALITY_TOGGLED).
        row = set_client_quality(
            workspace, critique_enabled=critique, focus_crop_enabled=focus_crop,
            variety_enabled=variety, image_text_check_enabled=image_text_check,
            by=request.user,
        )
        return APIResponse(
            success=True, message="Quality engine updated.", data=_quality_flags(row),
        )


# ───────────────────────────────────────────────────────────── P4 — plan

class ClientPlanView(ClientControlView):
    """POST .../plan/  {plan: key}

    Moves the client's subscription to another catalogue plan, creating the
    subscription if the client never had one. Overrides are left alone: a
    negotiated per-client limit survives a plan change on purpose.
    """

    def post(self, request, workspace_id):
        workspace = self.load_workspace(workspace_id)
        if workspace is None:
            return self.not_found("Client")

        plan_key = str(request.data.get('plan', '') or '').strip()
        plan = Plan.objects.filter(key=plan_key).first() if plan_key else None
        if plan is None:
            return _bad_request(f"No plan with key {plan_key!r}.", code='UNKNOWN_PLAN')

        subscription, created = ensure_subscription(workspace, plan=plan)
        previous = None if created else subscription.plan.key
        if not created and subscription.plan_id != plan.pk:
            subscription.plan = plan
            subscription.save(update_fields=['plan', 'updated_at'])

        self.audit(
            'CLIENT_PLAN_CHANGED', workspace=workspace,
            target=f'subscription:{subscription.pk}',
            detail={'from': previous, 'to': plan.key, 'created_subscription': created},
        )
        return APIResponse(
            success=True, message=f"{workspace.client_code} is on {plan.name}.",
            data={
                'plan': {'key': plan.key, 'name': plan.name},
                'subscription_status': subscription.status,
            },
        )


# ──────────────────────────────────────────────────────── P4 — spend cap

class ClientSpendCapView(ClientControlView):
    """POST .../spend-cap/  {spend_cap: "25.00" | null}

    Null clears the override so the plan's cap applies again; "0" is an
    explicit "uncapped" for this client (same convention as the plan column).
    """

    def post(self, request, workspace_id):
        workspace = self.load_workspace(workspace_id)
        if workspace is None:
            return self.not_found("Client")

        subscription = Subscription.objects.filter(workspace=workspace).first()
        if subscription is None:
            return _bad_request(
                "This client has no subscription; approve the client first.",
                code='NO_SUBSCRIPTION',
            )

        raw = request.data.get('spend_cap', None)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            new_cap = None
        else:
            try:
                new_cap = quota.money(Decimal(str(raw).strip()))
            except (InvalidOperation, ValueError, TypeError):
                return _bad_request(
                    "spend_cap must be a decimal amount like \"25.00\", or null.",
                    code='INVALID_SPEND_CAP',
                )
            if new_cap < 0:
                return _bad_request("spend_cap cannot be negative.", code='INVALID_SPEND_CAP')

        before = subscription.spend_cap_override
        subscription.spend_cap_override = new_cap
        subscription.save(update_fields=['spend_cap_override', 'updated_at'])

        self.audit(
            'CLIENT_SPEND_CAP_CHANGED', workspace=workspace,
            target=f'subscription:{subscription.pk}',
            detail={
                'from': str(quota.money(before)) if before is not None else None,
                'to': str(new_cap) if new_cap is not None else None,
            },
        )
        return APIResponse(
            success=True, message="Spend cap updated.", data=quota.summary(workspace),
        )


# ─────────────────────────────────────────────────── P4 — recompile brain

class ClientRecompileBrainView(ClientControlView):
    """POST .../recompile-brain/

    Rebuilds the Brand Brain for every live brand on the client. Uses the
    "safely" variant so one brand's compile failure is recorded on that brand
    and the rest still recompile; the response says which is which.
    """

    def post(self, request, workspace_id):
        workspace = self.load_workspace(workspace_id)
        if workspace is None:
            return self.not_found("Client")

        brands = Brand.objects.filter(workspace=workspace).exclude(
            status=Brand.Status.ARCHIVED
        ).order_by('created_at')

        rows = []
        for brand in brands:
            rebuild_brand_brain_safely(brand)
            # The failure path writes via queryset.update(), so re-read.
            brand.refresh_from_db(fields=[
                'brain_compiled_at', 'brain_version', 'brain_last_error', 'brain_failed_at',
            ])
            rows.append({
                'brand_id': str(brand.pk),
                'name': brand.name,
                'compiled_at': brand.brain_compiled_at.isoformat() if brand.brain_compiled_at else None,
                'version': brand.brain_version,
                'last_error': brand.brain_last_error,
                'failed': bool(brand.brain_last_error),
            })

        failed = [r['brand_id'] for r in rows if r['failed']]
        self.audit(
            'BRAND_BRAIN_RECOMPILED', workspace=workspace,
            target=f'workspace:{workspace.pk}',
            detail={
                'brands': [r['brand_id'] for r in rows],
                'failed': failed,
            },
        )
        message = (
            f"Recompiled {len(rows) - len(failed)} of {len(rows)} brand brain(s)."
            if rows else "This client has no live brands to recompile."
        )
        return APIResponse(success=True, message=message, data=rows)


# ───────────────────────────────────────────── P4 — provider kill switch

class ProviderAvailabilityView(PlatformView):
    """POST /api/platform/providers/{provider_id}/availability/  {is_available: bool}

    The global kill switch: flips `AIProvider.is_available`, which the router
    already honours for every workspace at once. Nothing else about routing or
    credentials is touched here.
    """

    def post(self, request, provider_id):
        provider = AIProvider.objects.filter(pk=provider_id).first()
        if provider is None:
            return self.not_found("Provider")

        try:
            wanted = _as_bool(request.data.get('is_available'))
        except ValueError:
            wanted = None
        if wanted is None:
            return _bad_request("is_available must be true or false.", code='INVALID_FLAG')

        was = provider.is_available
        if was != wanted:
            provider.is_available = wanted
            provider.save(update_fields=['is_available'])

        self.audit(
            'PROVIDER_AVAILABILITY_CHANGED', target=f'provider:{provider.pk}',
            detail={'provider_key': provider.key, 'from': was, 'to': wanted},
        )
        return APIResponse(
            success=True,
            message=f"{provider.display_name} is now {'available' if wanted else 'disabled'} platform-wide.",
            data={'provider_key': provider.key, 'is_available': provider.is_available},
        )


class PlatformProviderListView(PlatformView):
    """Global catalogue availability only; never workspace credentials/config."""

    def get(self, request):
        from .pagination import page_rows

        queryset = AIProvider.objects.filter(owner_workspace__isnull=True)
        search = str(request.query_params.get('q', '')).strip()[:200]
        if search:
            queryset = queryset.filter(Q(display_name__icontains=search) | Q(key__icontains=search))
        providers, pagination = page_rows(request, queryset.order_by('display_name', 'pk'))
        self.audit('PLATFORM_PROVIDER_AVAILABILITY_VIEWED', detail={'count': len(providers)})
        return APIResponse(success=True, data={
            'providers': [{
                'id': str(provider.pk), 'key': provider.key,
                'display_name': provider.display_name, 'is_available': provider.is_available,
            } for provider in providers],
            **pagination,
        })


# ─────────────────────────────────────────────────── P7 — platform admins

def _admin_row(grant):
    return {
        'user_id': grant.user_id,
        'username': grant.user.get_username(),
        'email': grant.user.email,
        'is_active': grant.is_active,
        'note': grant.note,
        'granted_at': grant.granted_at.isoformat() if grant.granted_at else None,
        'granted_by': grant.granted_by.get_username() if grant.granted_by_id else '',
        'revoked_at': grant.revoked_at.isoformat() if grant.revoked_at else None,
        'revoked_by': grant.revoked_by.get_username() if grant.revoked_by_id else '',
    }


def _admin_queryset():
    return PlatformAdmin.objects.select_related('user', 'granted_by', 'revoked_by')


class PlatformAdminsView(PlatformView):
    """GET  /api/platform/admins/              — every grant row, active first.
    POST /api/platform/admins/  {username, note}  — grant.

    Revoked rows stay in the list on purpose: who held this and when is the
    history the table exists to keep.
    """

    def get(self, request):
        grants = list(_admin_queryset().order_by('-is_active', '-granted_at'))
        rows = [_admin_row(g) for g in grants]
        self.audit('PLATFORM_ADMINS_VIEWED', detail={
            'count': len(rows),
            'active': sum(1 for r in rows if r['is_active']),
        })
        return APIResponse(success=True, data={'admins': rows})

    def post(self, request):
        username = str(request.data.get('username', '') or '').strip()
        user = None
        if username:
            user = User.objects.filter(
                Q(username__iexact=username) | Q(email__iexact=username)
            ).first()
        if user is None:
            return self.not_found("User")

        note = str(request.data.get('note', '') or '')[:255]
        # grant_platform_admin audits itself (PLATFORM_ADMIN_GRANTED).
        grant, created = grant_platform_admin(
            user, by=request.user, note=note, request=request,
        )
        grant = _admin_queryset().get(pk=grant.pk)
        return APIResponse(
            success=True,
            message=(
                f"{user.get_username()} now holds platform authority."
                if created else f"{user.get_username()} already holds platform authority."
            ),
            data=_admin_row(grant),
        )


class PlatformAdminRevokeView(PlatformView):
    """POST /api/platform/admins/{user_id}/revoke/

    The service refuses to remove the last active admin; that refusal is the
    400 here, with its message passed through.
    """

    def post(self, request, user_id):
        grant = _admin_queryset().filter(user_id=user_id).first()
        if grant is None:
            return self.not_found("Platform admin")

        try:
            # revoke_platform_admin audits itself (PLATFORM_ADMIN_REVOKED).
            revoke_platform_admin(grant.user, by=request.user, request=request)
        except PlatformAdminError as exc:
            return _bad_request(str(exc), code='LAST_ADMIN')

        grant = _admin_queryset().get(pk=grant.pk)
        return APIResponse(
            success=True,
            message=f"{grant.user.get_username()} no longer holds platform authority.",
            data=_admin_row(grant),
        )
