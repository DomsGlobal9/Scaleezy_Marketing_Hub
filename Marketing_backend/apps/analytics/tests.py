"""
The Overview KPIs are counts of real rows, scoped to the caller's workspace.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.brands.models import Brand
from apps.content.models import ContentItem
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

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
