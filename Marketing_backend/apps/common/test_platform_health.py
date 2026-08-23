"""
Health signals that mean what they say.

The defect these close: a console showing "0 knowledge failures" when nothing
in the codebase can produce a knowledge failure, and "0 brand brains failing"
when nothing recorded a compile outcome. A tile reading zero because the
sensor is disconnected is worse than no tile, because it is indistinguishable
from good news.
"""
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.brands.models import Brand
from apps.brands.services.brand_brain import (
    rebuild_brand_brain,
    rebuild_brand_brain_safely,
)
from apps.common.permissions import LAST_ACTIVE_RESOLUTION, touch_last_active
from apps.common.platform_health import platform_health, platform_signals
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


class UnmonitoredSignalTests(TestCase):
    """The point of the whole module: a dead sensor must not read zero."""

    def test_signals_with_no_writer_report_not_monitored(self):
        payload = platform_health()
        by_key = {s['key']: s for s in payload['signals']}

        for key in ('knowledge_failed', 'knowledge_needs_review',
                    'inspiration_analysis_failed'):
            row = by_key[key]
            self.assertFalse(row['live'], key)
            self.assertIsNone(row['value'], key)
            self.assertEqual(row['display'], 'Not monitored', key)
            self.assertNotEqual(row['display'], '0', key)
            self.assertTrue(row['reason'], f"{key} must say why it is not live")

        self.assertIn('knowledge_failed', payload['unmonitored'])

    def test_a_dead_sensor_never_counts_towards_needs_attention(self):
        payload = platform_health()
        self.assertEqual(payload['needs_attention'], 0)
        live_keys = {s['key'] for s in payload['signals'] if s['live']}
        dead_keys = {s['key'] for s in payload['signals'] if not s['live']}
        self.assertTrue(dead_keys)

        workspace = MarketingWorkspace.objects.create(
            customer_id='c', workspace_name='W'
        )
        Brand.objects.create(
            workspace=workspace, name='Pending Co', status=Brand.Status.PENDING
        )

        # This one client legitimately trips several LIVE signals at once —
        # it is awaiting approval, has no AI routing and has no activity. What
        # matters is that every contribution to needs_attention came from a
        # live signal, and that the dead ones stayed out of the count no
        # matter what the platform is doing.
        payload = platform_health()
        raised = {
            s['key'] for s in payload['signals']
            if s['live'] and s['actionable'] and (s['value'] or 0) > 0
        }
        self.assertEqual(payload['needs_attention'], len(raised))
        self.assertIn('pending_approvals', raised)
        self.assertTrue(raised.issubset(live_keys))
        self.assertFalse(raised & dead_keys)

    def test_every_live_signal_returns_a_number(self):
        for row in platform_signals():
            if row.live:
                self.assertIsInstance(row.value, int, row.key)
            else:
                self.assertIsNone(row.value, row.key)
