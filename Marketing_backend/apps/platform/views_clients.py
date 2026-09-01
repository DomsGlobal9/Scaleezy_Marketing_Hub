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
from types import SimpleNamespace

from django.db.models import (
    CharField,
    Count,
    DateTimeField,
    DecimalField,
    Exists,
    F,
    FloatField,
    IntegerField,
    JSONField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
    TextField,
    UUIDField,
    Value,
)
from django.utils import timezone

from apps.ai.models import AIUsageLog, WorkspaceAIRoute
from apps.audit.models import PlatformAuditLog
from apps.billing import quota
from apps.billing.models import Subscription
from apps.brands.models import Brand
from apps.brands.services.brand_brain import compile_brand_brain_from_records
from apps.common.platform_health import DEFAULT_INACTIVE_DAYS
from apps.common.responses import APIResponse
from apps.content.models import ContentItem
from apps.context.services.readiness import (
    readiness_counts_for_brands,
    score_brand_readiness,
)
from apps.inspirations.models import BrandInspiration, InspirationSignal
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import (
    BrandPreference,
    BrandRule,
    LearningEvent,
    LearningScope,
    SubjectType,
)
from apps.onboarding.models import CalibrationDirection
from apps.onboarding.services import derive_onboarding_state
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

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def _iso(moment):
    return moment.isoformat() if moment else None


def _int_param(raw, default, *, lo, hi):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _bulk_usage(workspace_ids):
    """Exact quota summaries for many workspaces in two bounded queries."""
    ids = list(workspace_ids)
    subscriptions = {
        sub.workspace_id: sub
        for sub in Subscription.objects.filter(workspace_id__in=ids).select_related('plan')
    }
    period_filter = Q()
    for workspace_id, subscription in subscriptions.items():
        start, end = subscription.current_period()
        period_filter |= Q(
            workspace_id=workspace_id, created_at__gte=start, created_at__lt=end
        )

    generation_counts = defaultdict(int)
    spend_by_workspace = defaultdict(lambda: Decimal('0'))
    capability_counts = defaultdict(dict)
    if subscriptions:
        content_rows = (
            ContentItem.objects.filter(period_filter).order_by()
            .annotate(
                _usage_workspace_id=F('workspace_id'),
                _usage_capability=Value('', output_field=CharField(max_length=32)),
            )
            .values('_usage_workspace_id', '_usage_capability')
            .annotate(
                _usage_generations=Count('id'),
                _usage_spend=Value(
                    Decimal('0'),
                    output_field=DecimalField(max_digits=12, decimal_places=4),
                ),
                _usage_used=Value(0, output_field=IntegerField()),
            )
            .values(
                '_usage_workspace_id', '_usage_capability', '_usage_generations',
                '_usage_spend', '_usage_used',
            )
        )
        ai_rows = (
            AIUsageLog.objects.filter(period_filter).order_by()
            .annotate(
                _usage_workspace_id=F('workspace_id'),
                _usage_capability=F('capability'),
            )
            .values('_usage_workspace_id', '_usage_capability')
            .annotate(
                _usage_generations=Value(0, output_field=IntegerField()),
                _usage_spend=Sum('cost'),
                _usage_used=Count('id', filter=Q(success=True, selected=True)),
            )
            .values(
                '_usage_workspace_id', '_usage_capability', '_usage_generations',
                '_usage_spend', '_usage_used',
            )
        )
        for row in content_rows.union(ai_rows, all=True).order_by(
            '_usage_workspace_id', '_usage_capability'
        ):
            workspace_id = row['_usage_workspace_id']
            if not row['_usage_capability']:
                generation_counts[workspace_id] = row['_usage_generations']
                continue
            spend_by_workspace[workspace_id] += row['_usage_spend'] or Decimal('0')
            if row['_usage_used']:
                capability_counts[workspace_id][row['_usage_capability']] = row['_usage_used']

    summaries = {}
    for workspace_id in ids:
        summaries[workspace_id] = quota.summary_from_aggregates(
            subscriptions.get(workspace_id),
            generations=generation_counts.get(workspace_id, 0),
            spend=spend_by_workspace[workspace_id],
            per_capability_used=capability_counts[workspace_id],
        )
    return subscriptions, summaries


