"""
Phase 1 — workspace membership, RBAC and queryset scoping.

The critical assertions here are the negative ones: a member of workspace A
must not be able to read, or even enumerate, workspace B.
"""
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_membership,
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
