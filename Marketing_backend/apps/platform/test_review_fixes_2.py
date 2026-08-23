"""
Second round of review findings (Bugbot), each pinned by a test.

P0  migration backfill marked previously-rejected clients APPROVED
P0  Django staff could add themselves to a client / create an approved client
P1  a rejected client could PATCH its brand ARCHIVED -> ACTIVE
P1  rejection left the workspace ACTIVE (scheduled posts kept firing)
P1  reactivate restored subscriptions it had not cancelled
P1  approval website correction could adopt another client's claim
P1  SSRF guard allowed CGNAT (100.64.0.0/10) and other non-global ranges
P1  page cap applied after full download
"""
import importlib

import httpx
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import PlatformAuditLog
from apps.audit.services import grant_platform_admin
from apps.billing.models import Plan, Subscription
from apps.brands.models import Brand
from apps.brands.services.approval import approve_brand, reject_brand, spend_block
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.marketing.models import MarketingAsset
from apps.publishing.models import PublishingJob
from apps.publishing.scheduler import due_jobs
from apps.universal import enrichment
from apps.users.models import SignupWebsiteClaim
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember
from apps.workspaces.services.lifecycle import archive_workspace, reactivate_workspace

User = get_user_model()
BRANDS = '/api/marketing/brands/'
SIGNUPS = '/api/platform/signups/'


def backfill_fn():
    module = importlib.import_module(
        'apps.workspaces.migrations.0004_workspace_approval_status'
    )
    return module.backfill


# ───────────────────────────────────────────── P0  migration backfill

class BackfillTests(TestCase):
    def test_previously_rejected_workspace_is_marked_rejected_not_approved(self):
        ws = MarketingWorkspace.objects.create(customer_id='r', workspace_name='Rejected Co')
        staff = User.objects.create_user(username='s@x.test', password='pw')
        Brand.objects.create(
            workspace=ws, name='Rejected Co', status=Brand.Status.ARCHIVED,
            reviewed_at=timezone.now(), reviewed_by=staff,
        )
        # Column default puts it APPROVED; the backfill must correct that.
        MarketingWorkspace.objects.filter(pk=ws.pk).update(approval_status='APPROVED')

        backfill_fn()(django_apps, None)

        ws.refresh_from_db()
        self.assertEqual(ws.approval_status, MarketingWorkspace.Approval.REJECTED)
        self.assertEqual(spend_block(ws).code, 'CLIENT_REJECTED')

    def test_legacy_client_that_archived_its_own_brands_stays_approved(self):
        ws = MarketingWorkspace.objects.create(customer_id='l', workspace_name='Legacy')
        Brand.objects.create(workspace=ws, name='Old', status=Brand.Status.ARCHIVED)  # no reviewer
        backfill_fn()(django_apps, None)
        ws.refresh_from_db()
        self.assertEqual(ws.approval_status, MarketingWorkspace.Approval.APPROVED)

    def test_pending_signup_is_marked_pending(self):
        ws = MarketingWorkspace.objects.create(customer_id='p', workspace_name='Pending')
        Brand.objects.create(workspace=ws, name='P', status=Brand.Status.PENDING)
        backfill_fn()(django_apps, None)
        ws.refresh_from_db()
        self.assertEqual(ws.approval_status, MarketingWorkspace.Approval.PENDING)


# ───────────────────────────────────────── P0  Django admin cannot create tenancy

class AdminCannotCreateTenancyTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission

        self.staff = User.objects.create_user(username='staff@x.test', password='pw', is_staff=True)
        self.staff.user_permissions.add(*Permission.objects.filter(
            content_type__app_label__in=['workspaces', 'brands']
        ))
        self.client.force_login(self.staff)
        self.workspace = MarketingWorkspace.objects.create(customer_id='c', workspace_name='Approved Co')

    def test_staff_cannot_add_a_workspace(self):
        response = self.client.get(reverse('admin:workspaces_marketingworkspace_add'))
        self.assertEqual(response.status_code, 403)
        before = MarketingWorkspace.objects.count()
        self.client.post(reverse('admin:workspaces_marketingworkspace_add'), {
            'customer_id': 'x', 'workspace_name': 'Backdoor', 'timezone': 'UTC',
            'default_language': 'en', '_save': 'Save',
        })
        self.assertEqual(MarketingWorkspace.objects.count(), before)

    def test_staff_cannot_add_or_change_a_membership(self):
        self.assertEqual(self.client.get(reverse('admin:workspaces_workspacemember_add')).status_code, 403)
        before = WorkspaceMember.objects.count()
        self.client.post(reverse('admin:workspaces_workspacemember_add'), {
            'workspace': str(self.workspace.pk), 'user': str(self.staff.pk),
            'role': 'OWNER', 'status': 'ACTIVE', '_save': 'Save',
        })
        self.assertEqual(WorkspaceMember.objects.count(), before)
        # Nor through the inline on the workspace change form.
        self.client.post(reverse('admin:workspaces_marketingworkspace_change', args=[self.workspace.pk]), {
            'customer_id': 'c', 'workspace_name': 'Approved Co', 'timezone': 'UTC',
            'default_language': 'en',
            'members-TOTAL_FORMS': '1', 'members-INITIAL_FORMS': '0',
            'members-MIN_NUM_FORMS': '0', 'members-MAX_NUM_FORMS': '1000',
            'members-0-user': str(self.staff.pk), 'members-0-role': 'OWNER',
            'members-0-status': 'ACTIVE', 'members-0-workspace': str(self.workspace.pk),
            '_save': 'Save',
        })
        self.assertEqual(WorkspaceMember.objects.count(), before)

    def test_staff_cannot_add_a_brand(self):
        self.assertEqual(self.client.get(reverse('admin:brands_brand_add')).status_code, 403)
        before = Brand.objects.count()
        self.client.post(reverse('admin:brands_brand_add'), {
            'workspace': str(self.workspace.pk), 'name': 'Backdoor', 'status': 'ACTIVE',
            'palette': '{}', 'fonts': '{}', 'layout_preference': 'agency_column',
            'competitors': '[]', 'creative_brain': '{}', '_save': 'Save',
        })
        self.assertEqual(Brand.objects.count(), before)


