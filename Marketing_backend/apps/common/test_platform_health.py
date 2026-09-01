"""
Health signals that mean what they say.

The defect these close: a console showing "0 knowledge failures" when nothing
in the codebase can produce a knowledge failure, and "0 brand brains failing"
when nothing recorded a compile outcome. A tile reading zero because the
sensor is disconnected is worse than no tile, because it is indistinguishable
from good news.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.brands.models import Brand
from apps.brands.services.brand_brain import (
    rebuild_brand_brain,
    rebuild_brand_brain_safely,
)
from apps.common.permissions import LAST_ACTIVE_RESOLUTION, touch_last_active
from apps.common.platform_health import Signal, platform_health, platform_signals
from apps.engagement.models import EngagementItem, EngagementSyncRun
from apps.inspirations.models import BrandInspiration, ResearchRun
from apps.knowledge.models import BrandSource
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember


def signal(key, signals=None):
    return next(s for s in (signals or platform_signals()) if s.key == key)


class BrainCompileHealthTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='c1', workspace_name='Acme'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme', is_default=True,
            status=Brand.Status.ACTIVE,
        )

    def test_a_successful_compile_is_recorded_on_the_brand(self):
        rebuild_brand_brain(self.brand)
        self.brand.refresh_from_db()
        self.assertIsNotNone(self.brand.brain_compiled_at)
        self.assertTrue(self.brand.brain_version)
        self.assertEqual(self.brand.brain_last_error, '')
        self.assertFalse(self.brand.brain_is_stale)

    def test_a_failed_compile_is_recorded_rather_than_only_logged(self):
        with patch(
            'apps.brands.services.brand_brain.compile_brand_brain',
            side_effect=RuntimeError('compiler exploded'),
        ):
            self.assertIsNone(rebuild_brand_brain_safely(self.brand))

        self.brand.refresh_from_db()
        self.assertIn('compiler exploded', self.brand.brain_last_error)
        self.assertIsNotNone(self.brand.brain_failed_at)
        self.assertTrue(self.brand.brain_is_stale)
        # The caller's change is never rolled back by a compile failure.
        self.assertTrue(Brand.objects.filter(pk=self.brand.pk).exists())

    def test_the_failure_signal_counts_it_and_clears_on_recovery(self):
        self.assertEqual(signal('brain_compile_failures').value, 0)

        with patch(
            'apps.brands.services.brand_brain.compile_brand_brain',
            side_effect=RuntimeError('boom'),
        ):
            rebuild_brand_brain_safely(self.brand)
        self.assertEqual(signal('brain_compile_failures').value, 1)

        rebuild_brand_brain(self.brand)
        self.brand.refresh_from_db()
        self.assertFalse(self.brand.brain_is_stale)
        self.assertEqual(signal('brain_compile_failures').value, 0)


class LastActiveTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='c1', workspace_name='Acme'
        )
        self.member = WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=User.objects.create_user(username='u@x.test', password='pw'),
            role=WorkspaceMember.Role.OWNER,
        )

    def test_activity_is_recorded(self):
        self.assertIsNone(self.member.last_active_at)
        touch_last_active(self.member)
        self.member.refresh_from_db()
        self.assertIsNotNone(self.member.last_active_at)

    def test_a_fresh_timestamp_is_not_rewritten_on_every_request(self):
        touch_last_active(self.member)
        self.member.refresh_from_db()
        first = self.member.last_active_at

        for _ in range(5):
            touch_last_active(self.member)
        self.member.refresh_from_db()
        self.assertEqual(self.member.last_active_at, first)

    def test_a_stale_timestamp_is_refreshed(self):
        stale = timezone.now() - LAST_ACTIVE_RESOLUTION * 2
        WorkspaceMember.objects.filter(pk=self.member.pk).update(last_active_at=stale)
        self.member.refresh_from_db()

        touch_last_active(self.member)
        self.member.refresh_from_db()
        self.assertGreater(self.member.last_active_at, stale)

    def test_inactive_clients_is_a_real_query_now(self):
        # No activity ever recorded -> the client counts as inactive.
        self.assertEqual(signal('inactive_clients').value, 1)
        touch_last_active(self.member)
        self.assertEqual(signal('inactive_clients').value, 0)


class ProcessingHealthTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='processing', workspace_name='Processing Co'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace,
            name='Processing Co',
            is_default=True,
            status=Brand.Status.ACTIVE,
        )

    def test_processing_states_are_live_numeric_signals(self):
        BrandSource.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            title='Broken source',
            status=BrandSource.SourceStatus.FAILED,
        )
        BrandSource.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            title='Review source',
            status=BrandSource.SourceStatus.NEEDS_REVIEW,
        )
        BrandInspiration.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            title='Broken inspiration',
            analysis_status=BrandInspiration.AnalysisStatus.FAILED,
        )
        ResearchRun.objects.create(
            workspace=self.workspace, brand=self.brand, query='retail posters',
            status=ResearchRun.Status.FAILED, error='provider unavailable',
        )
        connection = SocialConnection.objects.create(
            workspace=self.workspace,
            platform=SocialConnection.Platform.X,
            external_account_id='x-health',
            account_name='X Health',
            status=SocialConnection.Status.CONNECTED,
        )
        EngagementSyncRun.objects.create(
            workspace=self.workspace, brand=self.brand, social_connection=connection,
            status=EngagementSyncRun.Status.FAILED, error='sync unavailable',
        )
        EngagementItem.objects.create(
            workspace=self.workspace, brand=self.brand, social_connection=connection,
            platform=connection.platform, kind=EngagementItem.Kind.MENTION,
            external_id='mention-health', body='Help', occurred_at=timezone.now(),
            draft_status=EngagementItem.DraftStatus.FAILED,
        )
        stale_send = EngagementItem.objects.create(
            workspace=self.workspace, brand=self.brand, social_connection=connection,
            platform=connection.platform, kind=EngagementItem.Kind.MENTION,
            external_id='mention-stale', body='Still sending', occurred_at=timezone.now(),
            status=EngagementItem.Status.SENDING,
        )
        EngagementItem.objects.filter(pk=stale_send.pk).update(
            updated_at=timezone.now() - timedelta(hours=1)
        )

        payload = platform_health()
        by_key = {row['key']: row for row in payload['signals']}
        for key in (
            'knowledge_failed',
            'knowledge_needs_review',
            'inspiration_analysis_failed',
            'creative_research_failed',
            'engagement_sync_failed',
            'engagement_drafts_failed',
            'engagement_sends_stale',
        ):
            self.assertTrue(by_key[key]['live'], key)
            self.assertEqual(by_key[key]['value'], 1, key)
            self.assertEqual(by_key[key]['display'], '1', key)
            self.assertEqual(by_key[key]['reason'], '', key)
            self.assertNotIn(key, payload['unmonitored'])

        raised = {
            row['key'] for row in payload['signals']
            if row['live'] and row['actionable'] and (row['value'] or 0) > 0
        }
        self.assertTrue({
            'knowledge_failed',
            'knowledge_needs_review',
            'inspiration_analysis_failed',
            'creative_research_failed',
            'engagement_sync_failed',
            'engagement_drafts_failed',
            'engagement_sends_stale',
        }.issubset(raised))
        self.assertEqual(payload['needs_attention'], len(raised))

    def test_inactive_and_revoked_work_is_not_actionable(self):
        inactive = MarketingWorkspace.objects.create(
            customer_id='inactive',
            workspace_name='Inactive Co',
            status=MarketingWorkspace.Status.ARCHIVED,
        )
        inactive_brand = Brand.objects.create(
            workspace=inactive,
            name='Inactive Co',
            is_default=True,
            status=Brand.Status.ACTIVE,
        )
        BrandSource.objects.create(
            workspace=inactive,
            brand=inactive_brand,
            title='Inactive failure',
            status=BrandSource.SourceStatus.FAILED,
        )
        BrandInspiration.objects.create(
            workspace=inactive,
            brand=inactive_brand,
            title='Inactive inspiration failure',
            analysis_status=BrandInspiration.AnalysisStatus.FAILED,
        )

        archived_source = BrandSource.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            title='Revoked source',
            status=BrandSource.SourceStatus.ARCHIVED,
        )
        BrandInspiration.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            source=archived_source,
            title='Revoked inspiration failure',
            analysis_status=BrandInspiration.AnalysisStatus.FAILED,
        )
        BrandInspiration.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            title='Archived inspiration failure',
            analysis_status=BrandInspiration.AnalysisStatus.FAILED,
            lifecycle_status=BrandInspiration.LifecycleStatus.ARCHIVED,
        )

        self.assertEqual(signal('knowledge_failed').value, 0)
        self.assertEqual(signal('inspiration_analysis_failed').value, 0)


class UnmonitoredSignalTests(TestCase):
    """A dead sensor must not read zero; newly connected sensors must."""

    def test_processing_signals_are_live_even_when_zero(self):
        payload = platform_health()
        by_key = {s['key']: s for s in payload['signals']}

        for key in (
            'knowledge_failed', 'knowledge_needs_review',
            'inspiration_analysis_failed', 'creative_research_failed',
            'engagement_sync_failed', 'engagement_drafts_failed',
            'engagement_sends_stale',
        ):
            row = by_key[key]
            self.assertTrue(row['live'], key)
            self.assertEqual(row['value'], 0, key)
            self.assertEqual(row['display'], '0', key)
            self.assertEqual(row['reason'], '', key)
            self.assertNotIn(key, payload['unmonitored'])

    def test_a_dead_sensor_never_counts_towards_needs_attention(self):
        with patch(
            'apps.common.platform_health.platform_signals',
            return_value=[
                Signal('live', 'Live', 1, True),
                Signal('dead', 'Dead', None, False, 'No writer yet.'),
            ],
        ):
            payload = platform_health()

        self.assertEqual(payload['needs_attention'], 1)
        self.assertEqual(payload['unmonitored'], ['dead'])
        by_key = {row['key']: row for row in payload['signals']}
        self.assertEqual(by_key['live']['display'], '1')
        self.assertEqual(by_key['dead']['display'], 'Not monitored')

    def test_every_live_signal_returns_a_number(self):
        for row in platform_signals():
            if row.live:
                self.assertIsInstance(row.value, int, row.key)
            else:
                self.assertIsNone(row.value, row.key)
