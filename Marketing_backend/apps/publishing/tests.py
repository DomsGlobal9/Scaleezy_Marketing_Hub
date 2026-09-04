"""Publishing execution — retry safety and the move onto the worker."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from apps.content.models import ContentItem
from apps.marketing.models import MarketingAsset
from apps.publishing.models import PublishingJob, PublishingJobItem
from apps.publishing.services import execute_publishing_job
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember


User = get_user_model()


class ExecuteJobTests(TestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.asset = MarketingAsset.objects.create(
            workspace=self.ws, file_name='poster.jpg', source='MANUAL_UPLOAD',
            file_url='https://storage.test/poster.jpg',
        )
        self.job = PublishingJob.objects.create(
            workspace=self.ws, asset=self.asset, caption='Hello',
            status=PublishingJob.Status.QUEUED,
        )

    def connection(self, platform, external_id):
        return SocialConnection.objects.create(
            workspace=self.ws, platform=platform, external_account_id=external_id,
            account_name=f"{platform} account", status='CONNECTED',
        )

    def item(self, platform, external_id, status=PublishingJobItem.Status.QUEUED, **kwargs):
        return PublishingJobItem.objects.create(
            publishing_job=self.job,
            social_connection=self.connection(platform, external_id),
            status=status,
            **kwargs,
        )

    def test_an_already_published_item_is_never_posted_again(self):
        """
        Retrying an item re-runs its whole job. Without the skip, retrying one
        failed channel posts a second copy to every channel that worked.
        """
        published = self.item(
            'X', 'x1', status=PublishingJobItem.Status.PUBLISHED,
            external_post_id='already-live',
        )
        self.item('LINKEDIN', 'li1')

        with patch('apps.publishing.services._publish_to_x') as to_x, \
                patch('apps.publishing.services._publish_to_linkedin') as to_linkedin:
            execute_publishing_job(str(self.job.id))

        to_x.assert_not_called()
        to_linkedin.assert_called_once()

        published.refresh_from_db()
        self.assertEqual(published.external_post_id, 'already-live')

    def test_a_job_where_everything_is_already_published_is_published(self):
        self.item('X', 'x1', status=PublishingJobItem.Status.PUBLISHED)
        self.item('LINKEDIN', 'li1', status=PublishingJobItem.Status.PUBLISHED)

        execute_publishing_job(str(self.job.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, PublishingJob.Status.PUBLISHED)

    def test_successful_job_marks_its_approved_content_published(self):
        content = ContentItem.objects.create(
            workspace=self.ws,
            asset=self.asset,
            status=ContentItem.Status.APPROVED,
            headline='Approved version',
        )
        self.job.content_item = content
        self.job.save(update_fields=['content_item'])
        self.item('X', 'x1', status=PublishingJobItem.Status.PUBLISHED)

        execute_publishing_job(str(self.job.id))

        content.refresh_from_db()
        self.assertEqual(content.status, ContentItem.Status.PUBLISHED)

    def test_a_partial_result_is_reported_as_partial(self):
        self.item('X', 'x1', status=PublishingJobItem.Status.PUBLISHED)
        self.item('LINKEDIN', 'li1')

        def fail(item, job):
            item.status = PublishingJobItem.Status.FAILED
            item.save()

        with patch('apps.publishing.services._publish_to_linkedin', side_effect=fail):
            execute_publishing_job(str(self.job.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, PublishingJob.Status.PARTIALLY_PUBLISHED)

    def test_an_unsupported_platform_fails_only_its_own_item(self):
        self.item('TIKTOK', 'tt1')
        self.item('LINKEDIN', 'li1')

        def succeed(item, job):
            item.status = PublishingJobItem.Status.PUBLISHED
            item.save()

        with patch('apps.publishing.services._publish_to_linkedin', side_effect=succeed):
            execute_publishing_job(str(self.job.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, PublishingJob.Status.PARTIALLY_PUBLISHED)

    def test_a_missing_job_is_a_no_op(self):
        execute_publishing_job('00000000-0000-0000-0000-000000000000')


class PublishingRoleTests(APITestCase):
    """Only a marketing manager may make something reach an audience."""

    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(
            customer_id='role-check', workspace_name='Publishing roles'
        )
        self.users = {}
        for role in (
            WorkspaceMember.Role.VIEWER,
            WorkspaceMember.Role.EDITOR,
            WorkspaceMember.Role.MANAGER,
        ):
            user = User.objects.create_user(username=role.lower(), password='pw')
            WorkspaceMember.objects.create(workspace=self.ws, user=user, role=role)
            self.users[role] = user

        self.asset = MarketingAsset.objects.create(
            workspace=self.ws,
            file_name='approved.jpg',
            source='MANUAL_UPLOAD',
            file_url='https://storage.test/approved.jpg',
        )
        self.content = ContentItem.objects.create(
            workspace=self.ws,
            asset=self.asset,
            headline='Approved version',
            caption='Reviewed caption',
            hashtags='#reviewed',
            status=ContentItem.Status.APPROVED,
        )
        self.connection = SocialConnection.objects.create(
            workspace=self.ws,
            platform='X',
            external_account_id='role-check-x',
            account_name='Publishing X',
            status=SocialConnection.Status.CONNECTED,
        )
        self.job = PublishingJob.objects.create(
            workspace=self.ws,
            asset=self.asset,
            content_item=self.content,
            caption='Original caption',
            status=PublishingJob.Status.FAILED,
        )
        self.item = PublishingJobItem.objects.create(
            publishing_job=self.job,
            social_connection=self.connection,
            status=PublishingJobItem.Status.FAILED,
        )

    def authenticate_as(self, role):
        self.client.force_authenticate(user=self.users[role])
        self.client.credentials(HTTP_X_WORKSPACE_ID=str(self.ws.id))

    def publish_payload(self):
        return {
            'workspace_id': str(self.ws.id),
            'asset_id': str(self.asset.id),
            'content_item_id': str(self.content.id),
            'publish_mode': PublishingJob.PublishMode.NOW,
            'social_connection_ids': [str(self.connection.id)],
        }

    def test_history_pages_newest_first_when_a_page_size_is_asked_for(self):
        """The history table pages with ?page_size=; order must be stable."""
        newer = PublishingJob.objects.create(
            workspace=self.ws,
            asset=self.asset,
            content_item=self.content,
            caption='Newer job',
            status=PublishingJob.Status.PUBLISHED,
        )
        # Keep this ordering assertion independent of SQLite clock precision.
        PublishingJob.objects.filter(pk=newer.pk).update(
            created_at=self.job.created_at + timedelta(seconds=1)
        )
        self.authenticate_as(WorkspaceMember.Role.VIEWER)

        response = self.client.get('/api/marketing/publishing/jobs/?page_size=1')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertIsNotNone(response.data['next'])
        self.assertEqual(response.data['results'][0]['id'], str(newer.id))

    def test_viewer_and_editor_keep_read_access_but_cannot_create(self):
        for role in (WorkspaceMember.Role.VIEWER, WorkspaceMember.Role.EDITOR):
            with self.subTest(role=role):
                self.authenticate_as(role)
                self.assertEqual(
                    self.client.get('/api/marketing/publishing/jobs/').status_code,
                    status.HTTP_200_OK,
                )
                self.assertEqual(
                    self.client.get(
                        f'/api/marketing/publishing/jobs/{self.job.id}/'
                    ).status_code,
                    status.HTTP_200_OK,
                )
                before = PublishingJob.objects.count()
                response = self.client.post(
                    '/api/marketing/publishing/jobs/', self.publish_payload(), format='json'
                )
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(PublishingJob.objects.count(), before)

    @patch('apps.publishing.views.publish_job')
    def test_manager_can_create_an_immediate_publishing_job(self, publish_task):
        self.authenticate_as(WorkspaceMember.Role.MANAGER)

        response = self.client.post(
            '/api/marketing/publishing/jobs/', self.publish_payload(), format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        created = PublishingJob.objects.exclude(pk=self.job.pk).get()
        self.assertEqual(created.created_by, self.users[WorkspaceMember.Role.MANAGER])
        self.assertEqual(created.workspace, self.ws)
        self.assertEqual(
            created.caption,
            'Approved version\n\nReviewed caption\n\n#reviewed',
        )
        publish_task.enqueue.assert_called_once_with(str(created.id))

    def test_viewer_and_editor_cannot_patch_or_delete_jobs(self):
        for role in (WorkspaceMember.Role.VIEWER, WorkspaceMember.Role.EDITOR):
            with self.subTest(role=role, action='patch'):
                self.authenticate_as(role)
                response = self.client.patch(
                    f'/api/marketing/publishing/jobs/{self.job.id}/',
                    {'caption': 'Changed'},
                    format='json',
                )
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.job.refresh_from_db()
                self.assertEqual(self.job.caption, 'Original caption')

            with self.subTest(role=role, action='delete'):
                response = self.client.delete(
                    f'/api/marketing/publishing/jobs/{self.job.id}/'
                )
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertTrue(PublishingJob.objects.filter(pk=self.job.pk).exists())

    def test_manager_cannot_rewrite_or_delete_a_reviewed_job(self):
        self.authenticate_as(WorkspaceMember.Role.MANAGER)
        response = self.client.patch(
            f'/api/marketing/publishing/jobs/{self.job.id}/',
            {
                'caption': 'Manager changed this',
                'content_item': None,
                'workspace': str(self.ws.id),
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED, response.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.caption, 'Original caption')
        self.assertEqual(self.job.content_item, self.content)

        response = self.client.delete(f'/api/marketing/publishing/jobs/{self.job.id}/')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(PublishingJob.objects.filter(pk=self.job.pk).exists())

    @patch('apps.publishing.views.publish_job')
    def test_request_caption_cannot_bypass_the_reviewed_copy(self, publish_task):
        self.authenticate_as(WorkspaceMember.Role.MANAGER)
        payload = self.publish_payload()
        payload['caption'] = 'Unreviewed replacement copy'

        response = self.client.post(
            '/api/marketing/publishing/jobs/', payload, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        created = PublishingJob.objects.exclude(pk=self.job.pk).get()
        self.assertEqual(
            created.caption,
            'Approved version\n\nReviewed caption\n\n#reviewed',
        )
        self.assertNotIn('Unreviewed replacement', created.caption)

    @patch('apps.publishing.views.publish_job')
    def test_viewer_and_editor_cannot_retry_an_item(self, publish_task):
        for role in (WorkspaceMember.Role.VIEWER, WorkspaceMember.Role.EDITOR):
            with self.subTest(role=role):
                self.authenticate_as(role)
                response = self.client.post(
                    f'/api/marketing/publishing/jobs/items/{self.item.id}/retry/',
                    {},
                    format='json',
                )
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.item.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.item.status, PublishingJobItem.Status.FAILED)
        self.assertEqual(self.job.status, PublishingJob.Status.FAILED)
        publish_task.enqueue.assert_not_called()

    @patch('apps.publishing.views.publish_job')
    def test_manager_can_retry_a_failed_item(self, publish_task):
        self.authenticate_as(WorkspaceMember.Role.MANAGER)

        response = self.client.post(
            f'/api/marketing/publishing/jobs/items/{self.item.id}/retry/', {}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.item.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.item.status, PublishingJobItem.Status.QUEUED)
        self.assertEqual(self.job.status, PublishingJob.Status.PUBLISHING)
        publish_task.enqueue.assert_called_once_with(str(self.job.id))
