"""Performance evidence ingestion and rebuildable analytics projections."""
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.learning.models import LearningEvent, SubjectType
from apps.learning.services import record_event_safely
from apps.publishing.models import PublishingJobItem
from apps.social_accounts.integrations.x import XAdapter
from apps.social_accounts.integrations.youtube.youtube import YouTubeAdapter
from apps.social_accounts.models import SocialConnection
from apps.social_accounts.utils.encryption import decrypt_token

from .models import (
    CampaignROI,
    DailyMetric,
    PerformanceObservation,
    PerformanceSyncRun,
    PlatformPerformance,
    RevenueEvent,
)


class PerformanceSyncError(Exception):
    pass


def _latest_observations(workspace):
    """Latest cumulative snapshot per platform post, database-portably."""
    latest = {}
    rows = PerformanceObservation.objects.filter(workspace=workspace).order_by(
        '-observed_at', '-ingested_at'
    )
    for row in rows:
        key = (row.source, row.external_post_id or row.source_record_id)
        if key not in latest:
            latest[key] = row
    return list(latest.values())


@transaction.atomic
def rebuild_workspace_projections(workspace):
    """Rebuild legacy aggregate tables from source observations."""
    latest = _latest_observations(workspace)
    by_day = defaultdict(lambda: defaultdict(int))
    by_platform = defaultdict(lambda: defaultdict(int))
    campaign_spend = defaultdict(lambda: Decimal('0'))

    for row in latest:
        day = row.observed_at.date()
        for field in ('reach', 'engagement', 'conversions'):
            by_day[day][field] += int(getattr(row, field) or 0)
        for field in ('reach', 'engagement', 'clicks', 'conversions'):
            by_platform[row.platform][field] += int(getattr(row, field) or 0)
        if row.campaign_name:
            campaign_spend[row.campaign_name] += row.spend or Decimal('0')

    published_by_day = dict(
        PublishingJobItem.objects.filter(
            publishing_job__workspace=workspace,
            status=PublishingJobItem.Status.PUBLISHED,
            published_at__isnull=False,
        )
        .values('published_at__date')
        .annotate(total=Count('id'))
        .values_list('published_at__date', 'total')
    )
    DailyMetric.objects.filter(workspace=workspace).delete()
    days = set(by_day) | set(published_by_day)
    DailyMetric.objects.bulk_create([
        DailyMetric(
            workspace=workspace,
            date=day,
            reach=by_day[day]['reach'],
            engagement=by_day[day]['engagement'],
            conversions=by_day[day]['conversions'],
            posts_published=int(published_by_day.get(day) or 0),
        )
        for day in sorted(days)
    ])

    PlatformPerformance.objects.filter(workspace=workspace).exclude(
        platform__in=by_platform.keys()
    ).delete()
    revenue_total = RevenueEvent.objects.filter(workspace=workspace).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')
    for platform, metrics in by_platform.items():
        # Revenue without explicit campaign/content attribution stays a
        # workspace total and is never guessed onto a platform.
        PlatformPerformance.objects.update_or_create(
            workspace=workspace,
            platform=platform,
            defaults={
                **metrics,
                'roi_multiplier': 0.0,
            },
        )

    campaign_revenue = {
        row['campaign_name']: row['total'] or Decimal('0')
        for row in RevenueEvent.objects.filter(workspace=workspace)
        .exclude(campaign_name='')
        .values('campaign_name')
        .annotate(total=Sum('amount'))
    }
    campaign_names = set(campaign_spend) | set(campaign_revenue)
    CampaignROI.objects.filter(workspace=workspace).exclude(
        campaign_name__in=campaign_names
    ).delete()
    for name in campaign_names:
        spend = campaign_spend[name]
        revenue = campaign_revenue.get(name, Decimal('0'))
        roi = float(revenue / spend) if spend > 0 else 0.0
        CampaignROI.objects.update_or_create(
            workspace=workspace, campaign_name=name,
            defaults={'roi_multiplier': roi},
        )
    return {'observations': len(latest), 'revenue': str(revenue_total)}


