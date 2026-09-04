from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.tasks import TaskResultStatus
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.brands.models import Brand
from apps.jobs.models import TaskRun
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

from .measurements import measured_fields, summarize
from .models import CampaignROI, PerformanceObservation, PerformanceSyncRun, RevenueEvent
from .serializers import PerformanceObservationSerializer, PerformanceSyncRunSerializer
from .services import rebuild_workspace_projections


class AnalyticsTruthTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(customer_id='truth', workspace_name='Truth')
        self.other = MarketingWorkspace.objects.create(customer_id='other-truth', workspace_name='Other')
        self.user = get_user_model().objects.create_user(username='truth-editor')
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.user, role='EDITOR')
        self.brand = Brand.objects.create(workspace=self.workspace, name='Truth')
        self.connection = SocialConnection.objects.create(
            workspace=self.workspace, platform='X', external_account_id='truth-x',
            account_name='Truth X', status='CONNECTED',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.pk)}

    def observation(self, **values):
        defaults = dict(workspace=self.workspace, source='AUDITABLE_IMPORT',
                        source_record_id=f'row-{PerformanceObservation.objects.count()}',
                        platform='X', observed_at=timezone.now())
        defaults.update(values)
        return PerformanceObservation.objects.create(**defaults)

    def import_metric(self, **values):
        return self.client.post('/api/marketing/analytics/performance/import/', {
            'source_record_id': 'intake', 'platform': 'X', 'observed_at': timezone.now().isoformat(),
            **values,
        }, format='json', **self.headers)

    def test_explicit_zero_is_measured_but_omitted_null_and_blank_are_not(self):
        response = self.import_metric(reach=0, engagement=None, clicks='',
                                      source_payload={'measured_fields': ['conversions']})
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()['data']
        self.assertEqual(data['reach'], 0)
        self.assertIsNone(data['engagement'])
        self.assertIsNone(data['clicks'])
        self.assertIsNone(data['conversions'])
        self.assertEqual(data['measured_fields'], ['reach'])

    def test_legacy_positive_values_remain_measured(self):
        row = self.observation(reach=9, impressions=7, source='YOUTUBE_API')
        data = PerformanceObservationSerializer(row).data
        self.assertEqual(data['reach'], 9)
        self.assertEqual(data['impressions'], 7)
        self.assertIsNone(data['clicks'])

    def test_source_reported_zero_is_measured_without_inventing_clicks(self):
        row = self.observation(source='X_API', source_payload={
            'public_metrics': {'impression_count': 0, 'like_count': 0},
        })
        self.assertEqual(measured_fields(row), {'impressions', 'reach', 'engagement'})
        row.source = 'YOUTUBE_API'
        row.source_payload = {'statistics': {'viewCount': '0', 'likeCount': '0'}}
        self.assertEqual(measured_fields(row), {'reach', 'engagement'})

    def test_partial_total_is_unavailable_with_coverage_and_recorded_zero_is_zero(self):
        known = self.observation(source_payload={'measured_fields': ['reach']})
        unknown = self.observation()
        total = summarize([known, unknown])
        self.assertIsNone(total['reach'])
        self.assertEqual(total['measurement_coverage']['reach'], {'measured': 1, 'total': 2})
        self.assertEqual(summarize([known])['reach'], 0)
        self.assertIsNone(summarize([])['reach'])

    def test_dashboard_groups_currency_without_cross_tenant_or_fictitious_fx(self):
        for workspace, currency, amount in ((self.workspace, 'USD', '10'),
                                             (self.workspace, 'EUR', '20'),
                                             (self.other, 'USD', '999')):
            RevenueEvent.objects.create(workspace=workspace, source='test',
                external_event_id=currency, amount=amount, currency=currency, occurred_at=timezone.now())
        response = self.client.get('/api/marketing/analytics/dashboard/', **self.headers)
        summary = response.json()['summary']
        self.assertIsNone(summary['revenue'])
        self.assertIsNone(summary['revenue_currency'])
        self.assertEqual({row['currency']: Decimal(row['amount']) for row in summary['revenue_by_currency']},
                         {'EUR': Decimal('20'), 'USD': Decimal('10')})

    def test_campaign_roi_is_not_projected_across_currencies(self):
        self.observation(campaign_name='Launch', spend=10, currency='USD')
        RevenueEvent.objects.create(workspace=self.workspace, source='test', external_event_id='eur',
            campaign_name='Launch', amount=20, currency='EUR', occurred_at=timezone.now())
        CampaignROI.objects.create(workspace=self.workspace, campaign_name='Launch', roi_multiplier=2)
        dashboard = self.client.get('/api/marketing/analytics/dashboard/', **self.headers).json()
        self.assertEqual({row['currency'] for row in dashboard['roi']}, {'USD', 'EUR'})
        self.assertTrue(all(row['roi_multiplier'] is None for row in dashboard['roi']))
        rebuild_workspace_projections(self.workspace)
        self.assertFalse(CampaignROI.objects.filter(workspace=self.workspace).exists())

    def test_same_currency_campaign_roi_is_preserved(self):
        self.observation(campaign_name='Launch', spend=10, currency='USD')
        RevenueEvent.objects.create(workspace=self.workspace, source='test', external_event_id='usd',
            campaign_name='Launch', amount=20, currency='USD', occurred_at=timezone.now())
        rebuild_workspace_projections(self.workspace)
        self.assertEqual(CampaignROI.objects.get().roi_multiplier, 2)

    def test_malformed_number_and_currency_are_rejected(self):
        for values in ({'reach': 1.5}, {'spend': 'Infinity'}, {'currency': 'US dollars'}):
            with self.subTest(values=values):
                self.assertEqual(self.import_metric(**values).status_code, 400)
        self.assertFalse(PerformanceObservation.objects.exists())

    def test_sync_detail_is_workspace_scoped_and_active_retry_is_not_terminal(self):
        run = PerformanceSyncRun.objects.create(workspace=self.workspace, social_connection=self.connection, status='FAILED')
        task = TaskRun.objects.create(id='analytics-retry', task_path='apps.analytics.tasks.sync_performance_task',
            args=[str(run.pk)], status=TaskResultStatus.READY, attempts=1)
        url = f'/api/marketing/analytics/performance/sync/{run.pk}/'
        response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['execution'],
                         {'state': 'RETRY_PENDING', 'terminal': False, 'retry_allowed': False})
        WorkspaceMember.objects.create(workspace=self.other, user=self.user, role='VIEWER')
        self.assertEqual(self.client.get(url, HTTP_X_WORKSPACE_ID=str(self.other.pk)).status_code, 404)
        task.status = TaskResultStatus.FAILED
        task.save(update_fields=['status'])
        self.assertTrue(PerformanceSyncRunSerializer(run).data['execution']['terminal'])

    def test_app_completion_waits_for_task_owner_to_finish(self):
        run = PerformanceSyncRun.objects.create(workspace=self.workspace, social_connection=self.connection, status='COMPLETED')
        task = TaskRun.objects.create(id='analytics-running', task_path='apps.analytics.tasks.sync_performance_task',
            args=[str(run.pk)], status=TaskResultStatus.RUNNING)
        self.assertFalse(PerformanceSyncRunSerializer(run).data['execution']['terminal'])
        task.status = TaskResultStatus.SUCCESSFUL
        task.save(update_fields=['status'])
        self.assertEqual(PerformanceSyncRunSerializer(run).data['execution']['state'], 'COMPLETED')

    @patch('apps.analytics.tasks.sync_performance_task')
    def test_enqueue_failure_returns_service_failure_and_no_stranded_queue(self, task):
        task.enqueue.side_effect = RuntimeError('queue down')
        response = self.client.post('/api/marketing/analytics/performance/sync/',
            {'social_connection': str(self.connection.pk)}, format='json', **self.headers)
        self.assertEqual(response.status_code, 503)
        run = PerformanceSyncRun.objects.get()
        self.assertEqual(run.status, 'FAILED')
        self.assertIsNotNone(run.completed_at)
        self.assertNotIn('queue down', run.error)