def _workspace_stat_row(queryset, metric, *, key_field=None, last_field=None):
    """One normalized aggregate branch for the portfolio stats UNION."""
    key = F(key_field) if key_field else Value('', output_field=CharField(max_length=32))
    row = (
        queryset.order_by()
        .annotate(
            _stats_workspace_id=F('workspace_id'),
            _stats_metric=Value(metric, output_field=CharField(max_length=32)),
            _stats_key=key,
        )
        .values('_stats_workspace_id', '_stats_metric', '_stats_key')
        .annotate(
            _stats_count=Count('pk'),
            _stats_last=(
                Max(last_field)
                if last_field
                else Value(None, output_field=DateTimeField())
            ),
        )
        .values(
            '_stats_workspace_id', '_stats_metric', '_stats_key',
            '_stats_count', '_stats_last',
        )
    )
    return row


def _bulk_workspace_stats(workspace_ids, *, now, days):
    """All workspace-level portfolio aggregates in one database round trip."""
    ids = list(workspace_ids)
    content = defaultdict(dict)
    publishing = defaultdict(dict)
    team = {}
    grouped = {
        key: defaultdict(int)
        for key in ('knowledge_sources', 'confirmed_facts', 'inspirations', 'rules', 'preferences')
    }
    routed = set()
    recently_active = set()
    if not ids:
        return content, publishing, team, grouped, routed, recently_active

    rows = _workspace_stat_row(
        ContentItem.objects.filter(workspace_id__in=ids), 'content', key_field='status'
    ).union(
        _workspace_stat_row(
            PublishingJob.objects.filter(workspace_id__in=ids),
            'publishing', key_field='status',
        ),
        _workspace_stat_row(
            WorkspaceMember.objects.filter(workspace_id__in=ids),
            'team', last_field='last_active_at',
        ),
        _workspace_stat_row(
            BrandSource.objects.filter(workspace_id__in=ids).exclude(
                status=BrandSource.SourceStatus.ARCHIVED
            ),
            'knowledge_sources',
        ),
        _workspace_stat_row(
            BrandMemory.objects.filter(
                workspace_id__in=ids, status=BrandMemory.MemoryStatus.CONFIRMED,
            ).exclude(source__status=BrandSource.SourceStatus.ARCHIVED),
            'confirmed_facts',
        ),
        _workspace_stat_row(
            BrandInspiration.objects.filter(workspace_id__in=ids).eligible_for_retrieval(),
            'inspirations',
        ),
        _workspace_stat_row(
            BrandRule.objects.filter(workspace_id__in=ids, is_active=True), 'rules'
        ),
        _workspace_stat_row(
            BrandPreference.objects.filter(workspace_id__in=ids).active(), 'preferences'
        ),
        _workspace_stat_row(
            WorkspaceAIRoute.objects.filter(workspace_id__in=ids, enabled=True), 'routed'
        ),
        _workspace_stat_row(
            WorkspaceMember.objects.filter(
                workspace_id__in=ids,
                status=WorkspaceMember.Status.ACTIVE,
                last_active_at__gte=now - timedelta(days=days),
            ),
            'recently_active',
        ),
        all=True,
    ).order_by('_stats_workspace_id', '_stats_metric', '_stats_key')

    for row in rows:
        workspace_id = row['_stats_workspace_id']
        metric = row['_stats_metric']
        if metric == 'content':
            content[workspace_id][row['_stats_key']] = row['_stats_count']
        elif metric == 'publishing':
            publishing[workspace_id][row['_stats_key']] = row['_stats_count']
        elif metric == 'team':
            team[workspace_id] = {
                'count': row['_stats_count'], 'last_active_at': row['_stats_last'],
            }
        elif metric == 'routed':
            routed.add(workspace_id)
        elif metric == 'recently_active':
            recently_active.add(workspace_id)
        else:
            grouped[metric][workspace_id] = row['_stats_count']
    return content, publishing, team, grouped, routed, recently_active


