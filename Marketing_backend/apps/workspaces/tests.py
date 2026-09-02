"""
Phase 1 — workspace membership, RBAC and queryset scoping.

The critical assertions here are the negative ones: a member of workspace A
must not be able to read, or even enumerate, workspace B.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_membership,
    get_request_workspace,
    resolve_workspace_id,
)
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember
from apps.ai.models import AIProvider, Capability, WorkspaceAIProvider, WorkspaceAIRoute
from apps.brands.models import Brand

User = get_user_model()


class RoleRankingTests(TestCase):
    def test_role_hierarchy_is_ordered(self):
        ws = MarketingWorkspace.objects.create(customer_id='c', workspace_name='W')
        user = User.objects.create_user(username='u', password='p')
        member = WorkspaceMember.objects.create(
            workspace=ws, user=user, role=WorkspaceMember.Role.MANAGER
        )

        # A manager outranks editors and viewers...
        self.assertTrue(member.has_at_least(WorkspaceMember.Role.VIEWER))
        self.assertTrue(member.has_at_least(WorkspaceMember.Role.EDITOR))
        self.assertTrue(member.has_at_least(WorkspaceMember.Role.MANAGER))
        # ...but not admins or owners.
        self.assertFalse(member.has_at_least(WorkspaceMember.Role.ADMIN))
        self.assertFalse(member.has_at_least(WorkspaceMember.Role.OWNER))

    def test_a_user_cannot_join_the_same_workspace_twice(self):
        from django.db.utils import IntegrityError

        ws = MarketingWorkspace.objects.create(customer_id='c', workspace_name='W')
        user = User.objects.create_user(username='u', password='p')
        WorkspaceMember.objects.create(workspace=ws, user=user)
        with self.assertRaises(IntegrityError):
            WorkspaceMember.objects.create(workspace=ws, user=user)


class MembershipLookupTests(TestCase):
    def setUp(self):
        self.ws_a = MarketingWorkspace.objects.create(customer_id='a', workspace_name='A')
        self.ws_b = MarketingWorkspace.objects.create(customer_id='b', workspace_name='B')
        self.alice = User.objects.create_user(username='alice', password='p')
        WorkspaceMember.objects.create(
            workspace=self.ws_a, user=self.alice, role=WorkspaceMember.Role.ADMIN
        )

    def test_membership_found_for_own_workspace(self):
        self.assertIsNotNone(get_membership(self.alice, self.ws_a.id))

    def test_no_membership_for_someone_elses_workspace(self):
        self.assertIsNone(get_membership(self.alice, self.ws_b.id))

    def test_suspended_membership_does_not_count(self):
        WorkspaceMember.objects.filter(user=self.alice).update(
            status=WorkspaceMember.Status.SUSPENDED
        )
        self.assertIsNone(get_membership(self.alice, self.ws_a.id))

    def test_anonymous_user_has_no_membership(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertIsNone(get_membership(AnonymousUser(), self.ws_a.id))


class WorkspaceResolutionTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.ws_a = MarketingWorkspace.objects.create(customer_id='a', workspace_name='A')
        self.ws_b = MarketingWorkspace.objects.create(customer_id='b', workspace_name='B')
        self.alice = User.objects.create_user(username='alice', password='p')
        WorkspaceMember.objects.create(workspace=self.ws_a, user=self.alice)

    def _request(self, **kwargs):
        request = self.factory.get('/api/x/', **kwargs)
        request.user = self.alice
        return request

    def test_header_takes_precedence(self):
        request = self._request(HTTP_X_WORKSPACE_ID=str(self.ws_b.id))
        self.assertEqual(resolve_workspace_id(request), str(self.ws_b.id))

    def test_falls_back_to_sole_membership(self):
        """Keeps the existing single-workspace frontend working without a header."""
        self.assertEqual(str(resolve_workspace_id(self._request())), str(self.ws_a.id))

    def test_no_fallback_when_user_belongs_to_several_workspaces(self):
        WorkspaceMember.objects.create(workspace=self.ws_b, user=self.alice)
        self.assertIsNone(resolve_workspace_id(self._request()))


class PermissionTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.ws_a = MarketingWorkspace.objects.create(customer_id='a', workspace_name='A')
        self.ws_b = MarketingWorkspace.objects.create(customer_id='b', workspace_name='B')

        self.alice = User.objects.create_user(username='alice', password='p')
        WorkspaceMember.objects.create(
            workspace=self.ws_a, user=self.alice, role=WorkspaceMember.Role.EDITOR
        )
        self.mallory = User.objects.create_user(username='mallory', password='p')
        WorkspaceMember.objects.create(
            workspace=self.ws_b, user=self.mallory, role=WorkspaceMember.Role.OWNER
        )

    def _request(self, user, workspace_id, method='get'):
        request = getattr(self.factory, method)(
            '/api/x/', HTTP_X_WORKSPACE_ID=str(workspace_id)
        )
        request.user = user
        return request

    def test_member_is_allowed(self):
        request = self._request(self.alice, self.ws_a.id)
        self.assertTrue(IsWorkspaceMember().has_permission(request, None))

    def test_outsider_is_denied(self):
        """The core tenancy assertion: B's owner cannot reach A."""
        request = self._request(self.mallory, self.ws_a.id)
        self.assertFalse(IsWorkspaceMember().has_permission(request, None))

    def test_anonymous_is_denied(self):
        from django.contrib.auth.models import AnonymousUser

        request = self._request(AnonymousUser(), self.ws_a.id)
        self.assertFalse(IsWorkspaceMember().has_permission(request, None))

    def test_role_gate_blocks_insufficient_role_on_write(self):
        class View:
            required_role = WorkspaceMember.Role.ADMIN

        request = self._request(self.alice, self.ws_a.id, method='post')
        IsWorkspaceMember().has_permission(request, View())
        # Alice is an EDITOR; the view demands ADMIN.
        self.assertFalse(HasWorkspaceRole().has_permission(request, View()))

    def test_role_gate_allows_sufficient_role_on_write(self):
        class View:
            required_role = WorkspaceMember.Role.EDITOR

        request = self._request(self.alice, self.ws_a.id, method='post')
        IsWorkspaceMember().has_permission(request, View())
        self.assertTrue(HasWorkspaceRole().has_permission(request, View()))

    def test_reads_use_the_lower_read_role(self):
        """A viewer can read even when writes demand ADMIN."""
        viewer = User.objects.create_user(username='v', password='p')
        WorkspaceMember.objects.create(
            workspace=self.ws_a, user=viewer, role=WorkspaceMember.Role.VIEWER
        )

        class View:
            required_role = WorkspaceMember.Role.ADMIN

        request = self._request(viewer, self.ws_a.id, method='get')
        IsWorkspaceMember().has_permission(request, View())
        self.assertTrue(HasWorkspaceRole().has_permission(request, View()))

    def test_object_permission_blocks_cross_workspace_object(self):
        request = self._request(self.mallory, self.ws_b.id)
        # Mallory is a legitimate member of B, but this object belongs to A.
        self.assertFalse(
            IsWorkspaceMember().has_object_permission(request, None, self.ws_a)
        )

    def test_workspace_helper_reuses_permission_membership_without_a_query(self):
        request = self._request(self.alice, self.ws_a.id)
        self.assertTrue(IsWorkspaceMember().has_permission(request, None))

        with self.assertNumQueries(0), patch(
            'apps.common.permissions.get_membership'
        ) as membership_lookup:
            workspace, error = get_request_workspace(request)

        self.assertIsNone(error)
        self.assertEqual(workspace, self.ws_a)
        membership_lookup.assert_not_called()

    def test_workspace_helper_ignores_mismatched_cache_and_fails_closed(self):
        request = self._request(self.alice, self.ws_b.id)
        request.workspace_membership = get_membership(self.alice, self.ws_a.id)

        with patch(
            'apps.common.permissions.get_membership', wraps=get_membership
        ) as membership_lookup:
            workspace, error = get_request_workspace(request)

        self.assertIsNone(workspace)
        self.assertEqual(error.status_code, 404)
        membership_lookup.assert_called_once_with(self.alice, str(self.ws_b.id))


