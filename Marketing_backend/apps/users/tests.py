"""
Phase 1 — authentication and audit trail.

These assert the security boundary itself, not just the happy path: wrong
passwords, unknown accounts, missing tokens, and that every attempt is audited.
"""
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import AuthAuditLog
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()


class AuthFlowTests(APITestCase):
    def setUp(self):
        self.password = 'correct-horse-battery-staple'
        self.user = User.objects.create_user(
            username='anjali', email='anjali@scaleezy.test', password=self.password
        )
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='cust-1', workspace_name='Scaleezy Fashion'
        )
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=self.user, role=WorkspaceMember.Role.ADMIN
        )

    def test_login_returns_tokens_and_audits_success(self):
        res = self.client.post(
            reverse('auth_login'),
            {'username': 'anjali', 'password': self.password},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertIn('access', res.data['data'])
        self.assertIn('refresh', res.data['data'])

        log = AuthAuditLog.objects.get(event=AuthAuditLog.Event.LOGIN_SUCCESS)
        self.assertEqual(log.user, self.user)
        self.assertTrue(log.succeeded)

    def test_login_with_wrong_password_is_rejected_and_audited(self):
        res = self.client.post(
            reverse('auth_login'),
            {'username': 'anjali', 'password': 'wrong'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(res.data['success'])

        log = AuthAuditLog.objects.get(event=AuthAuditLog.Event.LOGIN_FAILED)
        self.assertFalse(log.succeeded)
        self.assertEqual(log.attempted_username, 'anjali')

    def test_login_error_does_not_reveal_whether_account_exists(self):
        """Same response for a bad password and a non-existent user."""
        bad_password = self.client.post(
            reverse('auth_login'), {'username': 'anjali', 'password': 'wrong'}, format='json'
        )
        no_such_user = self.client.post(
            reverse('auth_login'), {'username': 'ghost', 'password': 'wrong'}, format='json'
        )
        self.assertEqual(bad_password.status_code, no_such_user.status_code)
        self.assertEqual(bad_password.data['message'], no_such_user.data['message'])

    def test_unknown_username_is_still_audited(self):
        self.client.post(
            reverse('auth_login'), {'username': 'ghost', 'password': 'x'}, format='json'
        )
        log = AuthAuditLog.objects.get(attempted_username='ghost')
        self.assertIsNone(log.user)
        self.assertFalse(log.succeeded)

    def test_me_requires_authentication(self):
        res = self.client.get(reverse('auth_me'))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_identity_and_memberships(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.get(reverse('auth_me'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        data = res.data['data']
        self.assertEqual(data['username'], 'anjali')
        self.assertEqual(len(data['memberships']), 1)
        self.assertEqual(data['memberships'][0]['role'], WorkspaceMember.Role.ADMIN)
        self.assertEqual(data['memberships'][0]['workspace_name'], 'Scaleezy Fashion')

    def test_suspended_membership_is_not_returned(self):
        WorkspaceMember.objects.filter(user=self.user).update(
            status=WorkspaceMember.Status.SUSPENDED
        )
        self.client.force_authenticate(user=self.user)
        res = self.client.get(reverse('auth_me'))
        self.assertEqual(res.data['data']['memberships'], [])

    def test_refresh_issues_a_new_access_token(self):
        login = self.client.post(
            reverse('auth_login'),
            {'username': 'anjali', 'password': self.password},
            format='json',
        )
        res = self.client.post(
            reverse('auth_refresh'), {'refresh': login.data['data']['refresh']}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('access', res.data['data'])
        self.assertTrue(
            AuthAuditLog.objects.filter(event=AuthAuditLog.Event.TOKEN_REFRESH).exists()
        )

    def test_refresh_with_garbage_token_is_rejected_and_audited(self):
        res = self.client.post(
            reverse('auth_refresh'), {'refresh': 'not-a-token'}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(
            AuthAuditLog.objects.filter(
                event=AuthAuditLog.Event.TOKEN_REFRESH_FAILED
            ).exists()
        )

    def test_access_token_authenticates_a_protected_endpoint(self):
        """End-to-end: the issued token actually works as a Bearer credential."""
        login = self.client.post(
            reverse('auth_login'),
            {'username': 'anjali', 'password': self.password},
            format='json',
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login.data['data']['access']}"
        )
        res = self.client.get(reverse('auth_me'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['data']['username'], 'anjali')

    def test_jwt_carries_workspace_claims(self):
        from apps.users.serializers import ScaleezyTokenObtainPairSerializer

        token = ScaleezyTokenObtainPairSerializer.get_token(self.user)
        self.assertEqual(len(token['memberships']), 1)
        self.assertEqual(token['memberships'][0]['role'], WorkspaceMember.Role.ADMIN)

    def test_logout_is_audited(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.post(reverse('auth_logout'), {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(
            AuthAuditLog.objects.filter(event=AuthAuditLog.Event.LOGOUT).exists()
        )

    def test_logout_actually_revokes_the_refresh_token(self):
        """
        Regression: logout used to call .blacklist() without the token_blacklist
        app installed, raise AttributeError, swallow it, and still report
        success — leaving a live self-renewing credential behind.
        """
        login = self.client.post(
            reverse('auth_login'),
            {'username': 'anjali', 'password': self.password},
            format='json',
        )
        refresh = login.data['data']['refresh']

        self.client.force_authenticate(user=self.user)
        res = self.client.post(reverse('auth_logout'), {'refresh': refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['data']['refresh_token_revoked'])

        # The revoked token must no longer buy a new access token.
        self.client.force_authenticate(user=None)
        reuse = self.client.post(reverse('auth_refresh'), {'refresh': refresh}, format='json')
        self.assertEqual(reuse.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_audit_records_revocation_outcome(self):
        self.client.force_authenticate(user=self.user)
        self.client.post(reverse('auth_logout'), {}, format='json')
        log = AuthAuditLog.objects.filter(event=AuthAuditLog.Event.LOGOUT).first()
        # No refresh token supplied, so nothing was revoked — and the audit
        # trail says so rather than claiming success.
        self.assertFalse(log.succeeded)
        self.assertIn('no refresh token', log.reason)

    def test_audit_log_captures_ip_and_user_agent(self):
        self.client.post(
            reverse('auth_login'),
            {'username': 'anjali', 'password': self.password},
            format='json',
            HTTP_USER_AGENT='pytest-agent/1.0',
            HTTP_X_FORWARDED_FOR='203.0.113.7, 10.0.0.1',
        )
        log = AuthAuditLog.objects.get(event=AuthAuditLog.Event.LOGIN_SUCCESS)
        self.assertEqual(log.user_agent, 'pytest-agent/1.0')
        # First hop of X-Forwarded-For, not the proxy.
        self.assertEqual(log.ip_address, '203.0.113.7')