def sync_performance(run_id):
    run = PerformanceSyncRun.objects.select_related(
        'workspace', 'social_connection', 'initiated_by'
    ).get(pk=run_id)
    if run.status not in (PerformanceSyncRun.Status.QUEUED, PerformanceSyncRun.Status.FAILED):
        return {'status': run.status, 'observed': run.observed_count}
    run.status = PerformanceSyncRun.Status.PROCESSING
    run.started_at = timezone.now()
    run.completed_at = None
    run.error = ''
    run.save(update_fields=['status', 'started_at', 'completed_at', 'error', 'updated_at'])

    try:
        connection = run.social_connection
        if connection.status != SocialConnection.Status.CONNECTED:
            raise PerformanceSyncError('The social account must be connected before metrics sync.')
        token = decrypt_token(connection.access_token_encrypted)
        if not token:
            raise PerformanceSyncError('The social account must be reconnected before metrics sync.')
        items = list(
            PublishingJobItem.objects.select_related(
                'publishing_job__content_item__brand'
            ).filter(
                publishing_job__workspace=run.workspace,
                social_connection=connection,
                status=PublishingJobItem.Status.PUBLISHED,
            ).exclude(external_post_id__isnull=True).exclude(external_post_id='')[:100]
        )
        item_by_post = {str(item.external_post_id): item for item in items}
        if connection.platform == SocialConnection.Platform.X:
            rows = XAdapter().fetch_post_metrics(token, item_by_post.keys())
            source = PerformanceObservation.Source.X_API
        elif connection.platform == SocialConnection.Platform.YOUTUBE:
            rows = YouTubeAdapter().fetch_video_metrics(token, item_by_post.keys())
            source = PerformanceObservation.Source.YOUTUBE_API
        else:
            raise PerformanceSyncError(
                f'Performance sync for {connection.get_platform_display()} is not available yet.'
            )

        observed = 0
        now = timezone.now()
        for payload in rows[:100]:
            external_id = str(payload.get('external_post_id') or '')
            item = item_by_post.get(external_id)
            if not item:
                continue
            content = item.publishing_job.content_item
            observation, _ = PerformanceObservation.objects.update_or_create(
                workspace=run.workspace,
                source=source,
                source_record_id=f'{run.pk}:{external_id}',
                defaults={
                    'brand': content.brand if content else None,
                    'content_item': content,
                    'publishing_job_item': item,
                    'social_connection': connection,
                    'platform': connection.platform,
                    'external_post_id': external_id,
                    'impressions': max(0, int(payload.get('impressions') or 0)),
                    'reach': max(0, int(payload.get('reach') or 0)),
                    'engagement': max(0, int(payload.get('engagement') or 0)),
                    'clicks': max(0, int(payload.get('clicks') or 0)),
                    'conversions': max(0, int(payload.get('conversions') or 0)),
                    'observed_at': now,
                    'source_payload': payload.get('source_payload') or {},
                    'ingested_by': run.initiated_by,
                },
            )
            record_event_safely(
                workspace=run.workspace,
                brand=observation.brand,
                event_type=LearningEvent.EventType.PERFORMANCE_OBSERVED,
                outcome=LearningEvent.Outcome.NEUTRAL,
                subject_type=SubjectType.CONTENT_ITEM,
                subject_id=observation.content_item_id,
                source_type=SubjectType.OTHER,
                source_id=observation.pk,
                context={
                    'platform': observation.platform,
                    'reach': observation.reach,
                    'engagement': observation.engagement,
                    'source': observation.source,
                },
                dedupe_key=f'performance:{observation.pk}',
                created_by=run.initiated_by,
            )
            observed += 1
        rebuild_workspace_projections(run.workspace)
        run.status = PerformanceSyncRun.Status.COMPLETED
        run.observed_count = observed
        run.completed_at = timezone.now()
        run.save(update_fields=[
            'status', 'observed_count', 'completed_at', 'updated_at'
        ])
        return {'status': run.status, 'observed': observed}
    except Exception as exc:
        run.status = PerformanceSyncRun.Status.FAILED
        run.error = str(exc)[:1000]
        run.completed_at = timezone.now()
        run.save(update_fields=['status', 'error', 'completed_at', 'updated_at'])
        raise
