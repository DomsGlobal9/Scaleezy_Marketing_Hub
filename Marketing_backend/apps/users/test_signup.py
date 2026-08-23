"""
Public signup — the one write an anonymous caller may make.

What matters: one request leaves behind a complete, usable client (user,
workspace, OWNER membership, PENDING brand, AI routing) or nothing at all;
duplicates and weak passwords are refused; the endpoint is rate limited; and
every attempt, successful or not, is audited.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.ai.adapters.base import AIProviderAdapter
from apps.ai.models import AIProvider, Capability, WorkspaceAIRoute
from apps.brands.models import Brand
from apps.users.models import AuthAuditLog
from apps.users.views import SignupRateThrottle
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()


class SignupTestAdapter(AIProviderAdapter):
    """Vendor-neutral adapter so the bootstrap can provision a real route."""

    key = 'test-signup'
    display_name = 'Test Signup'
    capabilities = (Capability.TEXT, Capability.IMAGE)

    def health_check(self):
        return {'ok': True, 'detail': 'ready'}


VALID = {
    'email': 'founder@acme.test',
    'password': 'orbit-lantern-42-quartz',
    'brand_name': 'Acme Coffee',
    'website': 'https://acme.test',
    'industry': 'Coffee',
}


class SignupTestBase(APITestCase):
    """Fixture only: a platform with exactly one routable provider."""

    def setUp(self):
        # Throttle buckets live in the process-local cache and would otherwise
        # leak from one test into the next.
        cache.clear()
        self.provider, _ = AIProvider.objects.update_or_create(
            key=SignupTestAdapter.key,
            defaults={
                'display_name': SignupTestAdapter.display_name,
                'capabilities': [Capability.TEXT, Capability.IMAGE],
                'unit_cost': 0,
                'is_available': True,
            },
        )
        AIProvider.objects.exclude(pk=self.provider.pk).update(is_available=False)
        for target in (
            patch('apps.ai.provisioning.all_adapters',
                  return_value={self.provider.key: SignupTestAdapter}),
            patch('apps.ai.registry.get_adapter_class',
                  side_effect=lambda key: SignupTestAdapter if key == self.provider.key else None),
        ):
            target.start()
            self.addCleanup(target.stop)
        self.url = reverse('auth_signup')

    def signup(self, **overrides):
        return self.client.post(self.url, {**VALID, **overrides}, format='json')

    def assert_nothing_created(self):
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(MarketingWorkspace.objects.count(), 0)
        self.assertEqual(WorkspaceMember.objects.count(), 0)
        self.assertEqual(Brand.objects.count(), 0)


class SignupTests(SignupTestBase):
    # ------------------------------------------------------------ happy path

    def test_signup_creates_a_complete_pending_client_and_signs_in(self):
        response = self.signup()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()['data']

        user = User.objects.get(username='founder@acme.test')
        self.assertEqual(user.email, 'founder@acme.test')
        self.assertTrue(user.check_password(VALID['password']))

        workspace = MarketingWorkspace.objects.get(pk=data['workspace_id'])
        self.assertEqual(workspace.workspace_name, 'Acme Coffee')
        member = WorkspaceMember.objects.get(workspace=workspace, user=user)
        self.assertEqual(member.role, WorkspaceMember.Role.OWNER)
        self.assertEqual(member.status, WorkspaceMember.Status.ACTIVE)

        brand = Brand.objects.get(pk=data['brand_id'])
        self.assertEqual(brand.workspace, workspace)
        self.assertEqual(brand.status, Brand.Status.PENDING)
        self.assertEqual(data['brand_status'], 'PENDING')
        self.assertTrue(brand.is_default)
        self.assertEqual(brand.website, 'https://acme.test')
        self.assertEqual(brand.industry, 'Coffee')
        self.assertEqual(brand.created_by, user)
        self.assertIsNone(brand.reviewed_at)

        # The same bootstrap the add-client path performs: a routable workspace.
        self.assertEqual(
            WorkspaceAIRoute.objects.filter(workspace=workspace, enabled=True).count(), 2
        )

        # Signed in: the tokens work and carry the new membership.
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access']}")
        me = self.client.get(reverse('auth_me'))
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        memberships = me.json()['data']['memberships']
        self.assertEqual(len(memberships), 1)
        self.assertEqual(memberships[0]['workspace_id'], str(workspace.pk))
        self.assertEqual(memberships[0]['role'], 'OWNER')

        log = AuthAuditLog.objects.get(event=AuthAuditLog.Event.SIGNUP)
        self.assertTrue(log.succeeded)
        self.assertEqual(log.user, user)
        self.assertEqual(log.attempted_username, 'founder@acme.test')

    def test_email_is_normalised_and_a_duplicate_is_refused(self):
        self.assertEqual(self.signup(email='Founder@Acme.test').status_code, 201)
        self.assertTrue(User.objects.filter(username='founder@acme.test').exists())

        response = self.signup(email='founder@acme.test', brand_name='Other')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        body = response.json()
        self.assertFalse(body['success'])
        self.assertIn('email', body['error']['fields'])
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(MarketingWorkspace.objects.count(), 1)
        self.assertEqual(Brand.objects.count(), 1)

    # ------------------------------------------------------------ validation

    def test_weak_password_is_refused_and_nothing_is_created(self):
        response = self.signup(password='password')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.json()['error']['fields'])
        self.assert_nothing_created()

    def test_brand_name_is_required(self):
        response = self.signup(brand_name='   ')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('brand_name', response.json()['error']['fields'])
        self.assert_nothing_created()

    def test_malformed_website_is_refused(self):
        response = self.signup(website='not a url')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('website', response.json()['error']['fields'])
        self.assert_nothing_created()

    # ------------------------------------------------------------ atomicity

    def test_signup_rolls_back_when_platform_ai_is_unavailable(self):
        AIProvider.objects.update(is_available=False)
        response = self.signup()
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()['error']['code'], 'AI_BOOTSTRAP_UNAVAILABLE')
        self.assert_nothing_created()

        log = AuthAuditLog.objects.get(event=AuthAuditLog.Event.SIGNUP)
        self.assertFalse(log.succeeded)
        self.assertEqual(log.attempted_username, 'founder@acme.test')

    # ------------------------------------------------------------ abuse control

    def test_signup_is_rate_limited_per_client_ip(self):
        # Distinct websites: one company may only enrol once, and this test
        # is about the IP ceiling, not about that rule.
        with patch.object(SignupRateThrottle, 'rate', '2/hour', create=True):
            self.assertEqual(
                self.signup(email='a@a.test', brand_name='A', website='https://a.test')
                .status_code, 201)
            self.assertEqual(
                self.signup(email='b@b.test', brand_name='B', website='https://b.test')
                .status_code, 201)
            response = self.signup(
                email='c@c.test', brand_name='C', website='https://c.test')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertFalse(User.objects.filter(username='c@c.test').exists())
        self.assertEqual(Brand.objects.count(), 2)

    def test_signup_needs_no_authentication_but_the_rest_of_auth_still_does(self):
        # Sanity: the endpoint is open, /me/ is not.
        self.assertEqual(self.signup().status_code, 201)
        self.client.credentials()
        self.assertEqual(self.client.get(reverse('auth_me')).status_code, 401)


class DuplicateEnrolmentTests(SignupTestBase):
    """One company, one enrolment — the case the email check does not catch."""

    def test_a_second_signup_for_the_same_website_is_refused(self):
        self.assertEqual(self.signup().status_code, 201)

        response = self.signup(
            email='someone.else@acme.test', brand_name='Acme Coffee Ltd',
            website='https://WWW.Acme.test/about',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('website', response.json()['error']['fields'])
        self.assertEqual(Brand.objects.count(), 1)

    def test_a_different_website_enrols_normally(self):
        self.assertEqual(self.signup().status_code, 201)
        response = self.signup(
            email='founder@other.test', brand_name='Other Co',
            website='https://other.test',
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Brand.objects.count(), 2)

    def test_an_archived_client_frees_its_website_again(self):
        first = self.signup()
        brand = Brand.objects.get(pk=first.json()['data']['brand_id'])
        brand.status = Brand.Status.ARCHIVED
        brand.save(update_fields=['status'])

        response = self.signup(email='second@acme.test', brand_name='Acme Again')
        self.assertEqual(response.status_code, 201, response.content)

    def test_signup_without_a_website_is_still_allowed_more_than_once(self):
        self.assertEqual(self.signup(website='').status_code, 201)
        self.assertEqual(
            self.signup(email='b@acme.test', brand_name='B', website='').status_code, 201
        )

    def test_the_response_carries_the_unique_client_code(self):
        data = self.signup().json()['data']
        workspace = MarketingWorkspace.objects.get(pk=data['workspace_id'])
        self.assertEqual(data['client_code'], workspace.client_code)
        self.assertTrue(data['client_code'].startswith('SCZ-'))
