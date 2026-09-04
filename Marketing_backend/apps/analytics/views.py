from decimal import Decimal, InvalidOperation

from django.db.models import Count, Max, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.brands.models import Brand
from apps.common.permissions import HasWorkspaceRole, IsWorkspaceMember, get_request_workspace
from apps.common.responses import APIResponse
from apps.content.models import ContentItem
from apps.engagement.models import EngagementItem
from apps.publishing.models import PublishingJob, PublishingJobItem
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import WorkspaceMember

from .models import (
    GrowthLead,
    PerformanceObservation,
    PerformanceSyncRun,
    RevenueEvent,
)
from .serializers import (
    GrowthLeadSerializer,
    PerformanceObservationSerializer,
    PerformanceSyncRunSerializer,
    RevenueEventSerializer,
)
from .measurements import METRIC_FIELDS, campaign_returns, dashboard_measurements


class AnalyticsDashboardView(APIView):
    permission_classes = [IsWorkspaceMember]

    def get(self, request):
        # Was MarketingWorkspace.objects.first(), which served whichever
        # workspace the database returned first to any caller.
        workspace, error = get_request_workspace(request)
        if error:
            return error

        observation_query = PerformanceObservation.objects.select_related('content_item').filter(
            workspace=workspace
        )
        observations = observation_query[:50]
        sync_runs = PerformanceSyncRun.objects.select_related('social_connection').filter(
            workspace=workspace
        )[:10]
        leads = GrowthLead.objects.filter(workspace=workspace)[:50]
        revenue_query = RevenueEvent.objects.filter(workspace=workspace)
        revenue_events = revenue_query[:50]
        revenue_by_currency = [
            {'currency': row['currency'], 'amount': str(row['total'])}
            for row in revenue_query.values('currency').annotate(total=Sum('amount')).order_by('currency')
        ]
        revenue_total = revenue_by_currency[0]['amount'] if len(revenue_by_currency) == 1 else None
        from .services import _latest_observations
        latest_rows = _latest_observations(workspace)
        measured = dashboard_measurements(latest_rows)
        latest_observed = observation_query.aggregate(latest=Max('observed_at'))['latest']

        # Deliberately NOT the APIResponse envelope: the frontend reads
        # data.trend / data.platform_perf / data.roi at the top level.
        # Reshaping this is a separate change with matching frontend edits.
        return Response(
            {
                "trend": measured['trend'],
                "platform_perf": measured['platform_perf'],
                "roi": campaign_returns(latest_rows, revenue_query),
                "observations": PerformanceObservationSerializer(observations, many=True).data,
                "sync_runs": PerformanceSyncRunSerializer(sync_runs, many=True).data,
                "leads": GrowthLeadSerializer(leads, many=True).data,
                "revenue_events": RevenueEventSerializer(revenue_events, many=True).data,
                "summary": {
                    "observation_count": PerformanceObservation.objects.filter(
                        workspace=workspace
                    ).count(),
                    "lead_count": GrowthLead.objects.filter(workspace=workspace).count(),
                    "converted_leads": GrowthLead.objects.filter(
                        workspace=workspace, status=GrowthLead.Status.CONVERTED
                    ).count(),
                    "revenue": revenue_total,
                    "revenue_currency": revenue_by_currency[0]['currency'] if len(revenue_by_currency) == 1 else None,
                    "revenue_by_currency": revenue_by_currency,
                    "measurements": measured['totals'],
                    "latest_observed_at": latest_observed,
                },
            }
        )


ACCOUNT_ATTENTION_STATUSES = (
    SocialConnection.Status.TOKEN_EXPIRED,
    SocialConnection.Status.REAUTHORIZATION_REQUIRED,
    SocialConnection.Status.PERMISSION_MISSING,
    SocialConnection.Status.REVOKED,
    SocialConnection.Status.CONNECTION_FAILED,
)