class QuerysetScopingTests(TestCase):
    """A correct permission class still leaks if the queryset is unfiltered."""

    def setUp(self):
        self.ws_a = MarketingWorkspace.objects.create(customer_id='a', workspace_name='A')
        self.ws_b = MarketingWorkspace.objects.create(customer_id='b', workspace_name='B')
        self.alice = User.objects.create_user(username='alice', password='p')
        WorkspaceMember.objects.create(workspace=self.ws_a, user=self.alice)

        from apps.marketing.models import MarketingAsset

        self.asset_a = MarketingAsset.objects.create(
            workspace=self.ws_a, file_name='a.jpg', source='MANUAL_UPLOAD'
        )
        self.asset_b = MarketingAsset.objects.create(
            workspace=self.ws_b, file_name='b.jpg', source='MANUAL_UPLOAD'
        )

    def _view_for(self, user, workspace=None):
        from apps.marketing.models import MarketingAsset

        class Base:
            def get_queryset(self):
                return MarketingAsset.objects.all()

        class View(WorkspaceScopedMixin, Base):
            pass

        view = View()
        headers = {'HTTP_X_WORKSPACE_ID': str(workspace.id)} if workspace else {}
        request = RequestFactory().get('/api/assets/', **headers)
        request.user = user
        view.request = request
        return view

    def test_scoping_hides_other_workspaces(self):
        results = list(self._view_for(self.alice).get_queryset())
        self.assertEqual(results, [self.asset_a])

    def test_multi_client_user_sees_only_the_selected_workspace(self):
        WorkspaceMember.objects.create(workspace=self.ws_b, user=self.alice)

        results = list(self._view_for(self.alice, self.ws_a).get_queryset())

        self.assertEqual(results, [self.asset_a])

    def test_multi_client_request_without_selection_fails_closed(self):
        WorkspaceMember.objects.create(workspace=self.ws_b, user=self.alice)

        results = list(self._view_for(self.alice).get_queryset())

        self.assertEqual(results, [])

    def test_scoping_reuses_matching_permission_membership_without_a_query(self):
        view = self._view_for(self.alice, self.ws_a)
        view.request.workspace_membership = get_membership(self.alice, self.ws_a.id)

        with self.assertNumQueries(0), patch(
            'apps.common.mixins.get_membership'
        ) as membership_lookup:
            workspace_ids = view.accessible_workspace_ids()

        self.assertEqual(workspace_ids, [str(self.ws_a.id)])
        membership_lookup.assert_not_called()

    def test_scoping_ignores_mismatched_cache_without_crossing_tenants(self):
        view = self._view_for(self.alice, self.ws_b)
        view.request.workspace_membership = get_membership(self.alice, self.ws_a.id)

        with patch(
            'apps.common.mixins.get_membership', wraps=get_membership
        ) as membership_lookup:
            results = list(view.get_queryset())

        self.assertEqual(results, [])
        membership_lookup.assert_called_once_with(self.alice, str(self.ws_b.id))

    def test_user_with_no_membership_sees_nothing(self):
        nobody = User.objects.create_user(username='nobody', password='p')
        self.assertEqual(list(self._view_for(nobody).get_queryset()), [])

    def test_staff_does_not_bypass_tenant_isolation(self):
        """Staff users still need an explicit membership for tenant data."""
        staff = User.objects.create_user(username='staff', password='p', is_staff=True)
        self.assertEqual(len(list(self._view_for(staff).get_queryset())), 0)

        WorkspaceMember.objects.create(workspace=self.ws_a, user=staff)
        results = list(self._view_for(staff).get_queryset())
        self.assertEqual(results, [self.asset_a])


class ClientBootstrapTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.user = User.objects.create_user(username='owner', password='p')
        self.client.force_authenticate(self.user)
        self.provider = AIProvider.objects.update_or_create(
            key='gemini',
            defaults={
                'display_name': 'Google Gemini',
                'capabilities': [Capability.TEXT, Capability.IMAGE],
                'default_model': 'gemini-test',
                'is_available': True,
            },
        )[0]

    def test_add_client_atomically_bootstraps_owner_brand_and_ai(self):
        response = self.client.post(
            '/api/marketing/workspaces/',
            {'workspace_name': 'Client A', 'timezone': 'Asia/Kolkata'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        workspace = MarketingWorkspace.objects.get(workspace_name='Client A')
        self.assertTrue(WorkspaceMember.objects.filter(
            workspace=workspace, user=self.user, role=WorkspaceMember.Role.OWNER
        ).exists())
        self.assertTrue(Brand.objects.filter(
            workspace=workspace, name='Client A', is_default=True
        ).exists())
        workspace_provider = WorkspaceAIProvider.objects.get(
            workspace=workspace, enabled=True
        )
        self.assertTrue(
            workspace_provider.provider.supports(Capability.TEXT)
            and workspace_provider.provider.supports(Capability.IMAGE)
        )
        self.assertEqual(
            set(WorkspaceAIRoute.objects.filter(
                workspace=workspace,
                provider=workspace_provider.provider,
                enabled=True,
            ).values_list('capability', flat=True)),
            {Capability.TEXT, Capability.IMAGE},
        )

    def test_add_client_uses_the_requested_brand_name_inside_the_same_transaction(self):
        response = self.client.post(
            '/api/marketing/workspaces/',
            {'workspace_name': 'Agency Client', 'brand_name': 'Public Brand'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        workspace = MarketingWorkspace.objects.get(workspace_name='Agency Client')
        self.assertEqual(
            list(Brand.objects.filter(workspace=workspace).values_list('name', flat=True)),
            ['Public Brand'],
        )

    def test_add_client_rolls_back_when_platform_ai_is_unavailable(self):
        # Provisioning is capability-based and may choose any installed
        # provider. Make the whole catalogue unavailable rather than assuming
        # a particular vendor must be selected.
        AIProvider.objects.update(is_available=False)

        response = self.client.post(
            '/api/marketing/workspaces/', {'workspace_name': 'Broken'}, format='json'
        )

        self.assertEqual(response.status_code, 503)
        self.assertFalse(MarketingWorkspace.objects.filter(workspace_name='Broken').exists())
        self.assertFalse(WorkspaceMember.objects.filter(user=self.user).exists())


class WorkspaceSettingsAuditFeedTests(TestCase):
    """The accounts-page audit feed: connection events must appear in it, and
    it must never contain another tenant's rows."""

    def setUp(self):
        from rest_framework.test import APIClient

        from apps.audit.models import AuditLog
        from apps.social_accounts.models import SocialAccountAuditLog, SocialConnection

        self.ws_a = MarketingWorkspace.objects.create(customer_id='a', workspace_name='A')
        self.ws_b = MarketingWorkspace.objects.create(customer_id='b', workspace_name='B')
        self.alice = User.objects.create_user(username='alice', password='p')
        WorkspaceMember.objects.create(workspace=self.ws_a, user=self.alice)

        self.publishing_a = AuditLog.objects.create(
            workspace=self.ws_a, user='alice', platform='X',
            account='@scaleezy', action='Published Post', result='Success',
        )
        self.conn_a = SocialConnection.objects.create(
            workspace=self.ws_a, platform=SocialConnection.Platform.LINKEDIN,
            external_account_id='ext-a', account_name='Scaleezy Page',
        )
        self.connect_a = SocialAccountAuditLog.objects.create(
            workspace=self.ws_a, social_connection=self.conn_a, user=self.alice,
            action=SocialAccountAuditLog.Action.ACCOUNT_CONNECTION,
        )
        self.failed_a = SocialAccountAuditLog.objects.create(
            workspace=self.ws_a, social_connection=self.conn_a, user=self.alice,
            action=SocialAccountAuditLog.Action.TOKEN_REFRESH,
            error_message='token expired',
        )

        # Workspace B's rows, which must never surface in A's feed.
        self.publishing_b = AuditLog.objects.create(
            workspace=self.ws_b, user='mallory', platform='X',
            account='@other', action='Published Post', result='Success',
        )
        self.connect_b = SocialAccountAuditLog.objects.create(
            workspace=self.ws_b, social_connection=None, user=None,
            action=SocialAccountAuditLog.Action.ACCOUNT_CONNECTION,
        )

        self.client = APIClient()
        self.client.force_authenticate(self.alice)

    def _feed(self):
        response = self.client.get(
            '/api/marketing/settings/', HTTP_X_WORKSPACE_ID=str(self.ws_a.id)
        )
        self.assertEqual(response.status_code, 200)
        return response.data['audit_logs']

    def test_connection_events_are_interleaved_with_publishing_rows(self):
        rows = self._feed()

        by_id = {str(row['id']): row for row in rows}
        self.assertIn(str(self.publishing_a.id), by_id)
        self.assertIn(str(self.connect_a.id), by_id)

        connect = by_id[str(self.connect_a.id)]
        self.assertEqual(connect['action'], 'Account Connection')
        self.assertEqual(connect['platform'], 'LINKEDIN')
        self.assertEqual(connect['account'], 'Scaleezy Page')
        self.assertEqual(connect['user'], 'alice')
        self.assertEqual(connect['result'], 'Success')

        # Newest first across both sources.
        dates = [row['date'] for row in rows]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_a_failed_connection_event_reports_failed_with_its_error(self):
        rows = self._feed()
        failed = {str(row['id']): row for row in rows}[str(self.failed_a.id)]
        self.assertEqual(failed['result'], 'Failed')
        self.assertEqual(failed['error'], 'token expired')

    def test_workspace_a_cannot_read_workspace_b_events(self):
        ids = {str(row['id']) for row in self._feed()}
        self.assertNotIn(str(self.publishing_b.id), ids)
        self.assertNotIn(str(self.connect_b.id), ids)
