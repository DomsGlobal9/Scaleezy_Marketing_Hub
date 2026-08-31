"""
Super Admin console — P2 client portfolio and P3 client detail.

* P2 `GET /api/platform/clients/?filter=&days=&q=&limit=`  — every client as
  one row, each number a real query, with the flags an operator triages by.
* P3 `GET /api/platform/clients/{workspace}/`              — the same row plus
  the brain, onboarding, recent activity, team, audit and universal switches.

One function, `client_row`, builds the row for both endpoints so the portfolio
and the detail page can never disagree about a client. Everything that is a
count is aggregated per workspace in `PortfolioStats` — one grouped query per
table for the whole page rather than one query per row — and everything that
already has a service (quota, readiness, onboarding stage, approval) is read
through that service, never re-derived here.

The gate is `PlatformView` (IsAuthenticated + IsPlatformAdmin). Nothing in
this module touches the tenant permission classes: platform authority reads
across workspaces by being in its own namespace, not by loosening theirs.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Count, F, Max, Q
from django.utils import timezone

from apps.ai.models import AIUsageLog, WorkspaceAIRoute
from apps.audit.models import PlatformAuditLog
from apps.billing import quota
from apps.billing.models import Subscription
from apps.brands.models import Brand
from apps.brands.services.approval import spend_block
from apps.common.platform_health import DEFAULT_INACTIVE_DAYS
from apps.common.responses import APIResponse
from apps.content.models import ContentItem
from apps.context.services.readiness import brand_readiness
from apps.inspirations.models import BrandInspiration
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import (
    BrandPreference,
    BrandRule,
    LearningEvent,
    SubjectType,
)
from apps.onboarding.services import ensure_onboarding, refresh_stage
from apps.publishing.models import PublishingJob
from apps.universal.services import settings_for
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

from .views import PlatformView

#: The portfolio views. `all` is the default; the rest are flag subsets.
FILTERS = (
    'all', 'pending', 'at_risk', 'over_quota', 'never_generated', 'inactive',
    'failing_publishes', 'suspended', 'archived',
)

#: The flags that make a client "at risk": it is live but something that
#: should be moving is not. Mirrors the live signals on the health console so
#: "3 clients with no AI routing" there and `?filter=at_risk` here agree.
AT_RISK_FLAGS = ('INACTIVE', 'FAILING_PUBLISHES', 'NO_AI_ROUTING', 'BRAIN_STALE')

#: Which flag(s) each filter selects on. Evaluated against the row's own
#: `flags`, so a filtered list can never show a row that lacks the flag.
FILTER_FLAGS = {
    'pending': ('PENDING_APPROVAL',),
    'at_risk': AT_RISK_FLAGS,
    # Out of posters and out of money both mean "cannot generate"; the
    # operator looking for blocked clients wants both.
    'over_quota': ('OVER_QUOTA', 'SPEND_CAP_REACHED'),
    'never_generated': ('NEVER_GENERATED',),
    'inactive': ('INACTIVE',),
    'failing_publishes': ('FAILING_PUBLISHES',),
    'suspended': ('SUSPENDED',),
    'archived': ('ARCHIVED',),
}

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000


def _iso(moment):
    return moment.isoformat() if moment else None


def _int_param(raw, default, *, lo, hi):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


# ───────────────────────────────────────────────── grouped aggregates

class PortfolioStats:
    """Per-workspace aggregates for a page of clients, one query per table.

    The portfolio is up to `MAX_LIMIT` rows; counting content, publishing,
    team, knowledge and learning per row would be five-plus queries each.
    Grouping by `workspace_id` once per table gives the same numbers for the
    whole page in a fixed number of queries. `client_row` reads from here for
    anything that is a count; it still calls the real services for anything
    that is a judgement (quota, readiness, onboarding stage, approval).

    Counts are workspace-scoped, not default-brand-scoped, because every one
    of these tables carries a workspace FK: a client with two brands has the
    knowledge of both, and that is what the operator is looking at.
    """

    def __init__(self, workspace_ids, *, days=DEFAULT_INACTIVE_DAYS):
        ids = [wid for wid in workspace_ids]
        now = timezone.now()
        self.days = days

        self.content = defaultdict(dict)
        for row in (
            ContentItem.objects.filter(workspace_id__in=ids)
            .values('workspace_id', 'status').annotate(n=Count('id'))
        ):
            self.content[row['workspace_id']][row['status']] = row['n']

        self.publishing = defaultdict(dict)
        for row in (
            PublishingJob.objects.filter(workspace_id__in=ids)
            .values('workspace_id', 'status').annotate(n=Count('id'))
        ):
            self.publishing[row['workspace_id']][row['status']] = row['n']

        self.team = {
            row['workspace_id']: {'count': row['n'], 'last_active_at': row['last']}
            for row in (
                WorkspaceMember.objects.filter(workspace_id__in=ids)
                .values('workspace_id')
                .annotate(n=Count('id'), last=Max('last_active_at'))
            )
        }

        self.knowledge_sources = self._grouped(
            BrandSource.objects.filter(workspace_id__in=ids)
            .exclude(status=BrandSource.SourceStatus.ARCHIVED)
        )
        self.confirmed_facts = self._grouped(
            BrandMemory.objects.filter(
                workspace_id__in=ids, status=BrandMemory.MemoryStatus.CONFIRMED
            ).exclude(source__status=BrandSource.SourceStatus.ARCHIVED)
        )
        self.inspirations = self._grouped(
            BrandInspiration.objects.filter(workspace_id__in=ids).eligible_for_retrieval()
        )
        self.rules = self._grouped(
            BrandRule.objects.filter(workspace_id__in=ids, is_active=True)
        )
        self.preferences = self._grouped(
            BrandPreference.objects.filter(workspace_id__in=ids).active()
        )

        # Same definitions as the health console's live signals, so the
        # portfolio flags and the tiles count the same clients.
        self.routed = set(
            WorkspaceAIRoute.objects.filter(workspace_id__in=ids, enabled=True)
            .values_list('workspace_id', flat=True)
        )
        self.recently_active = set(
            WorkspaceMember.objects.filter(
                workspace_id__in=ids,
                status=WorkspaceMember.Status.ACTIVE,
                last_active_at__gte=now - timedelta(days=days),
            ).values_list('workspace_id', flat=True)
        )

        self.subscriptions = {
            sub.workspace_id: sub
            for sub in Subscription.objects.filter(workspace_id__in=ids).select_related('plan')
        }

        # The default brand, or the first non-archived one — Meta ordering is
        # (-is_default, name), so the first row seen per workspace is it.
        self.brands = {}
        for brand in (
            Brand.objects.filter(workspace_id__in=ids)
            .exclude(status=Brand.Status.ARCHIVED)
            .select_related('workspace')
        ):
            self.brands.setdefault(brand.workspace_id, brand)

    @staticmethod
    def _grouped(queryset):
        return {
            row['workspace_id']: row['n']
            for row in queryset.values('workspace_id').annotate(n=Count('id'))
        }

    def brand_for(self, workspace_id):
        return self.brands.get(workspace_id)


# ───────────────────────────────────────────────────── the row

def _onboarding_row(brand):
    """Where the brand is in setup, derived from what exists right now.

    `refresh_stage` is what the client's own onboarding screen calls, so the
    operator sees the same stage the client does — not a stage frozen at the
    last time the client opened that screen.
    """
    return refresh_stage(ensure_onboarding(brand))


def _quota_flags(usage):
    """OVER_QUOTA / SPEND_CAP_REACHED from `quota.summary()`'s own numbers.

    `check()` stops at the first ceiling it hits and ignores per-capability
    limits when no capability is named, so the verdict code alone would miss
    a client who is out of posters but under the overall limit. The summary
    carries every ceiling; read them all.
    """
    flags = []
    if not usage.get('subscribed'):
        return flags
    limit = usage.get('generations_limit') or 0
    if limit and (usage.get('generations_used') or 0) >= limit:
        flags.append('OVER_QUOTA')
    else:
        for capability in usage.get('capabilities') or []:
            if capability.get('limit') and capability.get('used', 0) >= capability['limit']:
                flags.append('OVER_QUOTA')
                break
    try:
        cap = Decimal(str(usage.get('spend_cap') or '0'))
        spend = Decimal(str(usage.get('spend') or '0'))
    except InvalidOperation:  # pragma: no cover - summary always quantises
        cap = spend = Decimal('0')
    if cap > 0 and spend >= cap:
        flags.append('SPEND_CAP_REACHED')
    return flags


def client_row(workspace, stats=None):
    """One portfolio row for `workspace`. Used by the list and the detail.

    `stats` is the page's `PortfolioStats`; the detail view passes none and
    gets a one-workspace instance. Every value is a query or a service call;
    a field whose data cannot exist for this client is null, never zero.
    """
    stats = stats or PortfolioStats([workspace.pk])
    ws_id = workspace.pk
    is_live = workspace.status == MarketingWorkspace.Status.ACTIVE

    brand = stats.brand_for(ws_id)
    subscription = stats.subscriptions.get(ws_id)
    usage = quota.summary(workspace)

    content_by_status = dict(stats.content.get(ws_id, {}))
    content_total = sum(content_by_status.values())
    publishing_by_status = stats.publishing.get(ws_id, {})
    team = stats.team.get(ws_id, {'count': 0, 'last_active_at': None})

    onboarding = None
    readiness = None
    if brand is not None:
        row = _onboarding_row(brand)
        onboarding = {'current_stage': row.current_stage, 'status': row.status}
        scored = brand_readiness(brand)
        readiness = {
            'score': scored['readiness_score'],
            'level': scored['readiness_level'],
        }

    # ── flags ────────────────────────────────────────────────────────
    flags = []
    block = spend_block(workspace)
    if block is not None and block.code == 'CLIENT_NOT_APPROVED':
        flags.append('PENDING_APPROVAL')
    # Routing, activity and publishing failures are expected to be absent on
    # a suspended or archived client, so they only count against a live one
    # — exactly as the health console counts them.
    if is_live and ws_id not in stats.routed:
        flags.append('NO_AI_ROUTING')
    flags.extend(_quota_flags(usage))
    # A generation is a ContentItem, which is also what the quota meters.
    if content_total == 0:
        flags.append('NEVER_GENERATED')
    if is_live and ws_id not in stats.recently_active:
        flags.append('INACTIVE')
    if is_live and publishing_by_status.get(PublishingJob.Status.FAILED, 0) > 0:
        flags.append('FAILING_PUBLISHES')
    if workspace.status == MarketingWorkspace.Status.SUSPENDED:
        flags.append('SUSPENDED')
    if workspace.status == MarketingWorkspace.Status.ARCHIVED:
        flags.append('ARCHIVED')
    if brand is not None and brand.brain_is_stale:
        flags.append('BRAIN_STALE')

    return {
        'workspace_id': str(ws_id),
        'client_code': workspace.client_code,
        'name': workspace.workspace_name,
        'status': workspace.status,
        'status_reason': workspace.status_reason,
        'created_at': _iso(workspace.created_at),
        'brand': None if brand is None else {
            'id': str(brand.pk),
            'name': brand.name,
            'status': brand.status,
            'industry': brand.industry,
            'website': brand.website,
        },
        'plan': None if subscription is None else {
            'key': subscription.plan.key,
            'name': subscription.plan.name,
        },
        'subscription_status': subscription.status if subscription else None,
        'onboarding': onboarding,
        'readiness': readiness,
        'counts': {
            'knowledge_sources': stats.knowledge_sources.get(ws_id, 0),
            'confirmed_facts': stats.confirmed_facts.get(ws_id, 0),
            'inspirations': stats.inspirations.get(ws_id, 0),
            'rules': stats.rules.get(ws_id, 0),
            'preferences': stats.preferences.get(ws_id, 0),
            'team': team['count'],
        },
        'content': {'total': content_total, 'by_status': content_by_status},
        'publishing': {
            'published': publishing_by_status.get(PublishingJob.Status.PUBLISHED, 0),
            'failed': publishing_by_status.get(PublishingJob.Status.FAILED, 0),
            'scheduled': publishing_by_status.get(PublishingJob.Status.SCHEDULED, 0),
            'queued': publishing_by_status.get(PublishingJob.Status.QUEUED, 0),
        },
        'usage': usage,
        'last_active_at': _iso(team['last_active_at']),
        'flags': flags,
    }


# ───────────────────────────────────────────────────── P2 — portfolio

def _narrow(queryset, filter_key, *, days):
    """Cut the candidate set at the database before rows are built.

    Each branch is a SUPERSET of what the flag will say — never a subset — so
    the Python pass over `flags` remains the single source of truth and the
    narrowing is only an economy. `all` and `over_quota` cannot be narrowed:
    quota is a service verdict, not a column.
    """
    active = MarketingWorkspace.Status.ACTIVE
    recently_active = WorkspaceMember.objects.filter(
        status=WorkspaceMember.Status.ACTIVE,
        last_active_at__gte=timezone.now() - timedelta(days=days),
    ).values('workspace_id')

    if filter_key == 'suspended':
        return queryset.filter(status=MarketingWorkspace.Status.SUSPENDED)
    if filter_key == 'archived':
        return queryset.filter(status=MarketingWorkspace.Status.ARCHIVED)
    if filter_key == 'pending':
        # spend_block's definition: has brands, none ACTIVE, at least one PENDING.
        return queryset.filter(brands__status=Brand.Status.PENDING).exclude(
            brands__status=Brand.Status.ACTIVE
        ).distinct()
    if filter_key == 'never_generated':
        return queryset.exclude(id__in=ContentItem.objects.values('workspace_id'))
    if filter_key == 'inactive':
        return queryset.filter(status=active).exclude(id__in=recently_active)
    if filter_key == 'failing_publishes':
        return queryset.filter(
            status=active, publishing_jobs__status=PublishingJob.Status.FAILED
        ).distinct()
    if filter_key == 'at_risk':
        routed = WorkspaceAIRoute.objects.filter(enabled=True).values('workspace_id')
        stale_brains = (
            Brand.objects.filter(brain_failed_at__isnull=False)
            .exclude(brain_compiled_at__gt=F('brain_failed_at'))
            .values('workspace_id')
        )
        return queryset.filter(
            (
                Q(status=active)
                & (
                    ~Q(id__in=routed)
                    | ~Q(id__in=recently_active)
                    | Q(publishing_jobs__status=PublishingJob.Status.FAILED)
                )
            )
            | Q(id__in=stale_brains)
        ).distinct()
    return queryset


class ClientPortfolioView(PlatformView):
    """GET /api/platform/clients/?filter=all&days=14&q=&limit=200"""

    def get(self, request):
        filter_key = str(request.query_params.get('filter', 'all')).strip().lower()
        if filter_key not in FILTERS:
            filter_key = 'all'
        days = _int_param(
            request.query_params.get('days'), DEFAULT_INACTIVE_DAYS, lo=1, hi=3650
        )
        limit = _int_param(request.query_params.get('limit'), DEFAULT_LIMIT, lo=1, hi=MAX_LIMIT)
        q = str(request.query_params.get('q', '')).strip()

        queryset = MarketingWorkspace.objects.all()
        if q:
            queryset = queryset.filter(
                Q(client_code__icontains=q)
                | Q(workspace_name__icontains=q)
                | Q(brands__name__icontains=q)
            ).distinct()
        queryset = _narrow(queryset, filter_key, days=days).order_by('-created_at')

        workspaces = list(queryset)
        stats = PortfolioStats([ws.pk for ws in workspaces], days=days)
        wanted = FILTER_FLAGS.get(filter_key)

        rows = []
        for workspace in workspaces:
            row = client_row(workspace, stats)
            if wanted is not None and not any(flag in row['flags'] for flag in wanted):
                continue
            rows.append(row)
            if len(rows) >= limit:
                break

        self.audit('PORTFOLIO_VIEWED', detail={
            'filter': filter_key, 'count': len(rows), 'days': days, 'q': q,
        })
        return APIResponse(success=True, data={
            'count': len(rows),
            'filter': filter_key,
            'days': days,
            'clients': rows,
        })


# ───────────────────────────────────────────────────── P3 — client detail

class ClientDetailView(PlatformView):
    """GET /api/platform/clients/{workspace_id}/"""

    def get(self, request, workspace_id):
        workspace = MarketingWorkspace.objects.filter(pk=workspace_id).first()
        if workspace is None:
            return self.not_found("Client")

        stats = PortfolioStats([workspace.pk])
        row = client_row(workspace, stats)
        brand = stats.brand_for(workspace.pk)

        brain = None
        onboarding = None
        if brand is not None:
            brain = {
                'compiled_at': _iso(brand.brain_compiled_at),
                'version': brand.brain_version,
                'last_error': brand.brain_last_error,
                'failed_at': _iso(brand.brain_failed_at),
                'stale': brand.brain_is_stale,
            }
            ob = _onboarding_row(brand)
            onboarding = {
                'current_stage': ob.current_stage,
                'status': ob.status,
                'started_at': _iso(ob.started_at),
                'completed_at': _iso(ob.completed_at),
                'skipped_steps': list(ob.skipped_steps or []),
            }

        recent_items = list(
            ContentItem.objects.filter(workspace=workspace)
            .select_related('asset')
            .order_by('-created_at')[:20]
        )
        # Which of these actually taught the brand something. Generating is
        # not learning: only a human verdict in review (and calibration)
        # writes to the ledger, so a card with no event here is work the
        # system learned nothing from. One query for the whole page.
        taught = set(
            LearningEvent.objects.filter(
                workspace=workspace,
                subject_type=SubjectType.CONTENT_ITEM,
                subject_id__in=[i.pk for i in recent_items],
            )
            .exclude(event_type=LearningEvent.EventType.PUBLISHED)
            .values_list('subject_id', flat=True)
        )
        recent_content = [
            {
                'id': str(item.pk),
                'headline': item.headline,
                'status': item.status,
                'format': item.content_format,
                # The composed preview if there is one, else the asset the
                # item was generated with. Blank renders as a placeholder
                # rather than a broken image.
                'preview_url': (
                    item.preview_url
                    or (item.asset.file_url if item.asset_id else '')
                    or ''
                ),
                'caption': (item.caption or '')[:280],
                'taught_learning': item.pk in taught,
                'created_at': _iso(item.created_at),
            }
            for item in recent_items
        ]
        recent_publishing = [
            {
                'id': str(job.pk),
                'status': job.status,
                'publish_mode': job.publish_mode,
                'scheduled_at': _iso(job.scheduled_at),
                'completed_at': _iso(job.completed_at),
            }
            for job in PublishingJob.objects.filter(workspace=workspace)
            .order_by('-created_at')[:20]
        ]
        recent_ai_calls = [
            {
                'created_at': _iso(call.created_at),
                'capability': call.capability,
                'provider': call.provider.key if call.provider_id else None,
                'success': call.success,
                'latency_ms': call.latency_ms,
                'cost': str(quota.money(call.cost)),
                'error': call.error,
            }
            for call in AIUsageLog.objects.filter(workspace=workspace)
            .select_related('provider').order_by('-created_at')[:50]
        ]
        team = [
            {
                'username': member.user.get_username(),
                'email': member.user.email,
                'role': member.role,
                'status': member.status,
                'last_active_at': _iso(member.last_active_at),
            }
            for member in WorkspaceMember.objects.filter(workspace=workspace)
            .select_related('user').order_by('created_at')
        ]
        # Read before this view's own row is written, so the list shows what
        # was done to the client, not the fact that somebody just looked.
        audit = [
            {
                'created_at': _iso(entry.created_at),
                'actor_username': entry.actor_username,
                'action': entry.action,
                'target': entry.target,
                'detail': entry.detail,
            }
            for entry in PlatformAuditLog.objects.filter(workspace=workspace)
            .order_by('-created_at')[:50]
        ]
        universal = settings_for(workspace)

        self.audit(
            'CLIENT_VIEWED', workspace=workspace,
            target=f'workspace:{workspace.pk}',
            detail={'workspace_id': str(workspace.pk)},
        )
        return APIResponse(success=True, data={
            'client': row,
            'brain': brain,
            'onboarding': onboarding,
            'recent_content': recent_content,
            'recent_publishing': recent_publishing,
            'recent_ai_calls': recent_ai_calls,
            'team': team,
            'audit': audit,
            'universal': {
                'standards_enabled': universal.standards_enabled,
                'inspirations_enabled': universal.inspirations_enabled,
            },
        })
