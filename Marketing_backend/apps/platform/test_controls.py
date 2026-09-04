"""
P4 master controls + P7 platform admins, proven from the outside.

A workspace owner gets 403 from every control; anonymous gets 401. A platform
admin gets the real effect — the override lands on the subscription, the
status flips and scheduled posts stop, the plan moves, the cap shows up in the
same summary the client reads, the provider switch flips for everyone, and
every action leaves an audit row. The last active admin cannot be revoked.
"""
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.ai.models import AIProvider, AIUsageLog, Capability
from apps.audit.models import PlatformAdmin, PlatformAuditLog
from apps.audit.services import grant_platform_admin
from apps.billing.models import Plan, Subscription
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.marketing.models import MarketingAsset
from apps.publishing.models import PublishingJob
from apps.universal.models import ClientQualitySettings, ClientUniversalSettings
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()

ADMINS = '/api/platform/admins/'


def client_url(workspace, action):
    return f'/api/platform/clients/{workspace.id}/{action}/'


class PlatformControlsTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Control Co', 'c-ctl')
        self.owner, self.owner_api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner@control.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Control Co', website='https://control.test',
            is_default=True, status=Brand.Status.ACTIVE,
        )
        # The seed migration may already ship these keys; never collide with it.
        self.free, _ = Plan.objects.get_or_create(
            key='free', defaults={'name': 'Free', 'is_default': True}
        )
        self.pro, _ = Plan.objects.get_or_create(
            key='pro', defaults={
                'name': 'Pro', 'monthly_generations': 1000,
                'capability_limits': {'IMAGE': 50},
            },
        )

        self.staff = User.objects.create_user(username='staff@scaleezy.test', password='pw')
        grant_platform_admin(self.staff, note='test')
        self.staff_api = APIClient()
        self.staff_api.force_authenticate(user=self.staff)

    def subscribe(self, plan=None):
        return Subscription.objects.create(workspace=self.workspace, plan=plan or self.free)

    def post(self, action, body=None):
        return self.staff_api.post(client_url(self.workspace, action), body or {}, format='json')

    # ───────────────────────────────────────────── the boundary itself

    def test_a_workspace_owner_cannot_reach_limits_or_admins(self):
        self.subscribe()
        before_admins = PlatformAdmin.objects.count()
        response = self.owner_api.post(
            client_url(self.workspace, 'limits'), {'limits': {'IMAGE': 1}}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.owner_api.get(ADMINS).status_code, status.HTTP_403_FORBIDDEN)
        response = self.owner_api.post(
            ADMINS, {'username': 'owner@control.test'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Nothing moved.
        self.assertEqual(Subscription.objects.get(workspace=self.workspace).capability_limit_overrides, {})
        self.assertEqual(PlatformAdmin.objects.count(), before_admins)
        self.assertFalse(PlatformAdmin.objects.filter(user=self.owner).exists())

    def test_anonymous_is_refused(self):
        response = APIClient().post(
            client_url(self.workspace, 'limits'), {'limits': {}}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(APIClient().get(ADMINS).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unknown_client_is_404(self):
        for action in ('limits', 'suspend', 'reactivate', 'archive', 'universal',
                       'quality', 'plan', 'spend-cap', 'recompile-brain'):
            response = self.staff_api.post(
                f'/api/platform/clients/{uuid.uuid4()}/{action}/', {}, format='json'
            )
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, action)

    # ───────────────────────────────────────────── limits

    def test_limits_set_the_override_and_return_per_capability_usage(self):
        self.subscribe()
        for _ in range(2):
            AIUsageLog.objects.create(
                workspace=self.workspace, capability=Capability.IMAGE,
                success=True, selected=True, cost=Decimal('0.5'),
            )
        # A failed call is not a billable unit and must not count.
        AIUsageLog.objects.create(
            workspace=self.workspace, capability=Capability.IMAGE, success=False,
        )

        response = self.post('limits', {'limits': {'IMAGE': 100, 'VIDEO': '10'}})
        self.assertEqual(response.status_code, 200, response.content)

        subscription = Subscription.objects.get(workspace=self.workspace)
        self.assertEqual(subscription.capability_limit_overrides, {'IMAGE': 100, 'VIDEO': 10})

        usage = response.json()['data']['usage']
        self.assertTrue(usage['subscribed'])
        by_key = {c['capability']: c for c in usage['capabilities']}
        self.assertEqual(by_key['IMAGE']['used'], 2)
        self.assertEqual(by_key['IMAGE']['limit'], 100)
        self.assertEqual(by_key['IMAGE']['remaining'], 98)
        self.assertTrue(by_key['IMAGE']['overridden'])
        self.assertEqual(by_key['VIDEO']['used'], 0)
        self.assertEqual(by_key['VIDEO']['limit'], 10)
        entry = PlatformAuditLog.objects.get(action='CLIENT_LIMITS_CHANGED')
        self.assertEqual(entry.detail['after'], {'IMAGE': 100, 'VIDEO': 10})
        self.assertEqual(entry.actor, self.staff)

    def test_limits_without_a_subscription_is_400(self):
        response = self.post('limits', {'limits': {'IMAGE': 100}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('subscription', response.json()['message'])
        self.assertFalse(PlatformAuditLog.objects.filter(action='CLIENT_LIMITS_CHANGED').exists())

    def test_limits_that_are_not_numbers_are_refused(self):
        self.subscribe()
        response = self.post('limits', {'limits': {'IMAGE': 'lots'}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            Subscription.objects.get(workspace=self.workspace).capability_limit_overrides, {}
        )
        response = self.post('limits', {'limits': 'IMAGE=100'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ───────────────────────────────────────────── lifecycle

    def test_suspend_then_reactivate_flip_status_and_audit(self):
        response = self.post('suspend', {'reason': 'unpaid invoice'})
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual(data['status'], MarketingWorkspace.Status.SUSPENDED)
        self.assertEqual(data['status_reason'], 'unpaid invoice')
        self.assertEqual(data['client_code'], self.workspace.client_code)
        self.assertIsNotNone(data['status_changed_at'])
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.status, MarketingWorkspace.Status.SUSPENDED)
        entry = PlatformAuditLog.objects.get(action='CLIENT_SUSPENDED')
        self.assertEqual(entry.detail['reason'], 'unpaid invoice')
        self.assertEqual(entry.workspace, self.workspace)

        response = self.post('reactivate', {'reason': 'paid'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['status'], MarketingWorkspace.Status.ACTIVE)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.status, MarketingWorkspace.Status.ACTIVE)
        entry = PlatformAuditLog.objects.get(action='CLIENT_REACTIVATED')
        self.assertEqual(entry.detail['from'], MarketingWorkspace.Status.SUSPENDED)

    def test_archive_cancels_scheduled_publishing_and_the_subscription(self):
        self.subscribe()
        asset = MarketingAsset.objects.create(
            workspace=self.workspace, file_name='poster.jpg', source='MANUAL_UPLOAD'
        )
        scheduled = PublishingJob.objects.create(
            workspace=self.workspace, asset=asset,
            publish_mode=PublishingJob.PublishMode.SCHEDULED,
            status=PublishingJob.Status.SCHEDULED,
        )
        published = PublishingJob.objects.create(
            workspace=self.workspace, asset=asset, status=PublishingJob.Status.PUBLISHED,
        )

        response = self.post('archive', {'reason': 'churned'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['status'], MarketingWorkspace.Status.ARCHIVED)

        scheduled.refresh_from_db()
        published.refresh_from_db()
        self.assertEqual(scheduled.status, PublishingJob.Status.CANCELLED)
        # History is what happened; it stays.
        self.assertEqual(published.status, PublishingJob.Status.PUBLISHED)
        self.assertEqual(
            Subscription.objects.get(workspace=self.workspace).status,
            Subscription.Status.CANCELLED,
        )
        entry = PlatformAuditLog.objects.get(action='CLIENT_ARCHIVED')
        self.assertEqual(entry.detail['cancelled_publishing_jobs'], 1)
        self.assertEqual(entry.detail['reason'], 'churned')

    # ───────────────────────────────────────────── universal layer

    def test_universal_toggle_persists(self):
        response = self.post('universal', {'standards': False})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()['data'],
            {'standards_enabled': False, 'inspirations_enabled': True},
        )
        row = ClientUniversalSettings.objects.get(workspace=self.workspace)
        self.assertFalse(row.standards_enabled)
        self.assertTrue(row.inspirations_enabled)
        self.assertTrue(PlatformAuditLog.objects.filter(action='CLIENT_UNIVERSAL_TOGGLED').exists())

        response = self.post('universal', {'inspirations': 'false', 'standards': 'true'})
        self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        self.assertTrue(row.standards_enabled)
        self.assertFalse(row.inspirations_enabled)

        # Nothing to change, or garbage, is a 400 — never a silent flip.
        self.assertEqual(self.post('universal', {}).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            self.post('universal', {'standards': 'maybe'}).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        row.refresh_from_db()
        self.assertTrue(row.standards_enabled)

    # ───────────────────────────────────────────── quality engine

    def test_quality_defaults_are_on_and_a_read_never_creates_a_row(self):
        response = self.staff_api.get(client_url(self.workspace, 'quality'))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data'], {
            'critique_enabled': True,
            'focus_crop_enabled': True,
            'variety_enabled': True,
        })
        self.assertFalse(
            ClientQualitySettings.objects.filter(workspace=self.workspace).exists()
        )
        response = self.staff_api.get(f'/api/platform/clients/{uuid.uuid4()}/quality/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_quality_toggle_persists(self):
        response = self.post('quality', {'focus_crop': False})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data'], {
            'critique_enabled': True,
            'focus_crop_enabled': False,
            'variety_enabled': True,
        })
        row = ClientQualitySettings.objects.get(workspace=self.workspace)
        self.assertTrue(row.critique_enabled)
        self.assertFalse(row.focus_crop_enabled)
        self.assertTrue(row.variety_enabled)
        entry = PlatformAuditLog.objects.get(action='CLIENT_QUALITY_TOGGLED')
        self.assertEqual(entry.actor, self.staff)
        self.assertEqual(entry.workspace, self.workspace)
        self.assertEqual(
            entry.detail['after'],
            {'critique': True, 'focus_crop': False, 'variety': True},
        )

        response = self.post('quality', {'critique': 'false', 'variety': 'true'})
        self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        self.assertFalse(row.critique_enabled)
        self.assertFalse(row.focus_crop_enabled)
        self.assertTrue(row.variety_enabled)

        # Nothing to change, or garbage, is a 400 — never a silent flip.
        self.assertEqual(self.post('quality', {}).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            self.post('quality', {'critique': 'maybe'}).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        row.refresh_from_db()
        self.assertFalse(row.critique_enabled)

    def test_quality_is_gated_to_platform_admins(self):
        self.assertEqual(
            self.owner_api.get(client_url(self.workspace, 'quality')).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        response = self.owner_api.post(
            client_url(self.workspace, 'quality'), {'critique': False}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Nothing moved, and nothing was audited.
        self.assertFalse(
            ClientQualitySettings.objects.filter(workspace=self.workspace).exists()
        )
        self.assertFalse(
            PlatformAuditLog.objects.filter(action='CLIENT_QUALITY_TOGGLED').exists()
        )

    # ───────────────────────────────────────────── plan

    def test_plan_change_creates_then_moves_the_subscription(self):
        self.assertFalse(Subscription.objects.filter(workspace=self.workspace).exists())

        response = self.post('plan', {'plan': 'free'})
        self.assertEqual(response.status_code, 200, response.content)
        subscription = Subscription.objects.get(workspace=self.workspace)
        self.assertEqual(subscription.plan, self.free)
        self.assertEqual(response.json()['data']['plan']['key'], 'free')
        self.assertEqual(response.json()['data']['subscription_status'], subscription.status)
        first = PlatformAuditLog.objects.get(action='CLIENT_PLAN_CHANGED')
        self.assertIsNone(first.detail['from'])
        self.assertEqual(first.detail['to'], 'free')

        response = self.post('plan', {'plan': 'pro'})
        self.assertEqual(response.status_code, 200, response.content)
        subscription.refresh_from_db()
        self.assertEqual(subscription.plan, self.pro)
        latest = PlatformAuditLog.objects.filter(action='CLIENT_PLAN_CHANGED').order_by('-created_at').first()
        self.assertEqual(latest.detail, {'from': 'free', 'to': 'pro', 'created_subscription': False})

        response = self.post('plan', {'plan': 'platinum'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        subscription.refresh_from_db()
        self.assertEqual(subscription.plan, self.pro)

    # ───────────────────────────────────────────── spend cap

    def test_spend_cap_change_is_reflected_in_the_quota_summary(self):
        response = self.post('spend-cap', {'spend_cap': '25.00'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, "no subscription yet")

        self.subscribe()
        response = self.post('spend-cap', {'spend_cap': '25.00'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['spend_cap'], '25.00')
        self.assertEqual(response.json()['data']['spend_remaining'], '25.00')
        subscription = Subscription.objects.get(workspace=self.workspace)
        self.assertEqual(subscription.spend_cap_override, Decimal('25.00'))
        entry = PlatformAuditLog.objects.get(action='CLIENT_SPEND_CAP_CHANGED')
        self.assertEqual(entry.detail, {'from': None, 'to': '25.00'})

        # The same summary the client reads agrees.
        from apps.billing import quota

        self.assertEqual(quota.summary(self.workspace)['spend_cap'], '25.00')

        # Null clears the override; the plan's cap applies again.
        response = self.post('spend-cap', {'spend_cap': None})
        self.assertEqual(response.status_code, 200, response.content)
        subscription.refresh_from_db()
        self.assertIsNone(subscription.spend_cap_override)
        self.assertEqual(
            response.json()['data']['spend_cap'], str(quota.money(self.free.monthly_spend_cap))
        )

        for bad in ('twenty', '-1'):
            response = self.post('spend-cap', {'spend_cap': bad})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, bad)
        subscription.refresh_from_db()
        self.assertIsNone(subscription.spend_cap_override)

    # ───────────────────────────────────────────── recompile brain

    def test_recompile_brain_rebuilds_every_live_brand_and_audits(self):
        archived = Brand.objects.create(
            workspace=self.workspace, name='Old Line', website='https://old.test',
            status=Brand.Status.ARCHIVED,
        )
        self.assertIsNone(self.brand.brain_compiled_at)

        response = self.post('recompile-brain')
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()['data']
        self.assertEqual([r['brand_id'] for r in rows], [str(self.brand.id)])
        self.assertIsNotNone(rows[0]['compiled_at'])
        self.assertEqual(rows[0]['last_error'], '')
        self.assertIn('version', rows[0])

        self.brand.refresh_from_db()
        archived.refresh_from_db()
        self.assertIsNotNone(self.brand.brain_compiled_at)
        self.assertEqual(self.brand.creative_brain.get('brand_id'), str(self.brand.id))
        self.assertIsNone(archived.brain_compiled_at)

        entry = PlatformAuditLog.objects.get(action='BRAND_BRAIN_RECOMPILED')
        self.assertEqual(entry.detail['brands'], [str(self.brand.id)])
        self.assertEqual(entry.detail['failed'], [])
        self.assertEqual(entry.workspace, self.workspace)

    # ───────────────────────────────────────────── provider kill switch

    def test_provider_kill_switch_flips_availability_for_everyone(self):
        provider = AIProvider.objects.create(
            key='kill-me', display_name='Kill Me', capabilities=[Capability.TEXT],
        )
        url = f'/api/platform/providers/{provider.id}/availability/'

        response = self.staff_api.post(url, {'is_available': False}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()['data'], {'provider_key': 'kill-me', 'is_available': False}
        )
        provider.refresh_from_db()
        self.assertFalse(provider.is_available)
        entry = PlatformAuditLog.objects.get(action='PROVIDER_AVAILABILITY_CHANGED')
        self.assertEqual(entry.detail, {'provider_key': 'kill-me', 'from': True, 'to': False})

        response = self.staff_api.post(url, {'is_available': 'true'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        provider.refresh_from_db()
        self.assertTrue(provider.is_available)

        response = self.staff_api.post(url, {'is_available': 'maybe'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.staff_api.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        provider.refresh_from_db()
        self.assertTrue(provider.is_available)

        response = self.owner_api.post(url, {'is_available': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.staff_api.post(
            f'/api/platform/providers/{uuid.uuid4()}/availability/',
            {'is_available': False}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ───────────────────────────────────────────── platform admins

    def test_admins_list_grant_revoke_and_last_admin_refusal(self):
        response = self.staff_api.get(ADMINS)
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()['data']['admins']
        self.assertEqual([r['username'] for r in rows], ['staff@scaleezy.test'])
        self.assertTrue(rows[0]['is_active'])
        self.assertEqual(rows[0]['note'], 'test')
        self.assertTrue(PlatformAuditLog.objects.filter(action='PLATFORM_ADMINS_VIEWED').exists())

        # Grant by email, case-insensitively.
        newcomer = User.objects.create_user(
            username='ops', email='Ops@scaleezy.test', password='pw'
        )
        response = self.staff_api.post(
            ADMINS, {'username': 'ops@SCALEEZY.test', 'note': 'on-call'}, format='json'
        )
        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()['data']
        self.assertEqual(row['user_id'], newcomer.pk)
        self.assertEqual(row['username'], 'ops')
        self.assertEqual(row['email'], 'Ops@scaleezy.test')
        self.assertTrue(row['is_active'])
        self.assertEqual(row['note'], 'on-call')
        self.assertEqual(row['granted_by'], 'staff@scaleezy.test')
        self.assertIsNone(row['revoked_at'])
        self.assertTrue(PlatformAdmin.objects.filter(user=newcomer, is_active=True).exists())
        # (setUp's bootstrap grant wrote one too; this one names the newcomer.)
        entry = PlatformAuditLog.objects.get(
            action='PLATFORM_ADMIN_GRANTED', target=f'user:{newcomer.pk}'
        )
        self.assertEqual(entry.actor, self.staff)
        self.assertEqual(entry.detail['note'], 'on-call')
        # And the grant is live on the very next request.
        newcomer_api = APIClient()
        newcomer_api.force_authenticate(user=newcomer)
        self.assertEqual(newcomer_api.get(ADMINS).status_code, 200)

        # Unknown user is 404, and nothing is granted.
        response = self.staff_api.post(ADMINS, {'username': 'nobody@x.test'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(PlatformAdmin.objects.filter(is_active=True).count(), 2)

        # Revoke the newcomer: row kept, flagged, audited, and refused next request.
        response = self.staff_api.post(f'{ADMINS}{newcomer.pk}/revoke/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()['data']
        self.assertFalse(row['is_active'])
        self.assertEqual(row['revoked_by'], 'staff@scaleezy.test')
        self.assertIsNotNone(row['revoked_at'])
        self.assertTrue(PlatformAuditLog.objects.filter(action='PLATFORM_ADMIN_REVOKED').exists())
        self.assertEqual(newcomer_api.get(ADMINS).status_code, status.HTTP_403_FORBIDDEN)

        # The revoked row stays in the list, after the active ones.
        rows = self.staff_api.get(ADMINS).json()['data']['admins']
        self.assertEqual([(r['username'], r['is_active']) for r in rows],
                         [('staff@scaleezy.test', True), ('ops', False)])

        # The last active admin cannot be revoked — not even by themselves.
        response = self.staff_api.post(f'{ADMINS}{self.staff.pk}/revoke/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertIn('last platform admin', response.json()['message'])
        self.assertTrue(PlatformAdmin.objects.get(user=self.staff).is_active)
        self.assertEqual(self.staff_api.get(ADMINS).status_code, 200)

        # Revoking somebody who never held the role is 404.
        response = self.staff_api.post(f'{ADMINS}{self.owner.pk}/revoke/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_regranting_a_revoked_admin_reactivates_the_same_row(self):
        returning = User.objects.create_user(username='returning@scaleezy.test', password='pw')
        grant_platform_admin(returning, by=self.staff)
        self.staff_api.post(f'{ADMINS}{returning.pk}/revoke/', {}, format='json')
        self.assertFalse(PlatformAdmin.objects.get(user=returning).is_active)

        response = self.staff_api.post(
            ADMINS, {'username': 'returning@scaleezy.test', 'note': 'back'}, format='json'
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['data']['is_active'])
        self.assertEqual(response.json()['data']['note'], 'back')
        self.assertEqual(PlatformAdmin.objects.filter(user=returning).count(), 1)
