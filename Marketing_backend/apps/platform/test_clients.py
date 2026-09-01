"""
P2 portfolio + P3 client detail, proven from the outside.

A workspace owner — even `is_staff` — gets 403 from both endpoints; a platform
admin gets rows whose every number matches what was actually seeded, each
filter returns exactly the clients its flag describes, the detail page carries
the brain / team / audit sections, and every successful call leaves an audit
row.
"""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.ai.models import AIProvider, AIUsageLog, Capability, WorkspaceAIRoute
from apps.audit.models import PlatformAuditLog, record_platform_event
from apps.audit.services import grant_platform_admin
from apps.billing.models import Plan, Subscription
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.content.models import ContentItem
from apps.inspirations.models import BrandInspiration
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import BrandRule
from apps.marketing.models import MarketingAsset
from apps.publishing.models import PublishingJob
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()

CLIENTS = '/api/platform/clients/'


def detail_url(workspace):
    return f'{CLIENTS}{workspace.pk}/'


class ClientPortfolioTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.plan, _ = Plan.objects.get_or_create(
            key='free', defaults={'name': 'Free', 'is_default': True}
        )

        # Acme: approved, an active member who was just here, one content item.
        self.acme = self.make_workspace('Acme Co', 'acme')
        self.owner, self.owner_api = self.authenticate_as(
            self.acme, WorkspaceMember.Role.OWNER, 'owner@acme.test'
        )
        WorkspaceMember.objects.filter(workspace=self.acme, user=self.owner).update(
            last_active_at=timezone.now()
        )
        self.acme_brand = Brand.objects.create(
            workspace=self.acme, name='Acme', website='https://acme.test',
            industry='Retail', is_default=True, status=Brand.Status.ACTIVE,
        )
        self.content = ContentItem.objects.create(
            workspace=self.acme, brand=self.acme_brand, headline='Spring sale',
            status=ContentItem.Status.PUBLISHED,
        )

        self.staff = User.objects.create_user(username='staff@scaleezy.test', password='pw')
        grant_platform_admin(self.staff, note='test')
        self.staff_api = APIClient()
        self.staff_api.force_authenticate(user=self.staff)

    # ───────────────────────────────────────────── helpers

    def other_workspace(self, name, *, brand_status=Brand.Status.ACTIVE, active_days_ago=0):
        workspace = self.make_workspace(name, name.lower())
        user, _ = self.authenticate_as(workspace, WorkspaceMember.Role.OWNER, f'owner@{name.lower()}.test')
        WorkspaceMember.objects.filter(workspace=workspace, user=user).update(
            last_active_at=timezone.now() - timedelta(days=active_days_ago)
        )
        brand = Brand.objects.create(
            workspace=workspace, name=name, is_default=True, status=brand_status,
        )
        return workspace, brand

    def rows_for(self, **params):
        response = self.staff_api.get(CLIENTS, params)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        return data, {row['workspace_id']: row for row in data['clients']}

    # ───────────────────────────────────────────── the boundary

    def test_only_platform_admins_reach_the_portfolio(self):
        for url in (CLIENTS, detail_url(self.acme)):
            self.assertEqual(self.owner_api.get(url).status_code, status.HTTP_403_FORBIDDEN, url)
            self.assertEqual(APIClient().get(url).status_code, status.HTTP_401_UNAUTHORIZED, url)
        self.owner.is_staff = True
        self.owner.is_superuser = True
        self.owner.save(update_fields=['is_staff', 'is_superuser'])
        self.assertEqual(self.owner_api.get(CLIENTS).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.staff_api.get(CLIENTS).status_code, 200)
        self.assertEqual(self.staff_api.get(detail_url(self.acme)).status_code, 200)
        # A refused caller leaves no audit row; the admin's two reads do.
        self.assertEqual(PlatformAuditLog.objects.filter(action='PORTFOLIO_VIEWED').count(), 1)
        self.assertEqual(PlatformAuditLog.objects.filter(action='CLIENT_VIEWED').count(), 1)

    # ───────────────────────────────────────────── P2 portfolio

    def test_portfolio_lists_the_seeded_client_with_real_counts(self):
        source = BrandSource.objects.create(
            workspace=self.acme, brand=self.acme_brand, title='Brand deck',
            status=BrandSource.SourceStatus.READY,
        )
        BrandSource.objects.create(
            workspace=self.acme, brand=self.acme_brand, title='Old deck',
            status=BrandSource.SourceStatus.ARCHIVED,
        )
        BrandMemory.objects.create(
            workspace=self.acme, brand=self.acme_brand, source=source,
            memory_type=BrandMemory.MemoryType.FACT, content='Founded 1999',
            status=BrandMemory.MemoryStatus.CONFIRMED,
        )
        BrandMemory.objects.create(
            workspace=self.acme, brand=self.acme_brand, source=source,
            memory_type=BrandMemory.MemoryType.FACT, content='Maybe',
            status=BrandMemory.MemoryStatus.CANDIDATE,
        )
        BrandInspiration.objects.create(
            workspace=self.acme, brand=self.acme_brand, title='Nice ad',
        )
        BrandRule.objects.create(
            workspace=self.acme, brand=self.acme_brand, text='Never use red',
        )
        ContentItem.objects.create(
            workspace=self.acme, brand=self.acme_brand, headline='Draft one',
            status=ContentItem.Status.DRAFT,
        )
        # The period must open before the content was made, or the quota
        # service — correctly — counts none of it against this period.
        Subscription.objects.create(
            workspace=self.acme, plan=self.plan,
            period_start=timezone.now() - timedelta(days=1),
        )

        data, by_id = self.rows_for()
        self.assertEqual(data['filter'], 'all')
        self.assertEqual(data['days'], 14)
        row = by_id[str(self.acme.pk)]
        self.assertEqual(row['client_code'], self.acme.client_code)
        self.assertEqual(row['name'], 'Acme Co')
        self.assertEqual(row['status'], MarketingWorkspace.Status.ACTIVE)
        self.assertEqual(row['brand']['name'], 'Acme')
        self.assertEqual(row['brand']['industry'], 'Retail')
        self.assertEqual(row['plan'], {'key': 'free', 'name': self.plan.name})
        self.assertEqual(row['subscription_status'], Subscription.Status.ACTIVE)
        self.assertEqual(row['counts'], {
            'knowledge_sources': 1, 'confirmed_facts': 1, 'inspirations': 1,
            'rules': 1, 'preferences': 0, 'team': 1,
        })
        self.assertEqual(row['content']['total'], 2)
        self.assertEqual(row['content']['by_status'], {'PUBLISHED': 1, 'DRAFT': 1})
        self.assertEqual(row['publishing'], {'published': 0, 'failed': 0, 'scheduled': 0, 'queued': 0})
        self.assertTrue(row['usage']['subscribed'])
        self.assertEqual(row['usage']['generations_used'], 2)
        self.assertIsInstance(row['readiness']['score'], int)
        self.assertIn(row['readiness']['level'], ('STARTING', 'LEARNING', 'STRONG', 'READY'))
        self.assertEqual(row['onboarding']['status'], 'COMPLETED')
        self.assertIsNotNone(row['last_active_at'])
        # Approved, active, generated, recently active — but no AI route yet.
        self.assertEqual(row['flags'], ['NO_AI_ROUTING'])

        entry = PlatformAuditLog.objects.get(action='PORTFOLIO_VIEWED')
        self.assertEqual(entry.detail['filter'], 'all')
        self.assertEqual(entry.detail['count'], 1)

    def test_a_client_without_a_brand_has_null_brand_sections(self):
        bare = self.make_workspace('Bare', 'bare')
        _, by_id = self.rows_for()
        row = by_id[str(bare.pk)]
        self.assertIsNone(row['brand'])
        self.assertIsNone(row['onboarding'])
        self.assertIsNone(row['readiness'])
        self.assertIsNone(row['plan'])
        self.assertIsNone(row['last_active_at'])
        self.assertFalse(row['usage']['subscribed'])
        self.assertNotIn('PENDING_APPROVAL', row['flags'])
        self.assertIn('NEVER_GENERATED', row['flags'])

    def test_pending_filter_returns_only_clients_awaiting_approval(self):
        pending, _ = self.other_workspace('Newco', brand_status=Brand.Status.PENDING)
        data, by_id = self.rows_for(filter='pending')
        self.assertEqual(data['filter'], 'pending')
        self.assertEqual(set(by_id), {str(pending.pk)})
        self.assertIn('PENDING_APPROVAL', by_id[str(pending.pk)]['flags'])
        self.assertEqual(PlatformAuditLog.objects.get(action='PORTFOLIO_VIEWED').detail['filter'], 'pending')

    def test_inactive_filter_honours_days(self):
        quiet, _ = self.other_workspace('Quiet', active_days_ago=20)
        _, by_id = self.rows_for(filter='inactive')
        self.assertEqual(set(by_id), {str(quiet.pk)})
        self.assertIn('INACTIVE', by_id[str(quiet.pk)]['flags'])

        data, by_id = self.rows_for(filter='inactive', days=30)
        self.assertEqual(data['days'], 30)
        self.assertEqual(by_id, {})

    def test_failing_publishes_filter(self):
        broken, _ = self.other_workspace('Broken')
        asset = MarketingAsset.objects.create(
            workspace=broken, file_name='p.jpg', source=MarketingAsset.Source.MANUAL_UPLOAD
        )
        PublishingJob.objects.create(workspace=broken, asset=asset, status=PublishingJob.Status.FAILED)
        PublishingJob.objects.create(workspace=broken, asset=asset, status=PublishingJob.Status.SCHEDULED)

        _, by_id = self.rows_for(filter='failing_publishes')
        self.assertEqual(set(by_id), {str(broken.pk)})
        row = by_id[str(broken.pk)]
        self.assertIn('FAILING_PUBLISHES', row['flags'])
        self.assertEqual(row['publishing']['failed'], 1)
        self.assertEqual(row['publishing']['scheduled'], 1)

    def test_over_quota_filter_uses_capability_overrides_and_usage_logs(self):
        capped, _ = self.other_workspace('Capped')
        Subscription.objects.create(
            workspace=capped, plan=self.plan, capability_limit_overrides={'IMAGE': 2},
        )
        for _ in range(2):
            AIUsageLog.objects.create(
                workspace=capped, capability=Capability.IMAGE, success=True, selected=True,
            )
        # Acme has a subscription too, but nothing spent against a ceiling.
        Subscription.objects.create(workspace=self.acme, plan=self.plan)

        _, by_id = self.rows_for(filter='over_quota')
        self.assertEqual(set(by_id), {str(capped.pk)})
        row = by_id[str(capped.pk)]
        self.assertIn('OVER_QUOTA', row['flags'])
        image = next(c for c in row['usage']['capabilities'] if c['capability'] == 'IMAGE')
        self.assertEqual((image['used'], image['limit'], image['overridden']), (2, 2, True))

    def test_never_generated_suspended_and_archived_filters(self):
        from apps.workspaces.services.lifecycle import archive_workspace, suspend_workspace

        idle, _ = self.other_workspace('Idle')
        paused, _ = self.other_workspace('Paused')
        suspend_workspace(paused, by=self.staff, reason='unpaid')
        gone, _ = self.other_workspace('Gone')
        archive_workspace(gone, by=self.staff)

        _, by_id = self.rows_for(filter='never_generated')
        self.assertEqual(set(by_id), {str(idle.pk), str(paused.pk), str(gone.pk)})

        _, by_id = self.rows_for(filter='suspended')
        self.assertEqual(set(by_id), {str(paused.pk)})
        self.assertIn('SUSPENDED', by_id[str(paused.pk)]['flags'])
        self.assertEqual(by_id[str(paused.pk)]['status_reason'], 'unpaid')

        _, by_id = self.rows_for(filter='archived')
        self.assertEqual(set(by_id), {str(gone.pk)})
        row = by_id[str(gone.pk)]
        self.assertIn('ARCHIVED', row['flags'])
        # A client that is deliberately off is not "at risk" for being quiet.
        self.assertNotIn('INACTIVE', row['flags'])
        self.assertNotIn('NO_AI_ROUTING', row['flags'])

    def test_at_risk_filter_and_the_routing_flag(self):
        provider = AIProvider.objects.create(
            key='mock', display_name='Mock', capabilities=[Capability.TEXT]
        )
        WorkspaceAIRoute.objects.create(
            workspace=self.acme, capability=Capability.TEXT, provider=provider,
        )
        stale, stale_brand = self.other_workspace('Stale')
        WorkspaceAIRoute.objects.create(
            workspace=stale, capability=Capability.TEXT, provider=provider,
        )
        stale_brand.brain_failed_at = timezone.now()
        stale_brand.brain_last_error = 'boom'
        stale_brand.save(update_fields=['brain_failed_at', 'brain_last_error'])

        _, by_id = self.rows_for(filter='at_risk')
        self.assertEqual(set(by_id), {str(stale.pk)})
        self.assertIn('BRAIN_STALE', by_id[str(stale.pk)]['flags'])

        _, by_id = self.rows_for()
        self.assertNotIn('NO_AI_ROUTING', by_id[str(self.acme.pk)]['flags'])

    def test_q_matches_code_name_and_brand(self):
        other, _ = self.other_workspace('Zed Industries')
        _, by_id = self.rows_for(q=self.acme.client_code.lower())
        self.assertEqual(set(by_id), {str(self.acme.pk)})
        _, by_id = self.rows_for(q='zed ind')
        self.assertEqual(set(by_id), {str(other.pk)})
        _, by_id = self.rows_for(q='acme')
        self.assertEqual(set(by_id), {str(self.acme.pk)})
        _, by_id = self.rows_for(q='nobody-here')
        self.assertEqual(by_id, {})

    def test_portfolio_pages_before_building_client_rows(self):
        created = []
        for index in range(4):
            workspace, _brand = self.other_workspace(f'Page {index}')
            created.append(workspace)

        first, first_rows = self.rows_for(page=1, page_size=2)
        second, second_rows = self.rows_for(page=2, page_size=2)

        self.assertEqual(first['total'], 5)
        self.assertEqual(first['count'], 5)
        self.assertEqual(first['page_size'], 2)
        self.assertEqual(first['total_pages'], 3)
        self.assertEqual(first['next_page'], 2)
        self.assertIsNone(first['previous_page'])
        self.assertEqual(second['previous_page'], 1)
        self.assertTrue(set(first_rows).isdisjoint(second_rows))

    def test_portfolio_get_never_creates_or_updates_onboarding_state(self):
        from apps.onboarding.models import BrandOnboarding

        self.assertFalse(BrandOnboarding.objects.filter(brand=self.acme_brand).exists())
        _data, by_id = self.rows_for()
        self.assertEqual(by_id[str(self.acme.pk)]['onboarding']['status'], 'COMPLETED')
        self.assertFalse(BrandOnboarding.objects.filter(brand=self.acme_brand).exists())

    def test_portfolio_query_count_is_bounded_as_clients_grow(self):
        for index in range(8):
            self.other_workspace(f'Scale {index}')
        Subscription.objects.create(
            workspace=self.acme,
            plan=self.plan,
            period_start=timezone.now() - timedelta(days=1),
        )

        with CaptureQueriesContext(connection) as queries:
            response = self.staff_api.get(CLIENTS, {'page_size': 10})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertLessEqual(len(queries), 27, [query['sql'] for query in queries])

    # ───────────────────────────────────────────── P3 detail

    def test_detail_returns_brain_team_audit_and_activity_sections(self):
        from apps.onboarding.models import BrandOnboarding

        self.acme_brand.brain_failed_at = timezone.now()
        self.acme_brand.brain_last_error = 'conflict'
        self.acme_brand.save(update_fields=['brain_failed_at', 'brain_last_error'])
        record_platform_event(
            actor=self.staff, action='BRAND_APPROVED', workspace=self.acme,
            target=f'brand:{self.acme_brand.pk}', detail={'brand_name': 'Acme'},
        )
        AIUsageLog.objects.create(
            workspace=self.acme, capability=Capability.TEXT, success=False,
            error='timeout', latency_ms=1200, cost='0.0125',
        )

        response = self.staff_api.get(detail_url(self.acme))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']

        self.assertEqual(data['client']['workspace_id'], str(self.acme.pk))
        self.assertIn('BRAIN_STALE', data['client']['flags'])
        self.assertTrue(data['brain']['stale'])
        self.assertEqual(data['brain']['last_error'], 'conflict')
        self.assertIsNone(data['brain']['compiled_at'])
        self.assertEqual(data['onboarding']['status'], 'COMPLETED')
        self.assertEqual(data['onboarding']['skipped_steps'], [])

        self.assertEqual([c['headline'] for c in data['recent_content']], ['Spring sale'])
        self.assertEqual(data['recent_publishing'], [])
        call = data['recent_ai_calls'][0]
        self.assertEqual((call['capability'], call['success'], call['error']), ('TEXT', False, 'timeout'))
        self.assertEqual(call['cost'], '0.01')
        self.assertIsNone(call['provider'])

        self.assertEqual(len(data['team']), 1)
        self.assertEqual(data['team'][0]['username'], 'owner@acme.test')
        self.assertEqual(data['team'][0]['role'], 'OWNER')

        self.assertEqual([a['action'] for a in data['audit']], ['BRAND_APPROVED'])
        self.assertEqual(data['audit'][0]['actor_username'], 'staff@scaleezy.test')
        self.assertEqual(data['universal'], {'standards_enabled': True, 'inspirations_enabled': True})

        entry = PlatformAuditLog.objects.get(action='CLIENT_VIEWED')
        self.assertEqual(entry.workspace_id, self.acme.pk)
        self.assertEqual(entry.detail['workspace_id'], str(self.acme.pk))
        self.assertFalse(BrandOnboarding.objects.filter(brand=self.acme_brand).exists())

    def test_unknown_client_is_404(self):
        response = self.staff_api.get(f'{CLIENTS}{uuid.uuid4()}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()['error']['code'], 'NOT_FOUND')
        self.assertFalse(PlatformAuditLog.objects.filter(action='CLIENT_VIEWED').exists())
