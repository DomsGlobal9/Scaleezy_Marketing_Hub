"""Delayed publishing must honour current authority, with bounded history reads."""
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.common.testing import TenantFixtureMixin
from apps.content.models import ContentItem
from apps.marketing.models import MarketingAsset
from apps.publishing.models import PublishingJob, PublishingJobItem
from apps.publishing.services import execute_publishing_job
from apps.social_accounts.models import SocialConnection, SocialAccountSettings
from apps.workspaces.models import WorkspaceMember


class PublishingClosureTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Publishing', 'publishing')
        self.user, self.client = self.authenticate_as(self.workspace, WorkspaceMember.Role.MANAGER, 'manager')
        self.headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.pk)}
        self.asset = MarketingAsset.objects.create(workspace=self.workspace, file_name='saved.png', source='MANUAL_UPLOAD')
        self.content = ContentItem.objects.create(workspace=self.workspace, asset=self.asset, status='APPROVED', headline='Approved')
        self.social = SocialConnection.objects.create(workspace=self.workspace, platform='X', external_account_id='x', account_name='X', status='CONNECTED')
        self.job = PublishingJob.objects.create(workspace=self.workspace, asset=self.asset, content_item=self.content, status='QUEUED')
        self.item = PublishingJobItem.objects.create(publishing_job=self.job, social_connection=self.social, status='QUEUED')

    def test_queued_account_and_workspace_changes_block_dispatch_without_auto_retry(self):
        SocialAccountSettings.objects.create(social_connection=self.social, automatic_retry_enabled=True)
        for fields, code in (
            ({'publishing_enabled': False}, 'PUBLISHING_DISABLED'),
            ({'status': 'DISCONNECTED'}, 'SOCIAL_ACCOUNT_NOT_READY'),
            ({'reauthorization_required': True}, 'SOCIAL_ACCOUNT_NOT_READY'),
        ):
            SocialConnection.objects.filter(pk=self.social.pk).update(publishing_enabled=True, status='CONNECTED', reauthorization_required=False)
            SocialConnection.objects.filter(pk=self.social.pk).update(**fields)
            with self.subTest(fields=fields), patch('apps.publishing.services._publish_to_x') as provider:
                execute_publishing_job(str(self.job.pk))
                provider.assert_not_called()
                self.item.refresh_from_db()
                self.assertEqual(self.item.status, 'FAILED')
                self.assertEqual(self.item.error_code, code)
        SocialConnection.objects.filter(pk=self.social.pk).update(publishing_enabled=True, status='CONNECTED', reauthorization_required=False)
        self.workspace.status = 'SUSPENDED'
        self.workspace.save(update_fields=['status'])
        with patch('apps.publishing.services._publish_to_x') as provider:
            execute_publishing_job(str(self.job.pk))
        provider.assert_not_called()
        self.item.refresh_from_db()
        self.assertEqual(self.item.error_code, 'WORKSPACE_INACTIVE')

    def test_cancelled_job_and_item_stay_cancelled(self):
        self.job.status = 'CANCELLED'
        self.job.save(update_fields=['status'])
        with patch('apps.publishing.services._publish_to_x') as provider:
            execute_publishing_job(str(self.job.pk))
        provider.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'CANCELLED')
        self.job.status = 'QUEUED'
        self.job.save(update_fields=['status'])
        self.item.status = 'CANCELLED'
        self.item.save(update_fields=['status'])
        with patch('apps.publishing.services._publish_to_x') as provider:
            execute_publishing_job(str(self.job.pk))
        provider.assert_not_called()
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'CANCELLED')

    def test_manual_retry_cannot_revive_cancelled_job(self):
        self.job.status = 'CANCELLED'
        self.job.save(update_fields=['status'])
        self.item.status = 'FAILED'
        self.item.save(update_fields=['status'])
        response = self.client.post(f'/api/marketing/publishing/jobs/items/{self.item.pk}/retry/', {}, format='json', **self.headers)
        self.assertEqual(response.status_code, 409)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'CANCELLED')

    def test_history_queries_are_constant_and_selected_client_only(self):
        other = self.make_workspace('Other', 'other')
        foreign = MarketingAsset.objects.create(workspace=other, file_name='foreign.png', source='MANUAL_UPLOAD')
        PublishingJob.objects.create(workspace=other, asset=foreign)
        url = '/api/marketing/publishing/jobs/?page_size=25'
        self.client.get(url, **self.headers)
        with CaptureQueriesContext(connection) as small:
            self.client.get(url, **self.headers)
        for index in range(24):
            content = ContentItem.objects.create(workspace=self.workspace, asset=self.asset, headline=str(index), status='APPROVED')
            job = PublishingJob.objects.create(workspace=self.workspace, asset=self.asset, content_item=content)
            PublishingJobItem.objects.create(publishing_job=job, social_connection=self.social)
        with CaptureQueriesContext(connection) as large:
            response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 25)
        self.assertEqual(len(small), len(large))
        self.assertLessEqual(len(large), 4)
