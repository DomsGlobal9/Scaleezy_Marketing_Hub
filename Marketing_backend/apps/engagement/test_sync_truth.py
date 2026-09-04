from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.tasks import TaskResultStatus
from django.test import TestCase
from rest_framework.test import APIClient

from apps.brands.models import Brand
from apps.jobs.models import TaskRun
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

from .models import EngagementSyncRun


class EngagementSyncTruthTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(customer_id='sync-truth', workspace_name='Truth')
        self.user = get_user_model().objects.create_user(username='sync-editor')
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.user, role='EDITOR')
        self.brand = Brand.objects.create(workspace=self.workspace, name='Truth')
        self.connection = SocialConnection.objects.create(workspace=self.workspace, platform='X',
            external_account_id='sync-x', account_name='Truth', status='CONNECTED')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.pk)}

    def run_row(self):
        return EngagementSyncRun.objects.create(workspace=self.workspace, brand=self.brand,
            social_connection=self.connection, status='FAILED')

    @patch('apps.engagement.tasks.sync_engagement_task')
    def test_enqueue_failure_is_honest_and_recoverable(self, task):
        task.enqueue.side_effect = RuntimeError('queue down')
        response = self.client.post('/api/marketing/engagement/sync-runs/',
            {'brand': str(self.brand.pk), 'social_connection': str(self.connection.pk)},
            format='json', **self.headers)
        self.assertEqual(response.status_code, 503)
        run = EngagementSyncRun.objects.get()
        self.assertEqual(run.status, 'FAILED')
        self.assertIsNotNone(run.completed_at)
        self.assertNotIn('queue down', run.error)

    @patch('apps.engagement.tasks.sync_engagement_task')
    def test_retry_dispatch_failure_is_not_left_queued(self, task):
        task.enqueue.side_effect = RuntimeError('queue down')
        run = self.run_row()
        response = self.client.post(f'/api/marketing/engagement/sync-runs/{run.pk}/retry/',
            format='json', **self.headers)
        self.assertEqual(response.status_code, 503)
        run.refresh_from_db()
        self.assertEqual(run.status, 'FAILED')
        self.assertIsNotNone(run.completed_at)

    @patch('apps.engagement.tasks.sync_engagement_task')
    def test_background_owned_retry_cannot_be_manually_duplicated(self, task):
        run = self.run_row()
        TaskRun.objects.create(id='owned-inbox-retry', task_path='apps.engagement.tasks.sync_engagement_task',
            args=[str(run.pk)], status=TaskResultStatus.READY, attempts=1)
        response = self.client.get(f'/api/marketing/engagement/sync-runs/{run.pk}/', **self.headers)
        self.assertEqual(response.json()['execution'],
                         {'state': 'RETRY_PENDING', 'terminal': False, 'retry_allowed': False})
        response = self.client.post(f'/api/marketing/engagement/sync-runs/{run.pk}/retry/',
            format='json', **self.headers)
        self.assertEqual(response.status_code, 409)
        task.enqueue.assert_not_called()

    def test_sync_detail_is_scoped_and_list_filters_brand(self):
        run = self.run_row()
        other_brand = Brand.objects.create(workspace=self.workspace, name='Other brand')
        response = self.client.get(f'/api/marketing/engagement/sync-runs/?brand_id={other_brand.pk}', **self.headers)
        self.assertEqual(response.json(), [])
        other = MarketingWorkspace.objects.create(customer_id='sync-other', workspace_name='Other')
        WorkspaceMember.objects.create(workspace=other, user=self.user, role='VIEWER')
        response = self.client.get(f'/api/marketing/engagement/sync-runs/{run.pk}/',
                                  HTTP_X_WORKSPACE_ID=str(other.pk))
        self.assertEqual(response.status_code, 404)

    @patch('apps.engagement.tasks.sync_engagement_task')
    def test_fast_worker_completion_is_not_overwritten_by_retry_metadata(self, task):
        run = self.run_row()
        def finish(run_id):
            EngagementSyncRun.objects.filter(pk=run_id).update(status='COMPLETED', imported_count=3)
            return SimpleNamespace(id='fast-worker')
        task.enqueue.side_effect = finish
        response = self.client.post(f'/api/marketing/engagement/sync-runs/{run.pk}/retry/',
            format='json', **self.headers)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['data']['execution']['state'], 'COMPLETED')
        run.refresh_from_db()
        self.assertEqual(run.status, 'COMPLETED')