def workspace_kpis(workspace):
    """Counts that exist, from the tables that own them.

    This used to return eight fixed numbers ("24.8K reach", "3.8x ROI") to
    every workspace. Nothing ingests reach, engagement or revenue yet, so
    those are not reported at all rather than invented. What IS known is the
    state of the pipeline - accounts, review queue, scheduled and published
    posts - and each tile names the screen that owns it.
    """
    content_counts = ContentItem.objects.filter(workspace=workspace).aggregate(
        awaiting_review=Count(
            'id', filter=Q(status=ContentItem.Status.PENDING_REVIEW)
        ),
        approved=Count('id', filter=Q(status=ContentItem.Status.APPROVED)),
    )
    job_counts = PublishingJob.objects.filter(workspace=workspace).aggregate(
        scheduled=Count(
            'id', filter=Q(status=PublishingJob.Status.SCHEDULED)
        ),
    )
    item_counts = PublishingJobItem.objects.filter(
        publishing_job__workspace=workspace
    ).aggregate(
        published=Count(
            'id', filter=Q(status=PublishingJobItem.Status.PUBLISHED)
        ),
        failed=Count('id', filter=Q(status=PublishingJobItem.Status.FAILED)),
    )
    connection_counts = SocialConnection.objects.filter(workspace=workspace).aggregate(
        connected=Count(
            'id', filter=Q(status=SocialConnection.Status.CONNECTED)
        ),
        attention=Count('id', filter=Q(status__in=ACCOUNT_ATTENTION_STATUSES)),
    )

    attention = connection_counts['attention']
    attention_hint = None
    if attention:
        attention_hint = "%d need%s attention" % (attention, "s" if attention == 1 else "")

    return [
        {
            "key": "awaiting_review",
            "label": "Awaiting review",
            "value": content_counts['awaiting_review'],
            "icon": "CheckCircle2",
            "hint": "Generated content waiting for a decision",
        },
        {
            "key": "approved",
            "label": "Approved, not yet published",
            "value": content_counts['approved'],
            "icon": "Send",
            "accent": "gold",
        },
        {
            "key": "scheduled",
            "label": "Scheduled posts",
            "value": job_counts['scheduled'],
            "icon": "CalendarClock",
        },
        {
            "key": "published",
            "label": "Published posts",
            "value": item_counts['published'],
            "icon": "Megaphone",
            "accent": "gold",
            "hint": "Per platform, all time",
        },
        {
            "key": "failed",
            "label": "Failed publishes",
            "value": item_counts['failed'],
            "icon": "AlertTriangle",
        },
        {
            "key": "connected_accounts",
            "label": "Connected accounts",
            "value": connection_counts['connected'],
            "icon": "Share2",
            "hint": attention_hint,
        },
    ]


class AnalyticsKPIView(APIView):
    permission_classes = [IsWorkspaceMember]

    def get(self, request):
        workspace, error = get_request_workspace(request)
        if error:
            return error
        # Top-level shape preserved for the same reason as the dashboard.
        return Response({"kpis": workspace_kpis(workspace)})


class GovernedAnalyticsView(APIView):
    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    def workspace(self, request):
        return get_request_workspace(request)


class PerformanceSyncView(GovernedAnalyticsView):
    def get(self, request, run_id=None):
        workspace, error = self.workspace(request)
        if error:
            return error
        queryset = PerformanceSyncRun.objects.select_related('social_connection').filter(workspace=workspace)
        if run_id is None:
            return APIResponse(success=True, data=PerformanceSyncRunSerializer(queryset[:10], many=True).data)
        run = queryset.filter(pk=run_id).first()
        if run is None:
            return APIResponse(success=False, message='Sync run not found.', status=404)
        return APIResponse(success=True, data=PerformanceSyncRunSerializer(run).data)

    def post(self, request, run_id=None):
        if run_id is not None:
            return APIResponse(success=False, message='Start a sync from the collection endpoint.', status=405)
        workspace, error = self.workspace(request)
        if error:
            return error
        connection = SocialConnection.objects.filter(
            workspace=workspace, pk=request.data.get('social_connection')
        ).first()
        if connection is None:
            return APIResponse(success=False, message='Social account not found.', status=404)
        if connection.platform not in (
            SocialConnection.Platform.X, SocialConnection.Platform.YOUTUBE
        ):
            return APIResponse(
                success=False,
                message=(
                    'Live metric sync currently supports X and YouTube. Use an '
                    'auditable import for any other platform.'
                ),
                status=status.HTTP_409_CONFLICT,
            )
        run = PerformanceSyncRun.objects.create(
            workspace=workspace, social_connection=connection, initiated_by=request.user
        )
        from .tasks import sync_performance_task

        try:
            result = sync_performance_task.enqueue(str(run.pk))
        except Exception:
            run.status = PerformanceSyncRun.Status.FAILED
            run.error = 'Metrics sync could not be queued. Please try again.'
            run.completed_at = timezone.now()
            run.save(update_fields=['status', 'error', 'completed_at', 'updated_at'])
            return APIResponse(success=False, message=run.error, status=503)
        run.task_id = str(result.id)
        run.save(update_fields=['task_id', 'updated_at'])
        return APIResponse(
            success=True, data=PerformanceSyncRunSerializer(run).data,
            status=status.HTTP_202_ACCEPTED,
        )