_BRAIN_COLUMNS = (
    '_brain_kind', '_brain_workspace_id', '_brain_brand_id', '_brain_pk',
    '_brain_category', '_brain_attribute', '_brain_value', '_brain_sentiment',
    '_brain_origin', '_brain_normalized_key', '_brain_memory_type',
    '_brain_content', '_brain_text', '_brain_structured', '_brain_hardness',
    '_brain_priority', '_brain_scope', '_brain_state', '_brain_confidence',
    '_brain_weight',
)


def _brain_record_row(queryset, kind, **fields):
    """Normalize one authoritative Brand Brain record type for a UNION."""
    normalized = {
        '_brain_workspace_id': Value(None, output_field=UUIDField()),
        '_brain_brand_id': Value(None, output_field=UUIDField()),
        '_brain_pk': F('pk'),
        '_brain_category': Value('', output_field=CharField(max_length=64)),
        '_brain_attribute': Value('', output_field=CharField(max_length=255)),
        '_brain_value': Value('', output_field=TextField()),
        '_brain_sentiment': Value('', output_field=CharField(max_length=16)),
        '_brain_origin': Value('', output_field=CharField(max_length=32)),
        '_brain_normalized_key': Value('', output_field=CharField(max_length=255)),
        '_brain_memory_type': Value('', output_field=CharField(max_length=32)),
        '_brain_content': Value('', output_field=TextField()),
        '_brain_text': Value('', output_field=TextField()),
        '_brain_structured': Value({}, output_field=JSONField()),
        '_brain_hardness': Value('', output_field=CharField(max_length=16)),
        '_brain_priority': Value(0, output_field=IntegerField()),
        '_brain_scope': Value('', output_field=CharField(max_length=16)),
        '_brain_state': Value('', output_field=CharField(max_length=16)),
        '_brain_confidence': Value(0.0, output_field=FloatField()),
        '_brain_weight': Value(0.0, output_field=FloatField()),
    }
    normalized.update(fields)
    return (
        queryset.order_by()
        .annotate(
            _brain_kind=Value(kind, output_field=CharField(max_length=16)),
            **normalized,
        )
        .values(*_BRAIN_COLUMNS)
    )


