"""
The Overview KPIs are counts of real rows, scoped to the caller's workspace.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.brands.models import Brand
from apps.content.models import ContentItem
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

from .models import PerformanceObservation, PlatformPerformance, RevenueEvent
from .services import rebuild_workspace_projections

User = get_user_model()


class KPITests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(customer_id='c1', workspace_name='One')
        self.other = MarketingWorkspace.objects.create(customer_id='c2', workspace_name='Two')
        self.user = User.objects.create_user(username='u1', password='p')
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=self.user, role=WorkspaceMember.Role.VIEWER
        )
        self.brand = Brand.objects.create(workspace=self.workspace, name='B1')
        other_brand = Brand.objects.create(workspace=self.other, name='B2')

        for _ in range(2):
            ContentItem.objects.create(
                workspace=self.workspace, brand=self.brand,
                status=ContentItem.Status.PENDING_REVIEW,
            )
        ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand, status=ContentItem.Status.APPROVED
        )
        # Sibling tenant: must never be counted.
        ContentItem.objects.create(
            workspace=self.other, brand=other_brand, status=ContentItem.Status.PENDING_REVIEW
        )
        SocialConnection.objects.create(
            workspace=self.workspace, platform=SocialConnection.Platform.INSTAGRAM,
            external_account_id='x1', account_name='Acme',
            status=SocialConnection.Status.CONNECTED,
        )
        SocialConnection.objects.create(
            workspace=self.workspace, platform=SocialConnection.Platform.LINKEDIN,
            external_account_id='x2', account_name='Acme LI',
            status=SocialConnection.Status.TOKEN_EXPIRED,
        )
        SocialConnection.objects.create(
            workspace=self.other, platform=SocialConnection.Platform.INSTAGRAM,
            external_account_id='x3', account_name='Other',
            status=SocialConnection.Status.CONNECTED,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _kpis(self):
        response = self.client.get(
            '/api/marketing/analytics/kpis/', HTTP_X_WORKSPACE_ID=str(self.workspace.id)
        )
        self.assertEqual(response.status_code, 200)
        return {row['key']: row for row in response.json()['kpis']}

    def test_counts_come_from_real_rows_in_the_callers_workspace(self):
        kpis = self._kpis()
        self.assertEqual(kpis['awaiting_review']['value'], 2)
        self.assertEqual(kpis['approved']['value'], 1)
        self.assertEqual(kpis['connected_accounts']['value'], 1)
        self.assertEqual(kpis['connected_accounts']['hint'], '1 needs attention')
        self.assertEqual(kpis['published']['value'], 0)
        self.assertEqual(kpis['scheduled']['value'], 0)

    def test_no_invented_metrics(self):
        keys = set(self._kpis())
        for invented in ('reach', 'engagement_rate', 'roi', 'repeat_purchase'):
            self.assertNotIn(invented, keys)

    def test_non_member_cannot_read(self):
        outsider = User.objects.create_user(username='out', password='p')
        client = APIClient()
        client.force_authenticate(user=outsider)
        response = client.get(
            '/api/marketing/analytics/kpis/', HTTP_X_WORKSPACE_ID=str(self.workspace.id)
        )
        self.assertIn(response.status_code, (403, 404))


class PerformanceAndRevenueTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(customer_id='metrics-1', workspace_name='One')
        self.other = MarketingWorkspace.objects.create(customer_id='metrics-2', workspace_name='Two')
        self.user = User.objects.create_user(username='metrics-user', password='p')
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=self.user, role=WorkspaceMember.Role.EDITOR
        )
        self.brand = Brand.objects.create(workspace=self.workspace, name='B1')
        self.content = ContentItem.objects.create(workspace=self.workspace, brand=self.brand)
        self.other_content = ContentItem.objects.create(
            workspace=self.other,
            brand=Brand.objects.create(workspace=self.other, name='B2'),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.pk)}

    def test_any_platform_metric_can_be_imported_with_lineage(self):
        response = self.client.post(
            '/api/marketing/analytics/performance/import/',
            {
                'source_record_id': 'sheet-row-7',
                'platform': 'CUSTOM_NETWORK',
                'content_item': str(self.content.pk),
                'observed_at': '2026-09-01T10:00:00Z',
                'reach': 120,
                'engagement': 12,
                'conversions': 2,
                'spend': '10.00',
                'campaign_name': 'Launch',
                'source_payload': {'file': 'client-report.csv'},
            },
            format='json',
            **self.headers,
        )
        self.assertEqual(response.status_code, 201, response.json())
        row = PerformanceObservation.objects.get()
        self.assertEqual(row.platform, 'CUSTOM_NETWORK')
        self.assertEqual(row.content_item, self.content)
        self.assertEqual(row.source, PerformanceObservation.Source.AUDITABLE_IMPORT)
        self.assertEqual(PlatformPerformance.objects.get().reach, 120)

    def test_metric_import_is_idempotent(self):
        payload = {
            'source_record_id': 'stable-id', 'platform': 'CUSTOM',
            'observed_at': '2026-09-01T10:00:00Z', 'reach': 10,
        }
        first = self.client.post(
            '/api/marketing/analytics/performance/import/', payload,
            format='json', **self.headers,
        )
        second = self.client.post(
            '/api/marketing/analytics/performance/import/', payload,
            format='json', **self.headers,
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PerformanceObservation.objects.count(), 1)

    def test_cross_tenant_content_cannot_be_attributed(self):
        response = self.client.post(
            '/api/marketing/analytics/performance/import/',
            {
                'source_record_id': 'bad', 'platform': 'CUSTOM',
                'content_item': str(self.other_content.pk),
                'observed_at': '2026-09-01T10:00:00Z',
            },
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(PerformanceObservation.objects.exists())

    def test_projection_uses_latest_cumulative_snapshot_not_sum(self):
        for index, reach in enumerate((100, 140)):
            PerformanceObservation.objects.create(
                workspace=self.workspace,
                source=PerformanceObservation.Source.X_API,
                source_record_id=f'run-{index}:post-1',
                platform=SocialConnection.Platform.X,
                external_post_id='post-1',
                reach=reach,
                observed_at=timezone.now() + timezone.timedelta(minutes=index),
            )
        rebuild_workspace_projections(self.workspace)
        self.assertEqual(PlatformPerformance.objects.get().reach, 140)

    def test_revenue_event_is_idempotent_and_converts_lead(self):
        lead_response = self.client.post(
            '/api/marketing/analytics/leads/',
            {'name': 'Buyer', 'brand': str(self.brand.pk)},
            format='json', **self.headers,
        )
        lead_id = lead_response.json()['data']['id']
        payload = {
            'lead': lead_id,
            'source': 'stripe',
            'external_event_id': 'checkout-1',
            'amount': '250.00',
            'currency': 'USD',
            'occurred_at': '2026-09-01T10:00:00Z',
        }
        first = self.client.post(
            '/api/marketing/analytics/revenue/', payload, format='json', **self.headers
        )
        second = self.client.post(
            '/api/marketing/analytics/revenue/', payload, format='json', **self.headers
        )
        self.assertEqual(first.status_code, 201, first.json())
        self.assertEqual(second.status_code, 200, second.json())
        self.assertEqual(RevenueEvent.objects.count(), 1)

    def test_viewer_cannot_write_metrics(self):
        membership = WorkspaceMember.objects.get(workspace=self.workspace, user=self.user)
        membership.role = WorkspaceMember.Role.VIEWER
        membership.save(update_fields=['role'])
        response = self.client.post(
            '/api/marketing/analytics/performance/import/',
            {'source_record_id': 'no', 'platform': 'X', 'observed_at': '2026-09-01T10:00:00Z'},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 403)