# ─────────────────────────────── P1  rejected client cannot un-archive its brand

class RejectedClientCannotRestoreBrandTests(TenantFixtureMixin, TestCase):
    def test_patch_archived_to_active_is_refused_for_a_rejected_client(self):
        workspace = self.make_workspace('Rejected Co', 'c1')
        user, api = self.authenticate_as(workspace, WorkspaceMember.Role.OWNER, 'owner')
        brand = Brand.objects.create(workspace=workspace, name='R', status=Brand.Status.PENDING)
        reject_brand(brand, by=user, reason='no')
        brand.refresh_from_db()
        self.assertEqual(brand.status, Brand.Status.ARCHIVED)

        # The workspace is archived by rejection, so writes are refused at the
        # gate (403); even if it were not, the serializer refuses the flip.
        response = api.patch(
            f'{BRANDS}{brand.id}/', {'status': 'ACTIVE'}, format='json',
            **workspace_header(workspace),
        )
        self.assertIn(response.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN))
        brand.refresh_from_db()
        self.assertEqual(brand.status, Brand.Status.ARCHIVED)

    def test_serializer_refuses_status_changes_for_unapproved_clients_directly(self):
        from apps.brands.serializers import BrandSerializer

        workspace = self.make_workspace('Pending Co', 'c2')
        workspace.approval_status = MarketingWorkspace.Approval.REJECTED
        workspace.save(update_fields=['approval_status'])
        brand = Brand.objects.create(workspace=workspace, name='R', status=Brand.Status.ARCHIVED)
        serializer = BrandSerializer(brand, data={'status': 'ACTIVE'}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn('status', serializer.errors)


# ──────────────────────────── P1  rejection archives the client; approval revives it

class RejectionArchivesClientTests(TenantFixtureMixin, TestCase):
    def test_rejecting_stops_scheduled_publishing_and_approval_restores_it(self):
        workspace = self.make_workspace('Pending Co', 'c1')
        workspace.approval_status = MarketingWorkspace.Approval.PENDING
        workspace.save(update_fields=['approval_status'])
        brand = Brand.objects.create(workspace=workspace, name='P', status=Brand.Status.PENDING)
        asset = MarketingAsset.objects.create(
            workspace=workspace, asset_type=MarketingAsset.AssetType.IMAGE,
            file_name='a.png', file_url='https://example.test/a.png',
        )
        job = PublishingJob.objects.create(
            workspace=workspace, asset=asset, status=PublishingJob.Status.SCHEDULED,
            publish_mode=PublishingJob.PublishMode.SCHEDULED,
            scheduled_at=timezone.now() - timezone.timedelta(minutes=1),
        )
        self.assertIn(job, due_jobs())

        reject_brand(brand, by=None, reason='not a fit')
        workspace.refresh_from_db()
        self.assertEqual(workspace.status, MarketingWorkspace.Status.ARCHIVED)
        self.assertEqual(workspace.approval_status, MarketingWorkspace.Approval.REJECTED)
        self.assertNotIn(job, due_jobs())
        job.refresh_from_db()
        self.assertEqual(job.status, PublishingJob.Status.CANCELLED)

        Plan.objects.get_or_create(key='free', defaults={'name': 'Free', 'is_default': True})
        approve_brand(brand, by=None)
        workspace.refresh_from_db()
        self.assertEqual(workspace.status, MarketingWorkspace.Status.ACTIVE)
        self.assertEqual(workspace.approval_status, MarketingWorkspace.Approval.APPROVED)
        self.assertIsNone(spend_block(workspace))


# ──────────────────────── P1  reactivate restores only what archive cancelled

class ReactivateRestoresOnlyArchiveCancellationsTests(TenantFixtureMixin, TestCase):
    def test_a_subscription_cancelled_before_archive_stays_cancelled(self):
        workspace = self.make_workspace('Acme', 'c1')
        plan = Plan.objects.create(key='p-x', name='P')
        subscription = Subscription.objects.create(
            workspace=workspace, plan=plan, status=Subscription.Status.CANCELLED,  # non-payment
        )
        archive_workspace(workspace, by=None, reason='churn')
        entry = PlatformAuditLog.objects.get(action='CLIENT_ARCHIVED')
        self.assertEqual(entry.detail['cancelled_subscription_ids'], [])

        reactivate_workspace(workspace, by=None)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, Subscription.Status.CANCELLED)

    def test_a_subscription_archive_cancelled_is_restored(self):
        workspace = self.make_workspace('Acme', 'c2')
        plan = Plan.objects.create(key='p-y', name='P')
        subscription = Subscription.objects.create(workspace=workspace, plan=plan)
        archive_workspace(workspace, by=None)
        entry = PlatformAuditLog.objects.get(action='CLIENT_ARCHIVED')
        self.assertEqual(entry.detail['cancelled_subscription_ids'], [str(subscription.pk)])
        reactivate_workspace(workspace, by=None)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)


