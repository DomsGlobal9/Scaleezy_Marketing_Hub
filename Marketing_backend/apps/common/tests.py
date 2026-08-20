"""
Phase 1c — the API is closed by default and scoped per tenant.

Two users in two workspaces. Every assertion is about what Mallory (a real,
authenticated user of workspace B) can reach in workspace A. Anonymous access
is checked too, but the cross-tenant case is the one that matters: before this
change, authentication alone would have changed "anyone" to "any account"
while every queryset still returned all rows.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.marketing.models import MarketingAsset
from apps.publishing.models import PublishingJob, PublishingJobItem
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()


class TenantIsolationTests(APITestCase):
    def setUp(self):
        self.ws_a = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.ws_b = MarketingWorkspace.objects.create(customer_id='b', workspace_name='Beta')

        self.alice = User.objects.create_user(username='alice', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws_a, user=self.alice, role=WorkspaceMember.Role.OWNER
        )
        self.mallory = User.objects.create_user(username='mallory', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws_b, user=self.mallory, role=WorkspaceMember.Role.OWNER
        )

        self.asset_a = MarketingAsset.objects.create(
            workspace=self.ws_a, file_name='alpha.jpg', source='MANUAL_UPLOAD'
        )
        self.conn_a = SocialConnection.objects.create(
            workspace=self.ws_a, platform='X', external_account_id='x1',
            account_name='Alpha X', status=SocialConnection.Status.CONNECTED,
        )
        self.job_a = PublishingJob.objects.create(workspace=self.ws_a, asset=self.asset_a)
        self.item_a = PublishingJobItem.objects.create(
            publishing_job=self.job_a, social_connection=self.conn_a,
            status=PublishingJobItem.Status.FAILED,
        )

    def as_(self, user, workspace=None):
        self.client.force_authenticate(user=user)
        if workspace:
            self.client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))

    # ── closed by default ────────────────────────────────────────────────
    def test_anonymous_is_rejected_everywhere(self):
        for url in (
            '/api/marketing/workspaces/',
            '/api/marketing/assets/',
            '/api/marketing/social-accounts/',
            '/api/marketing/publishing/jobs/',
            '/api/marketing/gemini/',
            '/api/marketing/settings/',
            '/api/marketing/analytics/dashboard/',
            '/api/marketing/analytics/kpis/',
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    self.client.get(url).status_code,
                    status.HTTP_401_UNAUTHORIZED,
                    f"{url} is reachable without authentication",
                )

    # ── list endpoints must not leak other tenants ───────────────────────
    def test_asset_list_is_scoped(self):
        MarketingAsset.objects.create(
            workspace=self.ws_b, file_name='beta.jpg', source='MANUAL_UPLOAD'
        )
        self.as_(self.alice, self.ws_a)
        res = self.client.get('/api/marketing/assets/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        names = [a['file_name'] for a in res.data]
        self.assertEqual(names, ['alpha.jpg'])

    def test_workspace_list_shows_only_own_workspaces(self):
        self.as_(self.mallory, self.ws_b)
        res = self.client.get('/api/marketing/workspaces/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual([w['workspace_name'] for w in res.data], ['Beta'])

    def test_social_connection_list_is_scoped(self):
        self.as_(self.mallory, self.ws_b)
        res = self.client.get('/api/marketing/social-accounts/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 0)

    def test_publishing_job_list_is_scoped(self):
        self.as_(self.mallory, self.ws_b)
        res = self.client.get('/api/marketing/publishing/jobs/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 0)

    # ── direct object access ─────────────────────────────────────────────
    def test_cannot_read_another_workspaces_asset_by_id(self):
        self.as_(self.mallory, self.ws_b)
        res = self.client.get(f'/api/marketing/assets/{self.asset_a.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_delete_another_workspaces_connection(self):
        self.as_(self.mallory, self.ws_b)
        res = self.client.delete(f'/api/marketing/social-accounts/{self.conn_a.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(SocialConnection.objects.filter(id=self.conn_a.id).exists())

    def test_retry_item_idor_is_closed(self):
        """
        Regression: retry_item looked the item up by id with no workspace
        filter, so any authenticated caller holding an item id could trigger a
        publish to a social account in someone else's workspace.
        """
        self.as_(self.mallory, self.ws_b)
        res = self.client.post(
            f'/api/marketing/publishing/jobs/items/{self.item_a.id}/retry/', {}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.item_a.refresh_from_db()
        # Still FAILED — nothing was queued or published on Alice's account.
        self.assertEqual(self.item_a.status, PublishingJobItem.Status.FAILED)

    def test_owner_can_reach_their_own_item(self):
        """The IDOR fix must not lock legitimate owners out."""
        self.as_(self.alice, self.ws_a)
        res = self.client.post(
            f'/api/marketing/publishing/jobs/items/{self.item_a.id}/retry/', {}, format='json'
        )
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # ── workspace-resolving APIViews ─────────────────────────────────────
    def test_settings_serves_the_callers_workspace_not_the_first_row(self):
        """
        Regression: this used MarketingWorkspace.objects.first(), so every
        caller got Alpha regardless of membership.
        """
        self.as_(self.mallory, self.ws_b)
        res = self.client.get('/api/marketing/settings/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['workspace']['workspace_name'], 'Beta')

    def test_settings_put_cannot_overwrite_another_workspace(self):
        self.as_(self.mallory, self.ws_a)  # claims Alpha, is only in Beta
        res = self.client.put(
            '/api/marketing/settings/', {'workspace': {'workspace_name': 'pwned'}}, format='json'
        )
        self.assertIn(res.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.ws_a.refresh_from_db()
        self.assertEqual(self.ws_a.workspace_name, 'Alpha')

    def test_analytics_is_scoped_to_the_caller(self):
        # 403, not 404: IsWorkspaceMember denies before the view body runs.
        # Workspace ids are UUIDs, so the existence disclosure a 404 would
        # avoid is not a practical enumeration risk.
        self.as_(self.mallory, self.ws_a)
        res = self.client.get('/api/marketing/analytics/dashboard/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_analytics_works_for_a_member(self):
        self.as_(self.alice, self.ws_a)
        res = self.client.get('/api/marketing/analytics/dashboard/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('trend', res.data)

    # ── role gating ──────────────────────────────────────────────────────
    def test_viewer_cannot_change_workspace_settings(self):
        viewer = User.objects.create_user(username='viewer', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws_a, user=viewer, role=WorkspaceMember.Role.VIEWER
        )
        self.as_(viewer, self.ws_a)
        res = self.client.put(
            '/api/marketing/settings/', {'workspace': {'workspace_name': 'nope'}}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.ws_a.refresh_from_db()
        self.assertEqual(self.ws_a.workspace_name, 'Alpha')

    def test_suspended_member_loses_access(self):
        WorkspaceMember.objects.filter(user=self.alice).update(
            status=WorkspaceMember.Status.SUSPENDED
        )
        self.as_(self.alice, self.ws_a)
        res = self.client.get('/api/marketing/settings/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # ── the OAuth callback must stay reachable ───────────────────────────
    def test_oauth_callback_remains_public(self):
        """
        It runs immediately after an external redirect holding a single-use
        code. A 401 there would silently break account connection.
        """
        res = self.client.post(
            '/api/marketing/social-accounts/oauth_callback/',
            {'platform': 'X', 'code': 'dummy', 'state': 'dummy'},
            format='json',
        )
        self.assertNotEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_connect_requires_authentication(self):
        res = self.client.post(
            '/api/marketing/social-accounts/connect/',
            {'workspace_id': str(self.ws_a.id), 'platform': 'X'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_connect_rejects_a_workspace_the_caller_is_not_in(self):
        self.as_(self.mallory)
        res = self.client.post(
            '/api/marketing/social-accounts/connect/',
            {'workspace_id': str(self.ws_a.id), 'platform': 'X'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
