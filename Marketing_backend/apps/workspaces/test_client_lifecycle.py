"""
Client identity and lifecycle.

Two things are asserted here that a status flag alone would not give you:
every client carries one unique, never-reused code, and archiving a client
actually stops the things that would otherwise keep acting in its name —
scheduled posts, AI routing, and the subscription that counts it as revenue.
"""
from django.test import TestCase
from rest_framework import status

from apps.audit.models import PlatformAuditLog
from apps.billing.models import Plan, Subscription
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.marketing.models import MarketingAsset
from apps.publishing.models import PublishingJob
from apps.publishing.scheduler import due_jobs
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember
from apps.workspaces.services.lifecycle import (
    archive_workspace,
    reactivate_workspace,
    suspend_workspace,
)
from django.utils import timezone


class ClientCodeTests(TestCase):
    def test_every_workspace_gets_a_unique_code(self):
        codes = {
            MarketingWorkspace.objects.create(
                customer_id=f'c{i}', workspace_name=f'W{i}'
            ).client_code
            for i in range(25)
        }
        self.assertEqual(len(codes), 25)
        for code in codes:
            self.assertTrue(code.startswith('SCZ-'), code)
            self.assertEqual(len(code), 12, code)

    def test_a_code_is_never_reassigned_on_later_saves(self):
        workspace = MarketingWorkspace.objects.create(customer_id='c', workspace_name='W')
        original = workspace.client_code
        workspace.workspace_name = 'Renamed'
        workspace.save(update_fields=['workspace_name'])
        workspace.refresh_from_db()
        self.assertEqual(workspace.client_code, original)

    def test_an_explicit_code_is_respected(self):
        workspace = MarketingWorkspace.objects.create(
            customer_id='c', workspace_name='W', client_code='SCZ-MIGRATED'
        )
        self.assertEqual(workspace.client_code, 'SCZ-MIGRATED')


class LifecycleTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.user, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme', is_default=True,
            status=Brand.Status.ACTIVE,
        )
        plan = Plan.objects.create(key='p', name='P')
        self.subscription = Subscription.objects.create(
            workspace=self.workspace, plan=plan
        )
        asset = MarketingAsset.objects.create(
            workspace=self.workspace, asset_type=MarketingAsset.AssetType.IMAGE,
            file_name='a.png', file_url='https://example.test/a.png',
        )
        self.job = PublishingJob.objects.create(
            workspace=self.workspace, asset=asset,
            status=PublishingJob.Status.SCHEDULED,
            publish_mode=PublishingJob.PublishMode.SCHEDULED,
            scheduled_at=timezone.now() - timezone.timedelta(minutes=5),
        )

    # ------------------------------------------------------------- suspend

    def test_suspension_stops_writes_and_scheduled_posts_but_not_reads(self):
        self.assertIn(self.job, due_jobs())

        suspend_workspace(self.workspace, by=self.user, reason='non-payment')

        self.assertNotIn(self.job, due_jobs())
        headers = workspace_header(self.workspace)
        read = self.api.get(f'/api/marketing/brands/{self.brand.id}/', **headers)
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        write = self.api.patch(
            f'/api/marketing/brands/{self.brand.id}/', {'tagline': 'x'},
            format='json', **headers,
        )
        self.assertEqual(write.status_code, status.HTTP_403_FORBIDDEN)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.tagline, '')

        # The schedule survives suspension, so paying up resumes it.
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, PublishingJob.Status.SCHEDULED)

    def test_reactivating_restores_writes_and_the_schedule(self):
        suspend_workspace(self.workspace, by=self.user)
        reactivate_workspace(self.workspace, by=self.user)
        self.assertIn(self.job, due_jobs())
        write = self.api.patch(
            f'/api/marketing/brands/{self.brand.id}/', {'tagline': 'x'},
            format='json', **workspace_header(self.workspace),
        )
        self.assertEqual(write.status_code, status.HTTP_200_OK, write.content)

    # ------------------------------------------------------------- archive

    def test_archiving_actually_stops_everything_acting_in_the_client_name(self):
        from apps.ai.models import AIProvider, WorkspaceAIRoute

        provider = AIProvider.objects.create(
            key='arch-test', display_name='Arch', capabilities=['TEXT'],
            unit_cost=0, is_available=True,
        )
        WorkspaceAIRoute.objects.create(
            workspace=self.workspace, provider=provider,
            capability='TEXT', priority=10, enabled=True,
        )

        archive_workspace(self.workspace, by=self.user, reason='churned')

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, PublishingJob.Status.CANCELLED)
        self.assertNotIn(self.job, due_jobs())
        self.assertFalse(
            WorkspaceAIRoute.objects.filter(workspace=self.workspace, enabled=True).exists()
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.CANCELLED)

        # Nothing destroyed: the client's data is all still there.
        self.assertTrue(Brand.objects.filter(pk=self.brand.pk).exists())
        self.assertTrue(PublishingJob.objects.filter(pk=self.job.pk).exists())

        entry = PlatformAuditLog.objects.get(action='CLIENT_ARCHIVED')
        self.assertEqual(entry.workspace, self.workspace)
        self.assertEqual(entry.detail['cancelled_publishing_jobs'], 1)
        self.assertEqual(entry.detail['disabled_ai_routes'], 1)
        self.assertEqual(entry.detail['reason'], 'churned')

    def test_archive_is_reversible_and_restores_routing(self):
        archive_workspace(self.workspace, by=self.user)
        reactivate_workspace(self.workspace, by=self.user)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.status, MarketingWorkspace.Status.ACTIVE)
        self.assertTrue(
            PlatformAuditLog.objects.filter(action='CLIENT_REACTIVATED').exists()
        )

    def test_transitions_are_idempotent(self):
        archive_workspace(self.workspace, by=self.user)
        archive_workspace(self.workspace, by=self.user)
        self.assertEqual(
            PlatformAuditLog.objects.filter(action='CLIENT_ARCHIVED').count(), 1
        )


