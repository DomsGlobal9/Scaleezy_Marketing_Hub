"""
Client Admin — team and roles.

These assert the authority rules themselves, not the happy path: that nobody
can promote past their own ceiling, that an OWNER is only touchable by an
OWNER, that the last OWNER survives every route that could strand a client,
and that suspension — a status that has existed since Phase 1 with no writer —
now actually removes access and restores it.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status

from apps.audit.models import PlatformAuditLog
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember
from apps.workspaces.services.team import (
    TeamError,
    attach_user_to_workspace,
    change_member_role,
    permission_matrix,
    remove_member,
    set_member_status,
)

User = get_user_model()
TEAM_URL = '/api/marketing/team/'


class TeamRuleTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.owner, self.owner_api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner'
        )
        self.admin, self.admin_api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'admin'
        )
        self.editor, self.editor_api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.EDITOR, 'editor'
        )
        self.m_owner = self.member(self.owner)
        self.m_admin = self.member(self.admin)
        self.m_editor = self.member(self.editor)

    def member(self, user, workspace=None):
        return WorkspaceMember.objects.get(
            workspace=workspace or self.workspace, user=user
        )

    # ------------------------------------------------------------ ceilings

    def test_nobody_may_grant_a_role_above_their_own(self):
        with self.assertRaises(TeamError):
            change_member_role(self.m_admin, self.m_editor, WorkspaceMember.Role.OWNER)
        self.m_editor.refresh_from_db()
        self.assertEqual(self.m_editor.role, WorkspaceMember.Role.EDITOR)

        # An owner may.
        change_member_role(self.m_owner, self.m_editor, WorkspaceMember.Role.OWNER)
        self.m_editor.refresh_from_db()
        self.assertEqual(self.m_editor.role, WorkspaceMember.Role.OWNER)

    def test_an_admin_may_promote_up_to_their_own_level(self):
        change_member_role(self.m_admin, self.m_editor, WorkspaceMember.Role.ADMIN)
        self.m_editor.refresh_from_db()
        self.assertEqual(self.m_editor.role, WorkspaceMember.Role.ADMIN)

    def test_only_an_owner_may_touch_an_owner(self):
        for call in (
            lambda: change_member_role(
                self.m_admin, self.m_owner, WorkspaceMember.Role.VIEWER),
            lambda: set_member_status(
                self.m_admin, self.m_owner, WorkspaceMember.Status.SUSPENDED),
            lambda: remove_member(self.m_admin, self.m_owner),
        ):
            with self.assertRaises(TeamError):
                call()
        self.m_owner.refresh_from_db()
        self.assertEqual(self.m_owner.role, WorkspaceMember.Role.OWNER)
        self.assertEqual(self.m_owner.status, WorkspaceMember.Status.ACTIVE)

    def test_an_editor_cannot_change_anybody(self):
        with self.assertRaises(TeamError):
            change_member_role(self.m_editor, self.m_admin, WorkspaceMember.Role.VIEWER)

    # ------------------------------------------------------- the last owner

    def test_the_last_owner_cannot_be_demoted_suspended_or_removed(self):
        for call in (
            lambda: change_member_role(
                self.m_owner, self.m_owner, WorkspaceMember.Role.ADMIN),
            lambda: set_member_status(
                self.m_owner, self.m_owner, WorkspaceMember.Status.SUSPENDED),
        ):
            with self.assertRaises(TeamError):
                call()

        second_owner, _ = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner2'
        )
        # With a second owner in place, the first may step down.
        change_member_role(self.m_owner, self.m_owner, WorkspaceMember.Role.ADMIN)
        self.m_owner.refresh_from_db()
        self.assertEqual(self.m_owner.role, WorkspaceMember.Role.ADMIN)

    def test_a_suspended_owner_does_not_count_as_an_owner(self):
        second, _ = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner2'
        )
        m_second = self.member(second)
        set_member_status(self.m_owner, m_second, WorkspaceMember.Status.SUSPENDED)
        # Only one ACTIVE owner remains, so it is again the last one.
        with self.assertRaises(TeamError):
            change_member_role(self.m_owner, self.m_owner, WorkspaceMember.Role.ADMIN)

    def test_nobody_removes_or_suspends_themselves(self):
        with self.assertRaises(TeamError):
            remove_member(self.m_admin, self.m_admin)
        with self.assertRaises(TeamError):
            set_member_status(
                self.m_admin, self.m_admin, WorkspaceMember.Status.SUSPENDED
            )

    # -------------------------------------------------------- cross-tenant

    def test_a_member_of_another_client_is_untouchable(self):
        other = self.make_workspace('Rival', 'c2')
        stranger, _ = self.authenticate_as(other, WorkspaceMember.Role.EDITOR, 'stranger')
        with self.assertRaises(TeamError):
            change_member_role(
                self.m_owner, self.member(stranger, other), WorkspaceMember.Role.VIEWER
            )

    # -------------------------------------------------------- the API

    def test_suspension_removes_access_and_reactivation_restores_it(self):
        brand = Brand.objects.create(
            workspace=self.workspace, name='Acme', status=Brand.Status.ACTIVE
        )
        url = f'/api/marketing/brands/{brand.id}/'
        headers = workspace_header(self.workspace)

        self.assertEqual(self.editor_api.get(url, **headers).status_code, 200)

        set_member_status(self.m_owner, self.m_editor, WorkspaceMember.Status.SUSPENDED)
        # `get_membership` filters on ACTIVE, so a suspended member is simply
        # not a member for the duration.
        self.assertIn(
            self.editor_api.get(url, **headers).status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

        set_member_status(self.m_owner, self.m_editor, WorkspaceMember.Status.ACTIVE)
        self.assertEqual(self.editor_api.get(url, **headers).status_code, 200)

    def test_the_roster_is_readable_by_the_team_and_states_there_is_no_invite(self):
        response = self.editor_api.get(TEAM_URL, **workspace_header(self.workspace))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual(len(data['members']), 3)
        self.assertFalse(data['can_invite'])
        self.assertTrue(data['invite_note'])

    def test_the_roster_never_shows_another_client(self):
        other = self.make_workspace('Rival', 'c2')
        self.authenticate_as(other, WorkspaceMember.Role.OWNER, 'rival-owner')
        response = self.owner_api.get(TEAM_URL, **workspace_header(self.workspace))
        usernames = {m['username'] for m in response.json()['data']['members']}
        self.assertNotIn('rival-owner', usernames)

    def test_role_change_through_the_api_respects_authority(self):
        headers = workspace_header(self.workspace)
        refused = self.admin_api.post(
            f'{TEAM_URL}{self.m_editor.id}/role/', {'role': 'OWNER'},
            format='json', **headers,
        )
        self.assertEqual(refused.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(refused.json()['error']['code'], 'TEAM_CHANGE_REFUSED')

        allowed = self.owner_api.post(
            f'{TEAM_URL}{self.m_editor.id}/role/', {'role': 'MANAGER'},
            format='json', **headers,
        )
        self.assertEqual(allowed.status_code, 200, allowed.content)
        self.m_editor.refresh_from_db()
        self.assertEqual(self.m_editor.role, WorkspaceMember.Role.MANAGER)

    def test_an_editor_cannot_reach_the_mutating_endpoints(self):
        response = self.editor_api.post(
            f'{TEAM_URL}{self.m_admin.id}/suspend/', {}, format='json',
            **workspace_header(self.workspace),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_removal_deletes_only_the_membership(self):
        response = self.owner_api.delete(
            f'{TEAM_URL}{self.m_editor.id}/', **workspace_header(self.workspace)
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(WorkspaceMember.objects.filter(pk=self.m_editor.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.editor.pk).exists())

    def test_the_permission_matrix_is_derived_from_role_rank(self):
        matrix = permission_matrix()
        self.assertEqual(
            [r['role'] for r in matrix['roles']],
            ['VIEWER', 'EDITOR', 'MANAGER', 'ADMIN', 'OWNER'],
        )
        by_key = {c['key']: c for c in matrix['capabilities']}
        self.assertEqual(by_key['transfer_ownership']['granted_to'], ['OWNER'])
        self.assertIn('EDITOR', by_key['edit_content']['granted_to'])
        self.assertNotIn('VIEWER', by_key['edit_content']['granted_to'])


class AttachUserTests(TenantFixtureMixin, TestCase):
    """The remedy for the colleague signup deliberately blocks."""

    def setUp(self):
        self.real = self.make_workspace('Acme', 'c1')
        self.owner, _ = self.authenticate_as(
            self.real, WorkspaceMember.Role.OWNER, 'owner'
        )
        Brand.objects.create(
            workspace=self.real, name='Acme', status=Brand.Status.ACTIVE
        )
        self.staff = User.objects.create_user(username='staff@scaleezy.test', password='pw')
        self.colleague = User.objects.create_user(username='colleague@acme.test', password='pw')

    def test_a_colleague_is_attached_and_the_action_is_audited(self):
        membership, candidates = attach_user_to_workspace(
            self.colleague, self.real, role=WorkspaceMember.Role.EDITOR, by=self.staff
        )
        self.assertEqual(membership.workspace, self.real)
        self.assertEqual(membership.role, WorkspaceMember.Role.EDITOR)
        self.assertEqual(membership.status, WorkspaceMember.Status.ACTIVE)
        self.assertEqual(candidates, [])

        entry = PlatformAuditLog.objects.get(action='USER_ATTACHED_TO_CLIENT')
        self.assertEqual(entry.workspace, self.real)
        self.assertEqual(entry.actor, self.staff)

    def test_a_stranded_signup_workspace_is_reported_never_archived(self):
        orphan = self.make_workspace('Acme (duplicate)', 'c-dup')
        orphan.approval_status = MarketingWorkspace.Approval.PENDING
        orphan.save(update_fields=['approval_status'])
        WorkspaceMember.objects.create(
            workspace=orphan, user=self.colleague, role=WorkspaceMember.Role.OWNER
        )
        Brand.objects.create(
            workspace=orphan, name='Acme dup', status=Brand.Status.PENDING
        )

        _, candidates = attach_user_to_workspace(
            self.colleague, self.real, by=self.staff
        )
        # Reported for the operator to judge — attach itself archives nothing,
        # because membership alone cannot prove this was the duplicate signup.
        self.assertEqual([c['workspace_id'] for c in candidates], [str(orphan.pk)])
        orphan.refresh_from_db()
        self.assertEqual(orphan.status, MarketingWorkspace.Status.ACTIVE)

    def test_a_real_approved_client_of_theirs_is_never_archived(self):
        theirs = self.make_workspace('Their Own Co', 'c-own')
        WorkspaceMember.objects.create(
            workspace=theirs, user=self.colleague, role=WorkspaceMember.Role.OWNER
        )
        Brand.objects.create(
            workspace=theirs, name='Their Co', status=Brand.Status.ACTIVE
        )

        _, candidates = attach_user_to_workspace(
            self.colleague, self.real, by=self.staff
        )
        self.assertEqual(candidates, [])
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, MarketingWorkspace.Status.ACTIVE)

    def test_attaching_twice_is_idempotent_and_reactivates(self):
        membership, _ = attach_user_to_workspace(self.colleague, self.real, by=self.staff)
        membership.status = WorkspaceMember.Status.SUSPENDED
        membership.save(update_fields=['status'])

        again, _ = attach_user_to_workspace(self.colleague, self.real, by=self.staff)
        self.assertEqual(again.pk, membership.pk)
        self.assertEqual(again.status, WorkspaceMember.Status.ACTIVE)

    def test_an_archived_client_cannot_be_attached_to(self):
        from apps.workspaces.services.lifecycle import archive_workspace

        archive_workspace(self.real, by=self.staff)
        with self.assertRaises(TeamError):
            attach_user_to_workspace(self.colleague, self.real, by=self.staff)


class PlatformAdminServiceTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username='a@scaleezy.test', password='pw')
        self.b = User.objects.create_user(username='b@scaleezy.test', password='pw')

    def test_the_last_platform_admin_cannot_be_revoked(self):
        from apps.audit.models import is_platform_admin
        from apps.audit.services import (
            PlatformAdminError,
            grant_platform_admin,
            revoke_platform_admin,
        )

        grant_platform_admin(self.a, note='bootstrap')
        with self.assertRaises(PlatformAdminError):
            revoke_platform_admin(self.a)
        self.assertTrue(is_platform_admin(self.a))

        # With a second admin in place, the first may be revoked.
        grant_platform_admin(self.b, by=self.a)
        revoke_platform_admin(self.a, by=self.b)
        self.assertFalse(is_platform_admin(self.a))
        self.assertTrue(is_platform_admin(self.b))

    def test_grants_record_who_did_it(self):
        from apps.audit.services import grant_platform_admin

        grant_platform_admin(self.a)
        grant_platform_admin(self.b, by=self.a, note='ops')
        entries = PlatformAuditLog.objects.filter(action='PLATFORM_ADMIN_GRANTED')
        self.assertEqual(entries.count(), 2)
        self.assertTrue(entries.filter(actor=self.a).exists())
        self.assertTrue(entries.filter(detail__bootstrap=True).exists())
