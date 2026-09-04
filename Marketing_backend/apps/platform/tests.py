"""
The platform boundary, proven from the outside.

What a workspace member — even an OWNER, even `is_staff` — gets from every
platform endpoint is 403. What a platform admin gets is the real thing, and
every call leaves an audit row. The approval queue is the worked example: the
approve action activates the brand, creates the subscription, records who
decided, and the client can generate afterwards; reject archives reversibly.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import PlatformAuditLog
from apps.audit.services import grant_platform_admin
from apps.billing.models import Plan, Subscription
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()

HEALTH = '/api/platform/health/'
SIGNUPS = '/api/platform/signups/'


class PlatformBoundaryTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Pending Co', 'c1')
        self.owner, self.owner_api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner@pending.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Pending Co', website='https://pending.test',
            is_default=True, status=Brand.Status.PENDING,
        )
        # The seed migration already ships a 'free' plan; make sure one exists
        # without colliding with it.
        Plan.objects.get_or_create(key='free', defaults={'name': 'Free', 'is_default': True})

        self.staff = User.objects.create_user(username='staff@scaleezy.test', password='pw')
        grant_platform_admin(self.staff, note='test')
        self.staff_api = APIClient()
        self.staff_api.force_authenticate(user=self.staff)

    # ───────────────────────────────────────────── the boundary itself

    def test_a_workspace_owner_cannot_reach_any_platform_endpoint(self):
        for url in (HEALTH, SIGNUPS):
            self.assertEqual(self.owner_api.get(url).status_code, status.HTTP_403_FORBIDDEN, url)
        self.assertEqual(
            self.owner_api.post(f'{SIGNUPS}{self.brand.id}/approve/', {}, format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.status, Brand.Status.PENDING)

    def test_is_staff_is_not_platform_authority(self):
        self.owner.is_staff = True
        self.owner.is_superuser = True
        self.owner.save(update_fields=['is_staff', 'is_superuser'])
        self.assertEqual(self.owner_api.get(HEALTH).status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_is_refused(self):
        self.assertEqual(APIClient().get(HEALTH).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_revocation_takes_effect_on_the_next_request(self):
        from apps.audit.services import revoke_platform_admin

        keeper = User.objects.create_user(username='keeper@scaleezy.test', password='pw')
        grant_platform_admin(keeper)
        self.assertEqual(self.staff_api.get(HEALTH).status_code, 200)
        revoke_platform_admin(self.staff, by=keeper)
        # Same client, same session, no token refresh — still refused.
        self.assertEqual(self.staff_api.get(HEALTH).status_code, status.HTTP_403_FORBIDDEN)

    # ───────────────────────────────────────────── P5 health

    def test_health_returns_live_signals_and_audits_the_read(self):
        response = self.staff_api.get(HEALTH)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        by_key = {s['key']: s for s in data['signals']}
        self.assertEqual(by_key['pending_approvals']['value'], 1)
        self.assertTrue(by_key['knowledge_failed']['live'])
        self.assertEqual(by_key['knowledge_failed']['display'], '0')
        self.assertNotIn('knowledge_failed', data['unmonitored'])
        self.assertTrue(PlatformAuditLog.objects.filter(action='PLATFORM_HEALTH_VIEWED').exists())

    # ───────────────────────────────────────────── P1 approval queue

    def test_the_queue_lists_pending_clients_with_real_counts(self):
        from apps.inspirations.models import BrandInspiration
        from apps.knowledge.models import BrandSource

        BrandSource.objects.create(workspace=self.workspace, brand=self.brand, title='Deck')
        BrandInspiration.objects.create(workspace=self.workspace, brand=self.brand, title='Ref')
        self.authenticate_as(self.workspace, WorkspaceMember.Role.EDITOR, 'second@pending.test')

        response = self.staff_api.get(SIGNUPS)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual(data['pending_total'], 1)
        # The exact response shape is a contract with the console pages.
        self.assertEqual(set(data), {'status', 'count', 'pending_total', 'signups'})
        row = data['signups'][0]
        self.assertEqual(set(row), {
            'brand_id', 'workspace_id', 'client_code', 'name', 'legal_name',
            'website', 'industry', 'location', 'contact_person',
            'contact_phone', 'status', 'signed_up_at', 'signed_up_by',
            'knowledge_sources', 'inspirations', 'team_size',
            'reviewed_at', 'reviewed_by',
        })
        self.assertEqual(row['brand_id'], str(self.brand.id))
        self.assertEqual(row['client_code'], self.workspace.client_code)
        self.assertEqual(row['signed_up_by'], 'owner@pending.test')
        self.assertEqual(row['knowledge_sources'], 1)
        self.assertEqual(row['inspirations'], 1)
        self.assertEqual(row['team_size'], 2)
        self.assertTrue(PlatformAuditLog.objects.filter(action='SIGNUP_QUEUE_VIEWED').exists())

    def test_count_only_returns_just_the_pending_total(self):
        response = self.staff_api.get(f'{SIGNUPS}?count_only=1')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data'], {'pending_total': 1})
        entry = PlatformAuditLog.objects.filter(action='SIGNUP_QUEUE_VIEWED').order_by('-pk').first()
        self.assertTrue(entry.detail.get('count_only'))

    def test_queue_query_count_does_not_grow_with_rows(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def queries_for_a_page():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.staff_api.get(SIGNUPS).status_code, 200)
            return len(ctx.captured_queries)

        baseline = queries_for_a_page()
        for i in range(4):
            workspace = self.make_workspace(f'Bulk {i}', f'bulk{i}')
            self.authenticate_as(workspace, WorkspaceMember.Role.OWNER, f'owner{i}@bulk.test')
            Brand.objects.create(
                workspace=workspace, name=f'Bulk {i}',
                is_default=True, status=Brand.Status.PENDING,
            )
        # Counts come from grouped queries per table, never per row.
        self.assertEqual(queries_for_a_page(), baseline)

    def test_approve_activates_creates_subscription_records_decider_and_corrections(self):
        response = self.staff_api.post(
            f'{SIGNUPS}{self.brand.id}/approve/',
            {'website': 'https://pending-co.test', 'plan': 'free'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)

        self.brand.refresh_from_db()
        self.assertEqual(self.brand.status, Brand.Status.ACTIVE)
        self.assertEqual(self.brand.website, 'https://pending-co.test')
        self.assertEqual(self.brand.reviewed_by, self.staff)
        self.assertTrue(Subscription.objects.filter(workspace=self.workspace).exists())

        actions = set(PlatformAuditLog.objects.values_list('action', flat=True))
        self.assertIn('BRAND_APPROVED', actions)
        self.assertIn('BRAND_CORRECTED_AT_APPROVAL', actions)

        # And the client can now spend.
        from apps.brands.services.approval import spend_block

        self.assertIsNone(spend_block(self.workspace))

    def test_approve_with_an_unknown_plan_changes_nothing(self):
        response = self.staff_api.post(
            f'{SIGNUPS}{self.brand.id}/approve/', {'plan': 'platinum'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.status, Brand.Status.PENDING)

    def test_reject_archives_reversibly_with_a_reason(self):
        response = self.staff_api.post(
            f'{SIGNUPS}{self.brand.id}/reject/', {'reason': 'not a real business'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.status, Brand.Status.ARCHIVED)
        entry = PlatformAuditLog.objects.get(action='BRAND_REJECTED')
        self.assertEqual(entry.detail['reason'], 'not a real business')
        # Still there, still reversible.
        self.assertTrue(Brand.objects.filter(pk=self.brand.pk).exists())

    def test_unknown_brand_is_404(self):
        import uuid

        response = self.staff_api.post(
            f'{SIGNUPS}{uuid.uuid4()}/approve/', {}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ───────────────────────────────────────────── attach-user

    def test_attach_user_puts_a_colleague_on_the_client_and_audits(self):
        colleague = User.objects.create_user(username='colleague@pending.test', password='pw')
        response = self.staff_api.post(
            f'/api/platform/clients/{self.workspace.id}/attach-user/',
            {'username': 'Colleague@Pending.test', 'role': 'EDITOR'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(
            WorkspaceMember.objects.filter(
                workspace=self.workspace, user=colleague, role='EDITOR'
            ).exists()
        )
        self.assertTrue(PlatformAuditLog.objects.filter(action='USER_ATTACHED_TO_CLIENT').exists())

    def test_attach_to_an_archived_client_is_refused(self):
        from apps.workspaces.services.lifecycle import archive_workspace

        User.objects.create_user(username='c@x.test', password='pw')
        archive_workspace(self.workspace, by=self.staff)
        response = self.staff_api.post(
            f'/api/platform/clients/{self.workspace.id}/attach-user/',
            {'username': 'c@x.test'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
