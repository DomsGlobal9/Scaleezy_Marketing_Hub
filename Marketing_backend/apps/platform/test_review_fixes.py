"""
Regressions for the external review of the approval flow.

1. P0  A pending or rejected customer could create another Brand, which was
       born ACTIVE, and the spend gate treated any ACTIVE brand as approval.
2. P1  Reactivating an archived client left its subscription CANCELLED, so it
       looked live and was refused on every AI request.
3. P1  Approval saved name/website corrections before validating the plan, so
       a failed approval still changed customer data.
4. P1  Attach-user archived other workspaces it could not prove were the
       duplicate signup.
5. P1  Duplicate-company prevention was a read-then-write and not safe under
       concurrent signups.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.ai.adapters.base import AIProviderAdapter
from apps.ai.models import AIProvider, Capability
from apps.audit.models import PlatformAuditLog
from apps.audit.services import grant_platform_admin
from apps.billing.models import Plan, Subscription
from apps.brands.models import Brand
from apps.brands.services.approval import approve_brand, reject_brand, spend_block
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.users.models import SignupWebsiteClaim
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember
from apps.workspaces.services.lifecycle import archive_workspace, reactivate_workspace
from apps.workspaces.services.team import attach_user_to_workspace

User = get_user_model()
BRANDS = '/api/marketing/brands/'
WORKSPACES = '/api/marketing/workspaces/'
SIGNUPS = '/api/platform/signups/'


class ProvisionedTestAdapter(AIProviderAdapter):
    key = 'test-review'
    display_name = 'Test Review'
    capabilities = (Capability.TEXT, Capability.IMAGE)

    def health_check(self):
        return {'ok': True, 'detail': 'ready'}


def install_provider(testcase):
    provider, _ = AIProvider.objects.update_or_create(
        key=ProvisionedTestAdapter.key,
        defaults={'display_name': 'Test Review',
                  'capabilities': [Capability.TEXT, Capability.IMAGE],
                  'unit_cost': 0, 'is_available': True},
    )
    AIProvider.objects.exclude(pk=provider.pk).update(is_available=False)
    for target in (
        patch('apps.ai.provisioning.all_adapters',
              return_value={provider.key: ProvisionedTestAdapter}),
        patch('apps.ai.registry.get_adapter_class',
              side_effect=lambda key: ProvisionedTestAdapter if key == provider.key else None),
    ):
        target.start()
        testcase.addCleanup(target.stop)
    return provider


def signup(client, email, website, brand='Brand'):
    return client.post(reverse('auth_signup'), {
        'email': email, 'password': 'orbit-lantern-42-quartz',
        'brand_name': brand, 'website': website,
    }, format='json')


# ────────────────────────────────────────────────── 1. P0 — no self-approval

class ApprovalBypassTests(TestCase):
    def setUp(self):
        cache.clear()
        install_provider(self)
        self.client_api = APIClient()
        data = signup(self.client_api, 'founder@pending.test', 'https://pending.test').json()['data']
        self.workspace = MarketingWorkspace.objects.get(pk=data['workspace_id'])
        self.brand = Brand.objects.get(pk=data['brand_id'])
        self.user = User.objects.get(username='founder@pending.test')
        self.client_api.force_authenticate(user=self.user)

    def test_signup_marks_the_workspace_itself_pending(self):
        self.assertEqual(self.workspace.approval_status, MarketingWorkspace.Approval.PENDING)
        self.assertEqual(spend_block(self.workspace).code, 'CLIENT_NOT_APPROVED')

    def test_a_second_brand_created_by_a_pending_customer_is_not_active(self):
        response = self.client_api.post(
            BRANDS, {'name': 'Second Brand', 'industry': 'x'},
            format='json', **workspace_header(self.workspace),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        second = Brand.objects.get(pk=response.json()['id'])
        self.assertEqual(second.status, Brand.Status.PENDING)
        # And the gate still holds even if a brand somehow were ACTIVE.
        self.assertIsNotNone(spend_block(self.workspace))

    def test_an_active_brand_does_not_approve_a_pending_workspace(self):
        # Even a directly-created ACTIVE brand (e.g. an older code path) does
        # not open the gate: approval is the workspace's, not the brand's.
        Brand.objects.create(workspace=self.workspace, name='Sneaky', status=Brand.Status.ACTIVE)
        self.assertEqual(spend_block(self.workspace).code, 'CLIENT_NOT_APPROVED')

    def test_a_rejected_customer_cannot_get_a_fresh_active_brand_from_current(self):
        reject_brand(self.brand, by=None, reason='not a fit')
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.approval_status, MarketingWorkspace.Approval.REJECTED)

        before = Brand.objects.filter(workspace=self.workspace).count()
        response = self.client_api.get(f'{BRANDS}current/', **workspace_header(self.workspace))
        self.assertEqual(response.status_code, 200, response.content)
        # They get their own (archived, rejected) brand back — nothing new is
        # minted, ACTIVE or otherwise, and the gate stays shut.
        self.assertEqual(response.json()['data']['id'], str(self.brand.id))
        self.assertEqual(response.json()['data']['status'], 'ARCHIVED')
        self.assertEqual(Brand.objects.filter(workspace=self.workspace).count(), before)
        self.assertEqual(spend_block(self.workspace).code, 'CLIENT_REJECTED')

    def test_a_pending_customer_adding_a_client_gets_a_pending_client(self):
        response = self.client_api.post(
            WORKSPACES, {'workspace_name': 'Side Co', 'brand_name': 'Side Brand'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        ws = MarketingWorkspace.objects.get(pk=response.json()['data']['id'])
        self.assertEqual(ws.approval_status, MarketingWorkspace.Approval.PENDING)
        self.assertEqual(Brand.objects.get(workspace=ws).status, Brand.Status.PENDING)
        self.assertIsNotNone(spend_block(ws))

    def test_approval_flips_the_workspace_and_opens_the_gate(self):
        Plan.objects.get_or_create(key='free', defaults={'name': 'Free', 'is_default': True})
        approve_brand(self.brand, by=None)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.approval_status, MarketingWorkspace.Approval.APPROVED)
        self.assertIsNone(spend_block(self.workspace))

        # An approved customer's next client is approved too.
        response = self.client_api.post(
            WORKSPACES, {'workspace_name': 'Second Co', 'brand_name': 'Second Brand'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        ws = MarketingWorkspace.objects.get(pk=response.json()['data']['id'])
        self.assertEqual(ws.approval_status, MarketingWorkspace.Approval.APPROVED)
        self.assertIsNone(spend_block(ws))

    def test_existing_workspaces_are_approved_by_default(self):
        legacy = MarketingWorkspace.objects.create(customer_id='old', workspace_name='Legacy')
        self.assertEqual(legacy.approval_status, MarketingWorkspace.Approval.APPROVED)
        self.assertIsNone(spend_block(legacy))


# ────────────────────────────────────────────── 2. P1 — reactivate restores billing

class ReactivateRestoresSubscriptionTests(TenantFixtureMixin, TestCase):
    def test_reactivated_client_is_billable_again(self):
        workspace = self.make_workspace('Acme', 'c1')
        plan = Plan.objects.create(key='p-react', name='P')
        subscription = Subscription.objects.create(workspace=workspace, plan=plan)
        Brand.objects.create(workspace=workspace, name='Acme', status=Brand.Status.ACTIVE)

        archive_workspace(workspace, by=None, reason='churn')
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, Subscription.Status.CANCELLED)

        reactivate_workspace(workspace, by=None)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)
        self.assertIsNone(spend_block(workspace))

        entry = PlatformAuditLog.objects.get(action='CLIENT_REACTIVATED')
        self.assertTrue(entry.detail['subscription_restored'])

    def test_reactivating_from_suspended_leaves_the_subscription_alone(self):
        from apps.workspaces.services.lifecycle import suspend_workspace

        workspace = self.make_workspace('Acme', 'c1')
        plan = Plan.objects.create(key='p-susp', name='P')
        Subscription.objects.create(
            workspace=workspace, plan=plan, status=Subscription.Status.PAST_DUE
        )
        suspend_workspace(workspace, by=None)
        reactivate_workspace(workspace, by=None)
        self.assertEqual(
            Subscription.objects.get(workspace=workspace).status,
            Subscription.Status.PAST_DUE,
        )


# ─────────────────────────────────── 3. P1 — failed approval changes nothing

class ApprovalAtomicityTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Pending Co', 'c1')
        self.workspace.approval_status = MarketingWorkspace.Approval.PENDING
        self.workspace.save(update_fields=['approval_status'])
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Pending Co', website='https://pending.test',
            status=Brand.Status.PENDING,
        )
        staff = User.objects.create_user(username='staff@scaleezy.test', password='pw')
        grant_platform_admin(staff)
        self.staff_api = APIClient()
        self.staff_api.force_authenticate(user=staff)

    def test_unknown_plan_leaves_name_website_status_and_audit_untouched(self):
        before = PlatformAuditLog.objects.count()
        response = self.staff_api.post(
            f'{SIGNUPS}{self.brand.id}/approve/',
            {'name': 'Corrected Co', 'website': 'https://corrected.test', 'plan': 'no-such-plan'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.brand.refresh_from_db()
        self.workspace.refresh_from_db()
        self.assertEqual(self.brand.name, 'Pending Co')
        self.assertEqual(self.brand.website, 'https://pending.test')
        self.assertEqual(self.brand.status, Brand.Status.PENDING)
        self.assertEqual(self.workspace.approval_status, MarketingWorkspace.Approval.PENDING)
        self.assertFalse(PlatformAuditLog.objects.filter(action='BRAND_CORRECTED_AT_APPROVAL').exists())
        self.assertFalse(PlatformAuditLog.objects.filter(action='BRAND_APPROVED').exists())
        self.assertEqual(PlatformAuditLog.objects.count(), before)

    def test_valid_approval_applies_corrections_and_moves_the_website_claim(self):
        Plan.objects.get_or_create(key='free', defaults={'name': 'Free', 'is_default': True})
        SignupWebsiteClaim.objects.create(website_host='pending.test', workspace=self.workspace)
        response = self.staff_api.post(
            f'{SIGNUPS}{self.brand.id}/approve/',
            {'website': 'https://www.corrected.test/about', 'plan': 'free'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.website, 'https://www.corrected.test/about')
        self.assertEqual(self.brand.status, Brand.Status.ACTIVE)
        hosts = set(SignupWebsiteClaim.objects.filter(workspace=self.workspace)
                    .values_list('website_host', flat=True))
        self.assertEqual(hosts, {'corrected.test'})


# ─────────────────────────────── 4. P1 — attach-user archives nothing, ever

class AttachUserNeverArchivesTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.real = self.make_workspace('Acme', 'c1')
        Brand.objects.create(workspace=self.real, name='Acme', status=Brand.Status.ACTIVE)
        self.staff = User.objects.create_user(username='staff@scaleezy.test', password='pw')
        self.colleague = User.objects.create_user(username='colleague@acme.test', password='pw')

    def _sole_member_workspace(self, name, approval):
        ws = self.make_workspace(name, f'c-{name}')
        ws.approval_status = approval
        ws.save(update_fields=['approval_status'])
        WorkspaceMember.objects.create(
            workspace=ws, user=self.colleague, role=WorkspaceMember.Role.OWNER
        )
        return ws

    def test_candidates_are_returned_and_nothing_is_archived(self):
        pending = self._sole_member_workspace('Dup', MarketingWorkspace.Approval.PENDING)
        approved = self._sole_member_workspace('TheirOwn', MarketingWorkspace.Approval.APPROVED)

        _, candidates = attach_user_to_workspace(self.colleague, self.real, by=self.staff)

        self.assertEqual([c['workspace_id'] for c in candidates], [str(pending.pk)])
        for ws in (pending, approved):
            ws.refresh_from_db()
            self.assertEqual(ws.status, MarketingWorkspace.Status.ACTIVE)
        self.assertFalse(PlatformAuditLog.objects.filter(action='CLIENT_ARCHIVED').exists())
        entry = PlatformAuditLog.objects.get(action='USER_ATTACHED_TO_CLIENT')
        self.assertEqual(entry.detail['duplicate_candidates'], [str(pending.pk)])


# ─────────────────────────── 5. P1 — duplicate company, concurrency-safe

class DuplicateWebsiteRaceTests(TestCase):
    def setUp(self):
        cache.clear()
        install_provider(self)

    def test_the_claim_is_unique_at_the_database(self):
        ws = MarketingWorkspace.objects.create(customer_id='a', workspace_name='A')
        SignupWebsiteClaim.objects.create(website_host='acme.test', workspace=ws)
        with self.assertRaises(IntegrityError):
            SignupWebsiteClaim.objects.create(website_host='acme.test', workspace=ws)

    def test_signup_writes_a_claim_inside_its_transaction(self):
        response = signup(APIClient(), 'a@acme.test', 'https://www.acme.test/')
        self.assertEqual(response.status_code, 201, response.content)
        claim = SignupWebsiteClaim.objects.get(website_host='acme.test')
        self.assertEqual(str(claim.workspace_id), response.json()['data']['workspace_id'])

    def test_a_racing_signup_that_passes_the_read_check_is_still_refused(self):
        # Simulate the loser of a race: the serializer's read check passes
        # (no brand with that site yet) but the claim row already exists.
        ws = MarketingWorkspace.objects.create(customer_id='w', workspace_name='Winner')
        SignupWebsiteClaim.objects.create(website_host='acme.test', workspace=ws)
        before = (User.objects.count(), MarketingWorkspace.objects.count(), Brand.objects.count())

        response = signup(APIClient(), 'loser@acme.test', 'https://acme.test')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertIn('already exists', response.json()['message'])
        # The whole signup rolled back: no user, no workspace, no brand.
        self.assertEqual(
            (User.objects.count(), MarketingWorkspace.objects.count(), Brand.objects.count()),
            before,
        )

    def test_rejecting_or_archiving_releases_the_claim(self):
        first = signup(APIClient(), 'a@acme.test', 'https://acme.test').json()['data']
        brand = Brand.objects.get(pk=first['brand_id'])
        self.assertTrue(SignupWebsiteClaim.objects.filter(website_host='acme.test').exists())

        reject_brand(brand, by=None, reason='no')
        self.assertFalse(SignupWebsiteClaim.objects.filter(website_host='acme.test').exists())

        second = signup(APIClient(), 'b@acme.test', 'https://acme.test', brand='Acme Again')
        self.assertEqual(second.status_code, 201, second.content)

        archive_workspace(MarketingWorkspace.objects.get(pk=second.json()['data']['workspace_id']))
        self.assertFalse(SignupWebsiteClaim.objects.filter(website_host='acme.test').exists())