# ─────────────────── P1  website correction cannot take another client's claim

class WebsiteCorrectionCollisionTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.other = self.make_workspace('Other Co', 'c-other')
        SignupWebsiteClaim.objects.create(website_host='taken.test', workspace=self.other)
        self.workspace = self.make_workspace('Pending Co', 'c1')
        self.workspace.approval_status = MarketingWorkspace.Approval.PENDING
        self.workspace.save(update_fields=['approval_status'])
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Pending Co', website='https://pending.test',
            status=Brand.Status.PENDING,
        )
        staff = User.objects.create_user(username='staff@scaleezy.test', password='pw')
        grant_platform_admin(staff)
        self.api = APIClient()
        self.api.force_authenticate(user=staff)

    def test_correcting_to_a_taken_website_is_refused_and_changes_nothing(self):
        response = self.api.post(
            f'{SIGNUPS}{self.brand.id}/approve/',
            {'website': 'https://www.taken.test/'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(response.json()['error']['code'], 'WEBSITE_TAKEN')
        self.brand.refresh_from_db()
        self.workspace.refresh_from_db()
        self.assertEqual(self.brand.website, 'https://pending.test')
        self.assertEqual(self.brand.status, Brand.Status.PENDING)
        self.assertEqual(self.workspace.approval_status, MarketingWorkspace.Approval.PENDING)
        # The other client's claim is untouched.
        self.assertEqual(
            SignupWebsiteClaim.objects.get(website_host='taken.test').workspace, self.other
        )


# ────────────────────────────── P1  SSRF: only globally routable addresses

class NonGlobalAddressTests(SimpleTestCase):
    def _refused(self, ip):
        from unittest.mock import patch

        with patch('apps.universal.enrichment.socket.getaddrinfo',
                   return_value=[(2, 1, 6, '', (ip, 0))]):
            with self.assertRaises(enrichment.UnsafeURL, msg=ip):
                enrichment.assert_safe('https://acme.test/', allowed_host='acme.test')

    def test_cgnat_and_other_special_ranges_are_refused(self):
        for ip in ('100.64.0.1', '100.127.255.254', '192.0.0.8', '198.18.0.1',
                   '0.0.0.0', '240.0.0.1', 'fc00::1', 'fe80::1', '::1'):
            self._refused(ip)

    def test_a_public_address_is_still_allowed(self):
        from unittest.mock import patch

        with patch('apps.universal.enrichment.socket.getaddrinfo',
                   return_value=[(2, 1, 6, '', ('93.184.216.34', 0))]):
            self.assertTrue(enrichment.assert_safe('https://acme.test/', allowed_host='acme.test'))


# ─────────────────────────────── P1  page cap while streaming

class StreamingCapTests(SimpleTestCase):
    def test_an_oversized_page_is_capped_during_download(self):
        from unittest.mock import patch

        big = b'<html>' + b'x' * (enrichment.MAX_PAGE_BYTES * 3)

        def handler(request):
            return httpx.Response(
                200, headers={'content-type': 'text/html', 'content-length': str(len(big))},
                content=big,
            )

        with patch('apps.universal.enrichment.socket.getaddrinfo',
                   return_value=[(2, 1, 6, '', ('93.184.216.34', 0))]):
            text, digest = enrichment.safe_fetch(
                'https://acme.test/', allowed_host='acme.test',
                transport=httpx.MockTransport(handler),
            )
        # Never more than the cap was kept; the hash is of the capped bytes.
        self.assertLessEqual(len(text.encode('utf-8')), enrichment.MAX_PAGE_BYTES + 16)
        self.assertTrue(digest)