def _nonnegative_int(value, name):
    try:
        number = Decimal(str(value if value not in (None, '') else 0))
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError
        parsed = int(number)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{name} must be a whole number.') from None
    if parsed < 0:
        raise ValueError(f'{name} cannot be negative.')
    return parsed


def _currency(value):
    currency = str(value or 'USD').strip().upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise ValueError('Currency must be a three-letter currency code.')
    return currency


class PerformanceImportView(GovernedAnalyticsView):
    """Auditable metric intake for any platform the client chooses."""

    def post(self, request):
        workspace, error = self.workspace(request)
        if error:
            return error
        source_record_id = str(request.data.get('source_record_id') or '').strip()[:255]
        platform = str(request.data.get('platform') or '').strip()[:50]
        if not source_record_id or not platform:
            return APIResponse(
                success=False, message='source_record_id and platform are required.', status=400
            )
        observed_at = parse_datetime(str(request.data.get('observed_at') or ''))
        if observed_at is None:
            return APIResponse(success=False, message='observed_at must be an ISO timestamp.', status=400)
        content = None
        if request.data.get('content_item'):
            content = ContentItem.objects.filter(
                workspace=workspace, pk=request.data.get('content_item')
            ).first()
            if content is None:
                return APIResponse(success=False, message='Content item not found.', status=404)
        try:
            spend = Decimal(str(request.data.get('spend') or '0'))
            revenue = Decimal(str(request.data.get('revenue') or '0'))
            if not spend.is_finite() or not revenue.is_finite() or spend < 0 or revenue < 0:
                raise ValueError('Spend and revenue cannot be negative.')
            defaults = {
                'brand': content.brand if content else None,
                'content_item': content,
                'platform': platform,
                'external_post_id': str(request.data.get('external_post_id') or '')[:255],
                'campaign_name': str(request.data.get('campaign_name') or '')[:255],
                'impressions': _nonnegative_int(request.data.get('impressions'), 'impressions'),
                'reach': _nonnegative_int(request.data.get('reach'), 'reach'),
                'engagement': _nonnegative_int(request.data.get('engagement'), 'engagement'),
                'clicks': _nonnegative_int(request.data.get('clicks'), 'clicks'),
                'conversions': _nonnegative_int(request.data.get('conversions'), 'conversions'),
                'spend': spend,
                'revenue': revenue,
                'currency': _currency(request.data.get('currency')),
                'observed_at': observed_at,
                'source_payload': request.data.get('source_payload') if isinstance(
                    request.data.get('source_payload'), dict
                ) else {},
                'ingested_by': request.user,
            }
            defaults['source_payload'] = {
                **defaults['source_payload'],
                'measured_fields': [field for field in METRIC_FIELDS if request.data.get(field) not in (None, '')],
            }
        except (InvalidOperation, ValueError) as exc:
            return APIResponse(success=False, message=str(exc), status=400)
        observation, created = PerformanceObservation.objects.get_or_create(
            workspace=workspace,
            source=PerformanceObservation.Source.AUDITABLE_IMPORT,
            source_record_id=source_record_id,
            defaults=defaults,
        )
        if not created:
            return APIResponse(
                success=True, message='This source record was already imported.',
                data=PerformanceObservationSerializer(observation).data,
            )
        from .services import rebuild_workspace_projections

        rebuild_workspace_projections(workspace)
        return APIResponse(
            success=True, data=PerformanceObservationSerializer(observation).data,
            status=status.HTTP_201_CREATED,
        )


