"""Phase 8 — subscriptions, quotas and spend caps."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.ai.models import AIProvider, AIUsageLog
from apps.billing import quota
from apps.billing.models import Plan, Subscription
from apps.content.models import ContentItem
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()


class Base(APITestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.other = MarketingWorkspace.objects.create(customer_id='b', workspace_name='Beta')

        self.editor = User.objects.create_user(username='ed', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.editor, role=WorkspaceMember.Role.EDITOR
        )
        self.outsider = User.objects.create_user(username='out', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.other, user=self.outsider, role=WorkspaceMember.Role.OWNER
        )

        self.plan = Plan.objects.get(key='free')

    def subscribe(self, workspace=None, plan=None, **kwargs):
        return Subscription.objects.create(
            workspace=workspace or self.ws, plan=plan or self.plan, **kwargs
        )

    def generations(self, n, workspace=None):
        for i in range(n):
            ContentItem.objects.create(
                workspace=workspace or self.ws, headline=f"Item {i}"
            )

    def spend(self, amount, workspace=None):
        provider, _ = AIProvider.objects.get_or_create(
            key='gemini', defaults={'display_name': 'Gemini', 'capabilities': ['TEXT']}
        )
        AIUsageLog.objects.create(
            workspace=workspace or self.ws, provider=provider,
            capability='TEXT', cost=Decimal(amount),
        )

    def as_(self, user, ws=None):
        self.client.force_authenticate(user=user)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str((ws or self.ws).id))


class PlanSeedTests(Base):
    def test_plans_are_seeded(self):
        self.assertEqual(
            set(Plan.objects.values_list('key', flat=True)), {'free', 'studio', 'agency'}
        )

    def test_nobody_is_enrolled_by_the_migration(self):
        """A billing migration must not silently put existing customers on a plan."""
        self.assertFalse(Subscription.objects.exists())


class QuotaTests(Base):
    def test_an_unsubscribed_workspace_is_never_blocked(self):
        self.generations(500)
        verdict = quota.check(self.ws)
        self.assertTrue(verdict.allowed)
        self.assertEqual(verdict.code, 'NO_SUBSCRIPTION')

    def test_within_allowance(self):
        self.subscribe()
        self.generations(5)
        verdict = quota.check(self.ws)
        self.assertTrue(verdict.allowed)
        self.assertEqual(verdict.used, 5)
        self.assertEqual(verdict.limit, 30)

    def test_generation_quota_blocks_at_the_limit(self):
        self.subscribe()
        self.generations(30)
        verdict = quota.check(self.ws)
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.code, 'GENERATION_QUOTA_EXCEEDED')

    def test_spend_cap_blocks_independently_of_the_count(self):
        self.subscribe()
        self.spend('5.00')
        verdict = quota.check(self.ws)
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.code, 'SPEND_CAP_REACHED')

    def test_zero_means_unlimited_not_zero_allowed(self):
        agency = Plan.objects.get(key='agency')
        self.subscribe(plan=agency)
        self.generations(50)
        self.spend('500.00')
        self.assertTrue(quota.check(self.ws).allowed)

    def test_an_inactive_subscription_blocks(self):
        self.subscribe(status=Subscription.Status.PAST_DUE)
        verdict = quota.check(self.ws)
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.code, 'SUBSCRIPTION_INACTIVE')

    def test_a_per_workspace_override_beats_the_plan(self):
        self.subscribe(generations_override=2)
        self.generations(2)
        self.assertFalse(quota.check(self.ws).allowed)

    def test_usage_is_counted_per_workspace(self):
        self.subscribe()
        self.generations(30, workspace=self.other)
        self.assertTrue(quota.check(self.ws).allowed)

    def test_usage_outside_the_period_does_not_count(self):
        subscription = self.subscribe()
        self.generations(30)
        ContentItem.objects.update(created_at=timezone.now() - timedelta(days=400))
        start, _end = subscription.current_period()
        self.assertGreater(start, timezone.now() - timedelta(days=400))
        self.assertTrue(quota.check(self.ws).allowed)

    def test_a_lapsed_period_rolls_forward_rather_than_locking_out(self):
        subscription = self.subscribe(
            period_start=timezone.now() - timedelta(days=200),
            period_end=timezone.now() - timedelta(days=170),
        )
        start, end = subscription.current_period()
        self.assertLessEqual(start, timezone.now())
        self.assertGreater(end, timezone.now())

    def test_enforce_raises(self):
        self.subscribe()
        self.generations(30)
        with self.assertRaises(quota.QuotaExceeded):
            quota.enforce(self.ws)

    def test_enforce_is_quiet_when_allowed(self):
        self.subscribe()
        self.assertTrue(quota.enforce(self.ws).allowed)


class SummaryTests(Base):
    def test_summary_for_an_unsubscribed_workspace(self):
        data = quota.summary(self.ws)
        self.assertFalse(data['subscribed'])
        self.assertTrue(data['allowed'])

    def test_summary_reports_remaining(self):
        self.subscribe()
        self.generations(4)
        self.spend('1.50')
        data = quota.summary(self.ws)
        self.assertEqual(data['generations_used'], 4)
        self.assertEqual(data['generations_remaining'], 26)
        self.assertEqual(data['spend'], '1.50')
        self.assertEqual(data['spend_remaining'], '3.50')
        self.assertEqual(data['plan']['key'], 'free')


class BillingAPITests(Base):
    def test_anonymous_rejected(self):
        self.client.credentials()
        self.assertEqual(
            self.client.get('/api/marketing/billing/').status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_returns_the_callers_own_usage(self):
        self.subscribe()
        self.generations(3)
        self.as_(self.editor)
        res = self.client.get('/api/marketing/billing/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['data']['generations_used'], 3)

    def test_another_tenants_usage_is_not_visible(self):
        self.subscribe(workspace=self.other)
        self.generations(9, workspace=self.other)
        self.as_(self.editor)
        res = self.client.get('/api/marketing/billing/')
        self.assertEqual(res.data['data']['generations_used'], 0)
        self.assertFalse(res.data['data']['subscribed'])

    def test_plans_are_listed(self):
        self.as_(self.editor)
        res = self.client.get('/api/marketing/billing/plans/')
        self.assertEqual(len(res.data['data']), 3)

    def test_the_plan_cannot_be_changed_through_the_api(self):
        """Self-service upgrade would be self-service spend-cap raising."""
        self.subscribe()
        self.as_(self.editor)
        for verb in (self.client.post, self.client.put, self.client.patch):
            res = verb('/api/marketing/billing/', {'plan': 'agency'}, format='json')
            self.assertIn(
                res.status_code,
                (status.HTTP_405_METHOD_NOT_ALLOWED, status.HTTP_404_NOT_FOUND),
            )


class GenerationGateTests(Base):
    def test_generation_is_refused_when_out_of_quota(self):
        self.subscribe()
        self.generations(30)
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/gemini/generate/',
            {'creativeMode': 'AI_ORIGINAL', 'campaignName': 'Diwali'}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(res.data['error']['code'], 'GENERATION_QUOTA_EXCEEDED')

    def test_async_generation_is_refused_too(self):
        self.subscribe()
        self.generations(30)
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/gemini/generate-async/',
            {'creativeMode': 'AI_ORIGINAL', 'campaignName': 'Diwali', 'contentType': 'video'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_402_PAYMENT_REQUIRED)

    def test_the_ai_router_refuses_when_over_cap(self):
        from apps.ai.router import AIRouter

        self.subscribe()
        self.spend('5.00')
        with self.assertRaises(quota.QuotaExceeded):
            AIRouter(self.ws).dispatch('TEXT', {})
