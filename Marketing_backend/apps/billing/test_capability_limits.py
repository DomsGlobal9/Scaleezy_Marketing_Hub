"""
Per-capability entitlement.

"100 posters for client A, 10 videos for client B" is the control Super Admin
actually needs, so what matters here is that IMAGE and VIDEO are metered
independently, that the per-client override beats the plan, that the count
comes from what was really produced (not from failed or discarded provider
calls), and that the ceiling is enforced at the router — the one place every
spend path goes through.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.ai.adapters.base import AIProviderAdapter
from apps.ai.models import (
    AIProvider,
    AIUsageLog,
    Capability,
    WorkspaceAIProvider,
    WorkspaceAIRoute,
)
from apps.ai.router import AIRouter
from apps.billing import quota
from apps.billing.models import Plan, Subscription
from apps.brands.models import Brand
from apps.workspaces.models import MarketingWorkspace
from apps.workspaces.services.lifecycle import set_capability_limits


class LimitTestAdapter(AIProviderAdapter):
    key = 'test-limits'
    display_name = 'Test Limits'
    capabilities = (Capability.TEXT, Capability.IMAGE, Capability.VIDEO)
    unit_cost = 0

    def generate_text(self, brief):
        return {'headline': 'ok'}

    def generate_image(self, brief):
        return {'image_url': 'https://example.test/p.png'}

    def health_check(self):
        return {'ok': True, 'detail': 'ready'}


class CapabilityLimitTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='c1', workspace_name='Acme'
        )
        # An ACTIVE brand: the approval gate is a separate rule and must not
        # be what blocks these requests.
        Brand.objects.create(
            workspace=self.workspace, name='Acme', is_default=True,
            status=Brand.Status.ACTIVE,
        )
        self.plan = Plan.objects.create(
            key='test-plan', name='Test', monthly_generations=0,
            monthly_spend_cap=0, capability_limits={'IMAGE': 2, 'VIDEO': 1},
        )
        self.subscription = Subscription.objects.create(
            workspace=self.workspace, plan=self.plan
        )

        self.provider, _ = AIProvider.objects.update_or_create(
            key=LimitTestAdapter.key,
            defaults={
                'display_name': LimitTestAdapter.display_name,
                'capabilities': list(LimitTestAdapter.capabilities),
                'unit_cost': 0, 'is_available': True,
            },
        )
        WorkspaceAIProvider.objects.create(
            workspace=self.workspace, provider=self.provider, enabled=True
        )
        for capability in LimitTestAdapter.capabilities:
            WorkspaceAIRoute.objects.create(
                workspace=self.workspace, provider=self.provider,
                capability=capability, priority=10,
            )
        registry = patch(
            'apps.ai.registry.get_adapter_class',
            side_effect=lambda key: LimitTestAdapter if key == self.provider.key else None,
        )
        registry.start()
        self.addCleanup(registry.stop)

    def log(self, capability, n=1, *, success=True, selected=True):
        for _ in range(n):
            AIUsageLog.objects.create(
                workspace=self.workspace, provider=self.provider,
                capability=capability, cost=Decimal('0'), success=success,
                selected=selected,
            )

    # ---------------------------------------------------------- independence

    def test_image_and_video_are_metered_separately(self):
        self.log(Capability.IMAGE, 2)
        self.assertFalse(quota.check(self.workspace, Capability.IMAGE).allowed)
        # Posters exhausted; video untouched.
        self.assertTrue(quota.check(self.workspace, Capability.VIDEO).allowed)

        self.log(Capability.VIDEO, 1)
        self.assertFalse(quota.check(self.workspace, Capability.VIDEO).allowed)

    def test_a_capability_with_no_limit_is_unlimited(self):
        self.log(Capability.TEXT, 50)
        self.assertTrue(quota.check(self.workspace, Capability.TEXT).allowed)

    def test_the_verdict_names_the_capability_and_the_numbers(self):
        self.log(Capability.IMAGE, 2)
        verdict = quota.check(self.workspace, Capability.IMAGE)
        self.assertEqual(verdict.code, 'CAPABILITY_QUOTA_EXCEEDED')
        self.assertEqual(verdict.capability, Capability.IMAGE)
        self.assertEqual(verdict.capability_used, 2)
        self.assertEqual(verdict.capability_limit, 2)
        self.assertIn('poster generations', verdict.message)
        self.assertIn('2', verdict.message)

    # ---------------------------------------------------------- what counts

    def test_failed_and_discarded_provider_calls_do_not_consume_allowance(self):
        # A run of provider failures must not burn a customer's posters:
        # they got nothing for them.
        self.log(Capability.IMAGE, 5, success=False)
        # A BEST_OF loser was paid for (it is spend) but produced no asset.
        self.log(Capability.IMAGE, 5, selected=False)
        self.assertTrue(quota.check(self.workspace, Capability.IMAGE).allowed)
        self.assertEqual(
            quota.capability_usage(self.workspace).get(Capability.IMAGE, 0), 0
        )

    def test_internal_qa_calls_are_spend_but_never_customer_units(self):
        # One real poster, plus a platform QA dispatch (the copy judge / the
        # focus vision call). The QA row is money — it counts toward the
        # spend cap — but it must not consume one of the customer's two
        # provisioned IMAGE units. The unit/spend split is surfaced for
        # founder review.
        self.log(Capability.IMAGE, 1)
        AIUsageLog.objects.create(
            workspace=self.workspace, provider=self.provider,
            capability=Capability.IMAGE, cost=Decimal('0.05'),
            success=True, selected=True, is_internal=True,
        )

        self.assertEqual(
            quota.capability_usage(self.workspace).get(Capability.IMAGE, 0), 1
        )
        self.assertTrue(quota.check(self.workspace, Capability.IMAGE).allowed)
        _generations, spend = quota.usage(self.workspace)
        self.assertEqual(spend, Decimal('0.05'))

    def test_usage_is_counted_within_the_current_period_only(self):
        self.log(Capability.IMAGE, 2)
        self.assertFalse(quota.check(self.workspace, Capability.IMAGE).allowed)
        # Roll the period forward; the previous period's usage stops counting.
        start, _ = self.subscription.current_period()
        self.subscription.period_start = start.replace(
            year=start.year + 1
        )
        self.subscription.period_end = None
        self.subscription.save(update_fields=['period_start', 'period_end'])
        self.assertTrue(quota.check(self.workspace, Capability.IMAGE).allowed)

    # ---------------------------------------------------------- the override

    def test_a_per_client_override_beats_the_plan(self):
        self.log(Capability.IMAGE, 2)
        self.assertFalse(quota.check(self.workspace, Capability.IMAGE).allowed)

        set_capability_limits(self.workspace, {'IMAGE': 100, 'VIDEO': 0})
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.limit_for(Capability.IMAGE), 100)
        self.assertTrue(quota.check(self.workspace, Capability.IMAGE).allowed)
        # 0 means unlimited, not "none allowed".
        self.log(Capability.VIDEO, 9)
        self.assertTrue(quota.check(self.workspace, Capability.VIDEO).allowed)

    def test_setting_limits_is_audited_and_never_touches_the_plan(self):
        from apps.audit.models import PlatformAuditLog

        set_capability_limits(self.workspace, {'IMAGE': 7})
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.capability_limits, {'IMAGE': 2, 'VIDEO': 1})

        entry = PlatformAuditLog.objects.get(action='CLIENT_LIMITS_CHANGED')
        self.assertEqual(entry.workspace, self.workspace)
        self.assertEqual(entry.detail['after'], {'IMAGE': 7})

    def test_a_malformed_limit_is_refused_rather_than_stored(self):
        with self.assertRaises(ValueError):
            set_capability_limits(self.workspace, {'IMAGE': 'lots'})
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.capability_limit_overrides, {})

    # ---------------------------------------------------------- enforcement

    def test_the_router_refuses_once_the_capability_ceiling_is_reached(self):
        self.log(Capability.IMAGE, 2)
        with patch.object(LimitTestAdapter, 'run') as run:
            with self.assertRaises(quota.QuotaExceeded) as caught:
                AIRouter(self.workspace).dispatch(Capability.IMAGE, {})
        run.assert_not_called()
        self.assertEqual(caught.exception.verdict.code, 'CAPABILITY_QUOTA_EXCEEDED')

        # The same workspace may still spend on a capability with headroom.
        with patch.object(LimitTestAdapter, 'run', return_value={'headline': 'ok'}):
            AIRouter(self.workspace).dispatch(Capability.TEXT, {})

    def test_no_subscription_stays_unlimited(self):
        self.subscription.delete()
        self.log(Capability.IMAGE, 99)
        self.assertTrue(quota.check(self.workspace, Capability.IMAGE).allowed)

    def test_summary_reports_every_capability_with_real_counts(self):
        self.log(Capability.IMAGE, 1)
        summary = quota.summary(self.workspace)
        by_capability = {c['capability']: c for c in summary['capabilities']}
        self.assertEqual(by_capability['IMAGE']['used'], 1)
        self.assertEqual(by_capability['IMAGE']['limit'], 2)
        self.assertEqual(by_capability['IMAGE']['remaining'], 1)
        self.assertEqual(by_capability['VIDEO']['used'], 0)
        self.assertFalse(by_capability['IMAGE']['overridden'])

        set_capability_limits(self.workspace, {'IMAGE': 50})
        summary = quota.summary(self.workspace)
        by_capability = {c['capability']: c for c in summary['capabilities']}
        self.assertTrue(by_capability['IMAGE']['overridden'])