def _bulk_missing_brain_records(brands):
    """Load four authoritative compiler inputs in one database round trip."""
    brands = list(brands)
    records = {
        brand.pk: {'memories': [], 'rules': [], 'preferences': [], 'signals': []}
        for brand in brands
    }
    if not brands:
        return records

    ids = [brand.pk for brand in brands]
    workspace_ids = {brand.workspace_id for brand in brands}
    brand_scope = Q()
    for brand in brands:
        brand_scope |= Q(brand_id=brand.pk, workspace_id=brand.workspace_id)

    rows = _brain_record_row(
        BrandMemory.objects.filter(
            brand_scope, status=BrandMemory.MemoryStatus.CONFIRMED,
        ).exclude(source__status=BrandSource.SourceStatus.ARCHIVED),
        'memory',
        _brain_workspace_id=F('workspace_id'),
        _brain_brand_id=F('brand_id'),
        _brain_normalized_key=F('normalized_key'),
        _brain_memory_type=F('memory_type'),
        _brain_content=F('content'),
        _brain_scope=F('scope'),
        _brain_confidence=F('confidence'),
    ).union(
        _brain_record_row(
            BrandRule.objects.filter(workspace_id__in=workspace_ids, is_active=True).filter(
                brand_scope | Q(brand__isnull=True, scope=LearningScope.TENANT)
            ),
            'rule',
            _brain_workspace_id=F('workspace_id'),
            _brain_brand_id=F('brand_id'),
            _brain_text=F('text'),
            _brain_structured=F('structured'),
            _brain_hardness=F('hardness'),
            _brain_origin=F('origin'),
            _brain_priority=F('priority'),
            _brain_scope=F('scope'),
            _brain_confidence=F('confidence'),
        ),
        _brain_record_row(
            BrandPreference.objects.filter(workspace_id__in=workspace_ids).active().filter(
                brand_scope | Q(brand__isnull=True, scope=LearningScope.TENANT)
            ),
            'preference',
            _brain_workspace_id=F('workspace_id'),
            _brain_brand_id=F('brand_id'),
            _brain_category=F('category'),
            _brain_attribute=F('attribute'),
            _brain_value=F('value'),
            _brain_state=F('state'),
            _brain_scope=F('scope'),
            _brain_confidence=F('confidence'),
            _brain_weight=F('weight'),
        ),
        _brain_record_row(
            InspirationSignal.objects.filter(inspiration__brand_id__in=ids)
            .eligible_for_retrieval(),
            'signal',
            _brain_workspace_id=F('inspiration__workspace_id'),
            _brain_brand_id=F('inspiration__brand_id'),
            _brain_category=F('category'),
            _brain_attribute=F('attribute'),
            _brain_value=F('value'),
            _brain_sentiment=F('sentiment'),
            _brain_origin=F('origin'),
            _brain_confidence=F('confidence'),
            _brain_weight=F('weight'),
        ),
        all=True,
    ).order_by('_brain_kind', '_brain_pk')

    brands_by_workspace = defaultdict(list)
    for brand in brands:
        brands_by_workspace[brand.workspace_id].append(brand.pk)

    for row in rows:
        record = SimpleNamespace(
            pk=row['_brain_pk'],
            workspace_id=row['_brain_workspace_id'],
            brand_id=row['_brain_brand_id'],
            category=row['_brain_category'],
            attribute=row['_brain_attribute'],
            value=row['_brain_value'],
            sentiment=row['_brain_sentiment'],
            origin=row['_brain_origin'],
            normalized_key=row['_brain_normalized_key'],
            memory_type=row['_brain_memory_type'],
            content=row['_brain_content'],
            text=row['_brain_text'],
            structured=row['_brain_structured'] or {},
            hardness=row['_brain_hardness'],
            priority=row['_brain_priority'],
            scope=row['_brain_scope'],
            state=row['_brain_state'],
            confidence=row['_brain_confidence'],
            weight=row['_brain_weight'],
        )
        kind = row['_brain_kind']
        targets = (
            [row['_brain_brand_id']]
            if row['_brain_brand_id']
            else brands_by_workspace[row['_brain_workspace_id']]
        )
        bucket = {
            'memory': 'memories', 'rule': 'rules',
            'preference': 'preferences', 'signal': 'signals',
        }[kind]
        for brand_id in targets:
            if brand_id in records:
                records[brand_id][bucket].append(record)
    return records


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

        (
            self.content,
            self.publishing,
            self.team,
            workspace_counts,
            self.routed,
            self.recently_active,
        ) = _bulk_workspace_stats(ids, now=now, days=days)
        self.knowledge_sources = workspace_counts['knowledge_sources']
        self.confirmed_facts = workspace_counts['confirmed_facts']
        self.inspirations = workspace_counts['inspirations']
        self.rules = workspace_counts['rules']
        self.preferences = workspace_counts['preferences']

        self.subscriptions, self.usage = _bulk_usage(ids)

        # The default brand, or the first non-archived one — Meta ordering is
        # (-is_default, name), so the first row seen per workspace is it.
        self.brands = {}
        self.has_brand = set()
        self.active_brand = set()
        self.pending_brand = set()
        latest_direction = (
            CalibrationDirection.objects.filter(brand_id=OuterRef('pk'))
            .order_by('-created_at')
        )
        for brand in (
            Brand.objects.filter(workspace_id__in=ids)
            .select_related('workspace', 'onboarding')
            .annotate(
                _portfolio_has_generated=Exists(
                    ContentItem.objects.filter(brand_id=OuterRef('pk'))
                ),
                _portfolio_latest_round=Subquery(
                    latest_direction.values('round_id')[:1]
                ),
                _portfolio_latest_verdict=Subquery(
                    latest_direction.values('verdict')[:1]
                ),
            )
        ):
            self.has_brand.add(brand.workspace_id)
            if brand.status == Brand.Status.ACTIVE:
                self.active_brand.add(brand.workspace_id)
            elif brand.status == Brand.Status.PENDING:
                self.pending_brand.add(brand.workspace_id)
            if brand.status != Brand.Status.ARCHIVED:
                self.brands.setdefault(brand.workspace_id, brand)

        brand_ids = [brand.pk for brand in self.brands.values()]
        self.readiness = readiness_counts_for_brands(brand_ids)
        self.brains = {
            brand.pk: brand.creative_brain
            for brand in self.brands.values()
            if brand.creative_brain
        }
        missing_brains = [
            brand for brand in self.brands.values() if not brand.creative_brain
        ]
        if missing_brains:
            brain_records = _bulk_missing_brain_records(missing_brains)
            for brand in missing_brains:
                records = brain_records[brand.pk]
                self.brains[brand.pk] = compile_brand_brain_from_records(
                    brand,
                    memories=records['memories'],
                    rules=records['rules'],
                    preferences=records['preferences'],
                    signals=records['signals'],
                )
        self.generated_brands = set()
        self.onboarding = {}
        self.latest_calibration_round = {}
        self.pending_calibration = set()
        for brand in self.brands.values():
            if brand._portfolio_has_generated:
                self.generated_brands.add(brand.pk)
            saved_onboarding = getattr(brand, 'onboarding', None)
            if saved_onboarding is not None:
                self.onboarding[brand.pk] = saved_onboarding
            if brand._portfolio_latest_round is not None:
                self.latest_calibration_round[brand.pk] = brand._portfolio_latest_round
                if brand._portfolio_latest_verdict == CalibrationDirection.Verdict.PENDING:
                    self.pending_calibration.add(brand.pk)

    def brand_for(self, workspace_id):
        return self.brands.get(workspace_id)

    def pending_approval(self, workspace):
        if workspace.approval_status == MarketingWorkspace.Approval.PENDING:
            return True
        return (
            workspace.approval_status == MarketingWorkspace.Approval.APPROVED
            and workspace.pk in self.has_brand
            and workspace.pk not in self.active_brand
            and workspace.pk in self.pending_brand
        )

    def onboarding_for(self, brand):
        counts = self.readiness.get(brand.pk, {})
        current, status = derive_onboarding_state(
            has_basics=bool(brand.name and (brand.industry or brand.tagline)),
            has_knowledge=bool(counts.get('sources')),
            has_inspirations=bool(counts.get('inspirations')),
            has_calibration=(
                brand.pk in self.latest_calibration_round
                and brand.pk not in self.pending_calibration
            ),
            has_generated=brand.pk in self.generated_brands,
            skipped_steps=getattr(self.onboarding.get(brand.pk), 'skipped_steps', ()),
        )
        return {'current_stage': current, 'status': status}

    def readiness_for(self, brand):
        scored = score_brand_readiness(
            brand, self.readiness[brand.pk], brain=self.brains[brand.pk]
        )
        return {
            'score': scored['readiness_score'],
            'level': scored['readiness_level'],
        }