class GrowthLeadView(GovernedAnalyticsView):
    def get(self, request):
        workspace, error = self.workspace(request)
        if error:
            return error
        return APIResponse(
            success=True,
            data=GrowthLeadSerializer(GrowthLead.objects.filter(workspace=workspace), many=True).data,
        )

    def post(self, request):
        workspace, error = self.workspace(request)
        if error:
            return error
        engagement = None
        if request.data.get('engagement_item'):
            engagement = EngagementItem.objects.filter(
                workspace=workspace, pk=request.data.get('engagement_item')
            ).first()
            if engagement is None:
                return APIResponse(success=False, message='Engagement item not found.', status=404)
        brand = None
        brand_id = request.data.get('brand') or getattr(engagement, 'brand_id', None)
        if brand_id:
            brand = Brand.objects.filter(workspace=workspace, pk=brand_id).first()
            if brand is None:
                return APIResponse(success=False, message='Brand not found.', status=404)
        if engagement:
            existing = GrowthLead.objects.filter(engagement_item=engagement).first()
            if existing:
                return APIResponse(success=True, data=GrowthLeadSerializer(existing).data)
        try:
            estimated = Decimal(str(request.data.get('estimated_value') or '0'))
            if not estimated.is_finite() or estimated < 0:
                raise ValueError('Estimated value cannot be negative.')
            currency = _currency(request.data.get('currency'))
        except (InvalidOperation, ValueError) as exc:
            return APIResponse(success=False, message=str(exc), status=400)
        lead = GrowthLead.objects.create(
            workspace=workspace,
            brand=brand,
            engagement_item=engagement,
            name=str(request.data.get('name') or getattr(engagement, 'author_name', ''))[:255],
            handle=str(request.data.get('handle') or getattr(engagement, 'author_handle', ''))[:255],
            email=str(request.data.get('email') or '')[:254],
            source=str(request.data.get('source') or ('ENGAGEMENT' if engagement else 'MANUAL'))[:80],
            external_reference=str(request.data.get('external_reference') or '')[:255],
            estimated_value=estimated,
            currency=currency,
            notes=str(request.data.get('notes') or ''),
            created_by=request.user,
        )
        return APIResponse(
            success=True, data=GrowthLeadSerializer(lead).data,
            status=status.HTTP_201_CREATED,
        )


class RevenueEventView(GovernedAnalyticsView):
    def get(self, request):
        workspace, error = self.workspace(request)
        if error:
            return error
        return APIResponse(
            success=True,
            data=RevenueEventSerializer(
                RevenueEvent.objects.filter(workspace=workspace), many=True
            ).data,
        )

    def post(self, request):
        workspace, error = self.workspace(request)
        if error:
            return error
        source = str(request.data.get('source') or '').strip()[:80]
        external_id = str(request.data.get('external_event_id') or '').strip()[:255]
        occurred_at = parse_datetime(str(request.data.get('occurred_at') or ''))
        if not source or not external_id or occurred_at is None:
            return APIResponse(
                success=False,
                message='source, external_event_id and ISO occurred_at are required.',
                status=400,
            )
        lead = None
        if request.data.get('lead'):
            lead = GrowthLead.objects.filter(workspace=workspace, pk=request.data.get('lead')).first()
            if lead is None:
                return APIResponse(success=False, message='Lead not found.', status=404)
        content = None
        if request.data.get('content_item'):
            content = ContentItem.objects.filter(
                workspace=workspace, pk=request.data.get('content_item')
            ).first()
            if content is None:
                return APIResponse(success=False, message='Content item not found.', status=404)
        try:
            amount = Decimal(str(request.data.get('amount')))
            if not amount.is_finite() or amount < 0:
                raise ValueError('Amount cannot be negative.')
            currency = _currency(request.data.get('currency'))
        except (InvalidOperation, TypeError, ValueError):
            return APIResponse(success=False, message='amount must be finite and non-negative; currency must be a three-letter code.', status=400)
        event, created = RevenueEvent.objects.get_or_create(
            workspace=workspace, source=source, external_event_id=external_id,
            defaults={
                'lead': lead, 'content_item': content,
                'campaign_name': str(request.data.get('campaign_name') or '')[:255],
                'amount': amount,
                'currency': currency,
                'occurred_at': occurred_at,
                'metadata': request.data.get('metadata') if isinstance(
                    request.data.get('metadata'), dict
                ) else {},
                'recorded_by': request.user,
            },
        )
        if not created and (event.amount != amount or event.currency != currency):
            return APIResponse(
                success=False,
                message='This external revenue id already exists with different values.',
                status=status.HTTP_409_CONFLICT,
            )
        if lead and created:
            lead.status = GrowthLead.Status.CONVERTED
            lead.converted_at = timezone.now()
            lead.save(update_fields=['status', 'converted_at', 'updated_at'])
        from .services import rebuild_workspace_projections

        rebuild_workspace_projections(workspace)
        return APIResponse(
            success=True, data=RevenueEventSerializer(event).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
