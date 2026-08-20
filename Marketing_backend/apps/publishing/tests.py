"""Publishing execution — retry safety and the move onto the worker."""
from unittest.mock import patch

from django.test import TestCase

from apps.marketing.models import MarketingAsset
from apps.publishing.models import PublishingJob, PublishingJobItem
from apps.publishing.services import execute_publishing_job
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace


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
        Both retry paths re-run the whole job. Without the skip, retrying one
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
