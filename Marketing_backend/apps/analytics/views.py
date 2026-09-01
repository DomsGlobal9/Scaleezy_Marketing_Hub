from decimal import Decimal, InvalidOperation

from django.db.models import Max, Sum
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
    CampaignROI,
    DailyMetric,
    GrowthLead,
    PerformanceObservation,
    PerformanceSyncRun,
    PlatformPerformance,
    RevenueEvent,
)
from .serializers import (
    CampaignROISerializer,
    DailyMetricSerializer,
    GrowthLeadSerializer,
    PerformanceObservationSerializer,
    PerformanceSyncRunSerializer,
    PlatformPerformanceSerializer,
    RevenueEventSerializer,
)


class AnalyticsDashboardView(APIView):
    permission_classes = [IsWorkspaceMember]

    def get(self, request):
        # Was MarketingWorkspace.objects.first(), which served whichever
        # workspace the database returned first to any caller.
        workspace, error = get_request_workspace(request)
        if error:
            return error

        metrics = DailyMetric.objects.filter(workspace=workspace).order_by('date')
        performance = PlatformPerformance.objects.filter(workspace=workspace).order_by(
            '-conversions'
        )
        roi = CampaignROI.objects.filter(workspace=workspace).order_by('-roi_multiplier')
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
        revenue_total = revenue_query.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        latest_observed = observation_query.aggregate(latest=Max('observed_at'))['latest']

        # Deliberately NOT the APIResponse envelope: the frontend reads
        # data.trend / data.platform_perf / data.roi at the top level.
        # Reshaping this is a separate change with matching frontend edits.
        return Response(
            {
                "trend": DailyMetricSerializer(metrics, many=True).data,
                "platform_perf": PlatformPerformanceSerializer(performance, many=True).data,
                "roi": CampaignROISerializer(roi, many=True).data,
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
                    "revenue": str(revenue_total),
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
    content = ContentItem.objects.filter(workspace=workspace)
    jobs = PublishingJob.objects.filter(workspace=workspace)
    items = PublishingJobItem.objects.filter(publishing_job__workspace=workspace)
    connections = SocialConnection.objects.filter(workspace=workspace)

    attention = connections.filter(status__in=ACCOUNT_ATTENTION_STATUSES).count()
    attention_hint = None
    if attention:
        attention_hint = "%d need%s attention" % (attention, "s" if attention == 1 else "")

    return [
        {
            "key": "awaiting_review",
            "label": "Awaiting review",
            "value": content.filter(status=ContentItem.Status.PENDING_REVIEW).count(),
            "icon": "CheckCircle2",
            "hint": "Generated content waiting for a decision",
        },
        {
            "key": "approved",
            "label": "Approved, not yet published",
            "value": content.filter(status=ContentItem.Status.APPROVED).count(),
            "icon": "Send",
            "accent": "gold",
        },
        {
            "key": "scheduled",
            "label": "Scheduled posts",
            "value": jobs.filter(status__in=[
                PublishingJob.Status.SCHEDULED, PublishingJob.Status.QUEUED,
            ]).count(),
            "icon": "CalendarClock",
        },
        {
            "key": "published",
            "label": "Published posts",
            "value": items.filter(status=PublishingJobItem.Status.PUBLISHED).count(),
            "icon": "Megaphone",
            "accent": "gold",
            "hint": "Per platform, all time",
        },
        {
            "key": "failed",
            "label": "Failed publishes",
            "value": jobs.filter(status=PublishingJob.Status.FAILED).count(),
            "icon": "AlertTriangle",
        },
        {
            "key": "connected_accounts",
            "label": "Connected accounts",
            "value": connections.filter(status=SocialConnection.Status.CONNECTED).count(),
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
    def post(self, request):
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

        result = sync_performance_task.enqueue(str(run.pk))
        run.task_id = str(result.id)
        run.save(update_fields=['task_id', 'updated_at'])
        return APIResponse(
            success=True, data=PerformanceSyncRunSerializer(run).data,
            status=status.HTTP_202_ACCEPTED,
        )


def _nonnegative_int(value, name):
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a whole number.') from None
    if parsed < 0:
        raise ValueError(f'{name} cannot be negative.')
    return parsed


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
            if spend < 0 or revenue < 0:
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
                'currency': str(request.data.get('currency') or 'USD')[:3].upper(),
                'observed_at': observed_at,
                'source_payload': request.data.get('source_payload') if isinstance(
                    request.data.get('source_payload'), dict
                ) else {},
                'ingested_by': request.user,
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
            if estimated < 0:
                raise ValueError('Estimated value cannot be negative.')
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
            currency=str(request.data.get('currency') or 'USD')[:3].upper(),
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
            if amount < 0:
                raise ValueError('Amount cannot be negative.')
        except (InvalidOperation, TypeError, ValueError):
            return APIResponse(success=False, message='amount must be non-negative.', status=400)
        event, created = RevenueEvent.objects.get_or_create(
            workspace=workspace, source=source, external_event_id=external_id,
            defaults={
                'lead': lead, 'content_item': content,
                'campaign_name': str(request.data.get('campaign_name') or '')[:255],
                'amount': amount,
                'currency': str(request.data.get('currency') or 'USD')[:3].upper(),
                'occurred_at': occurred_at,
                'metadata': request.data.get('metadata') if isinstance(
                    request.data.get('metadata'), dict
                ) else {},
                'recorded_by': request.user,
            },
        )
        if not created and (event.amount != amount or event.currency != str(request.data.get('currency') or 'USD')[:3].upper()):
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