class PlatformAuditTests(TestCase):
    def test_platform_admin_cannot_be_obtained_by_workspace_membership(self):
        from apps.audit.models import is_platform_admin
        from django.contrib.auth import get_user_model

        User = get_user_model()
        workspace = MarketingWorkspace.objects.create(customer_id='c', workspace_name='W')
        user = User.objects.create_user(username='owner@x.test', password='pw')
        WorkspaceMember.objects.create(
            workspace=workspace, user=user, role=WorkspaceMember.Role.OWNER
        )
        self.assertFalse(is_platform_admin(user))

        # Nor by is_staff, which is a Django-admin decision, not a platform one.
        user.is_staff = True
        user.save(update_fields=['is_staff'])
        self.assertFalse(is_platform_admin(user))

    def test_grant_and_revoke_are_live_and_audited(self):
        from django.contrib.auth import get_user_model
        from django.core.management import call_command

        from apps.audit.models import is_platform_admin

        User = get_user_model()
        user = User.objects.create_user(username='staff@scaleezy.test', password='pw')
        # A second admin, because revoking the last one is refused on purpose.
        keeper = User.objects.create_user(username='keeper@scaleezy.test', password='pw')

        call_command('grant_platform_admin', 'staff@scaleezy.test', verbosity=0)
        call_command('grant_platform_admin', 'keeper@scaleezy.test', verbosity=0)
        self.assertTrue(is_platform_admin(user))
        self.assertTrue(
            PlatformAuditLog.objects.filter(action='PLATFORM_ADMIN_GRANTED').exists()
        )

        call_command('grant_platform_admin', 'staff@scaleezy.test', '--revoke', verbosity=0)
        # Live check, so revocation takes effect immediately — no token to expire.
        self.assertFalse(is_platform_admin(user))
        self.assertTrue(is_platform_admin(keeper))
        self.assertTrue(
            PlatformAuditLog.objects.filter(action='PLATFORM_ADMIN_REVOKED').exists()
        )

    def test_audit_rows_are_immutable(self):
        entry = PlatformAuditLog.objects.create(action='TEST', target='x')
        entry.action = 'TAMPERED'
        with self.assertRaises(ValueError):
            entry.save()