# ───────────────────────────────────────────────────── the row

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
    usage = stats.usage[ws_id]

    content_by_status = dict(stats.content.get(ws_id, {}))
    content_total = sum(content_by_status.values())
    publishing_by_status = stats.publishing.get(ws_id, {})
    team = stats.team.get(ws_id, {'count': 0, 'last_active_at': None})

    onboarding = None
    readiness = None
    if brand is not None:
        onboarding = stats.onboarding_for(brand)
        readiness = stats.readiness_for(brand)

    # ── flags ────────────────────────────────────────────────────────
    flags = []
    if stats.pending_approval(workspace):
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
        # Workspace approval is authoritative. The brand fallback preserves
        # the stricter approved-workspace rule in spend_block().
        return queryset.filter(
            Q(approval_status=MarketingWorkspace.Approval.PENDING)
            | (
                Q(approval_status=MarketingWorkspace.Approval.APPROVED)
                & Q(brands__status=Brand.Status.PENDING)
                & ~Q(brands__status=Brand.Status.ACTIVE)
            )
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
            .exclude(status=Brand.Status.ARCHIVED)
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
    """GET /api/platform/clients/?filter=all&days=14&q=&page=1&page_size=25"""

    def get(self, request):
        filter_key = str(request.query_params.get('filter', 'all')).strip().lower()
        if filter_key not in FILTERS:
            filter_key = 'all'
        days = _int_param(
            request.query_params.get('days'), DEFAULT_INACTIVE_DAYS, lo=1, hi=3650
        )
        page = _int_param(request.query_params.get('page'), 1, lo=1, hi=1_000_000)
        requested_size = request.query_params.get(
            'page_size', request.query_params.get('limit')
        )
        page_size = _int_param(requested_size, DEFAULT_LIMIT, lo=1, hi=MAX_LIMIT)
        q = str(request.query_params.get('q', '')).strip()

        queryset = MarketingWorkspace.objects.all()
        if q:
            queryset = queryset.filter(
                Q(client_code__icontains=q)
                | Q(workspace_name__icontains=q)
                | Q(brands__name__icontains=q)
            ).distinct()
        queryset = _narrow(queryset, filter_key, days=days).order_by('-created_at')
        offset = (page - 1) * page_size

        if filter_key == 'over_quota':
            # Periods differ per subscription, so this filter cannot be one
            # honest static WHERE clause. Count all candidates in bulk, then
            # page the matching ids before building the expensive row model.
            candidate_ids = list(queryset.values_list('pk', flat=True))
            filtered_ids = []
            for start in range(0, len(candidate_ids), MAX_LIMIT):
                batch = candidate_ids[start:start + MAX_LIMIT]
                _subscriptions, candidate_usage = _bulk_usage(batch)
                filtered_ids.extend(
                    workspace_id for workspace_id in batch
                    if _quota_flags(candidate_usage[workspace_id])
                )
            total = len(filtered_ids)
            page_ids = filtered_ids[offset:offset + page_size]
            by_id = {
                workspace.pk: workspace
                for workspace in MarketingWorkspace.objects.filter(pk__in=page_ids)
            }
            workspaces = [by_id[workspace_id] for workspace_id in page_ids]
        else:
            total = queryset.count()
            workspaces = list(queryset[offset:offset + page_size])

        stats = PortfolioStats([ws.pk for ws in workspaces], days=days)
        wanted = FILTER_FLAGS.get(filter_key)

        rows = []
        for workspace in workspaces:
            row = client_row(workspace, stats)
            if wanted is not None and not any(flag in row['flags'] for flag in wanted):
                continue
            rows.append(row)

        total_pages = (total + page_size - 1) // page_size if total else 0

        self.audit('PORTFOLIO_VIEWED', detail={
            'filter': filter_key, 'count': len(rows), 'total': total,
            'page': page, 'page_size': page_size, 'days': days, 'q': q,
        })
        return APIResponse(success=True, data={
            'count': total,
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'next_page': page + 1 if page < total_pages else None,
            'previous_page': page - 1 if page > 1 and total else None,
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
            saved_onboarding = stats.onboarding.get(brand.pk)
            onboarding = {
                **row['onboarding'],
                'started_at': _iso(
                    saved_onboarding.started_at if saved_onboarding else None
                ),
                'completed_at': _iso(
                    saved_onboarding.completed_at if saved_onboarding else None
                ),
                'skipped_steps': list(
                    saved_onboarding.skipped_steps if saved_onboarding else []
                ),
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
