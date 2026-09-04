from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai.models import AIProvider
from apps.audit.models import PlatformAuditLog
from apps.audit.services import grant_platform_admin, revoke_platform_admin
from apps.brands.models import Brand
from apps.universal.models import LearnedPattern, PlatformInspiration, UniversalStandard
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember


class PlatformListClosureTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(username='list-platform-admin')
        grant_platform_admin(self.admin)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.workspace = MarketingWorkspace.objects.create(customer_id='closure', workspace_name='closure workspace')
        self.owner = get_user_model().objects.create_user(username='list-owner', is_staff=True)
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.owner, role='OWNER')

    def assert_pages(self, path, key, total=501):
        first = self.api.get(f'{path}?page=1&page_size=200&q=closure').json()['data']
        second = self.api.get(f'{path}?page=2&page_size=200&q=closure').json()['data']
        last = self.api.get(f'{path}?page=3&page_size=200&q=closure').json()['data']
        self.assertEqual(first['total'], total)
        self.assertEqual(first['next_page'], 2)
        self.assertEqual(last['previous_page'], 2)
        self.assertIsNone(last['next_page'])
        self.assertEqual(len(last[key]), 101)
        identifier = 'brand_id' if key == 'signups' else 'id'
        ids = [row[identifier] for page in (first, second, last) for row in page[key]]
        self.assertEqual(len(set(ids)), total)
        beyond = self.api.get(f'{path}?page=10000&page_size=25&q=closure').json()['data']
        self.assertEqual(beyond[key], [])
        self.assertEqual(beyond['total'], total)

    def test_signup_continuation_reaches_records_beyond_legacy_cap(self):
        Brand.objects.bulk_create([Brand(workspace=self.workspace, name=f'closure {i}', status='PENDING') for i in range(501)])
        self.assert_pages('/api/platform/signups/', 'signups')
        legacy = self.api.get('/api/platform/signups/').json()['data']
        self.assertEqual(set(legacy), {'status', 'count', 'pending_total', 'signups'})
        self.assertEqual(len(legacy['signups']), 200)

    def test_standards_continuation_reaches_all_records(self):
        UniversalStandard.objects.bulk_create([UniversalStandard(title=f'closure {i}', category='copy', attribute='length', value=str(i), guidance='Short') for i in range(501)])
        self.assert_pages('/api/platform/standards/', 'standards')
        self.assertNotIn('page', self.api.get('/api/platform/standards/').json()['data'])

    def test_library_continuation_reaches_all_records(self):
        PlatformInspiration.objects.bulk_create([PlatformInspiration(title=f'closure {i}', annotation='Reference') for i in range(501)])
        self.assert_pages('/api/platform/inspirations/', 'inspirations')

    def test_patterns_continuation_reaches_all_records(self):
        LearnedPattern.objects.bulk_create([LearnedPattern(category='closure', attribute='length', value=str(i), normalized_value=str(i), compiled_at=timezone.now(), pattern_version='v1') for i in range(501)])
        self.assert_pages('/api/platform/patterns/', 'patterns')

    def test_status_kind_search_counts_are_server_authoritative(self):
        PlatformInspiration.objects.bulk_create([
            PlatformInspiration(title='needle one', kind='TEXT', status='PUBLISHED'),
            PlatformInspiration(title='needle two', kind='TEXT', status='DRAFT'),
            PlatformInspiration(title='needle three', kind='LINK', status='PUBLISHED'),
            PlatformInspiration(title='unrelated', kind='TEXT', status='PUBLISHED'),
        ])
        data = self.api.get('/api/platform/inspirations/?page=1&page_size=1&q=needle&status=PUBLISHED&kind=TEXT').json()['data']
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['inspirations'][0]['title'], 'needle one')
        self.assertEqual(data['status_counts'], {'ALL': 2, 'DRAFT': 1, 'PUBLISHED': 1})
        self.assertEqual(data['kind_counts'], {'ALL': 2, 'TEXT': 1, 'LINK': 1})

    def test_invalid_page_values_are_bounded_and_legacy_lists_stay_unchanged(self):
        for path in ('signups', 'standards', 'patterns', 'inspirations', 'providers'):
            with self.subTest(path=path):
                data = self.api.get(f'/api/platform/{path}/?page=bad&page_size=1000000').json()['data']
                self.assertEqual(data['page'], 1)
                self.assertEqual(data['page_size'], 200)
                data = self.api.get(f'/api/platform/{path}/?page=-3&page_size=bad').json()['data']
                self.assertEqual(data['page'], 1)
                self.assertEqual(data['page_size'], 25)

    def test_platform_lists_reject_workspace_staff_and_revoked_platform_admin(self):
        paths = ('signups', 'standards', 'patterns', 'inspirations', 'providers')
        owner_api = APIClient()
        owner_api.force_authenticate(self.owner)
        for path in paths:
            self.assertEqual(owner_api.get(f'/api/platform/{path}/?page=1').status_code, 403)
            self.assertEqual(APIClient().get(f'/api/platform/{path}/?page=1').status_code, 401)
        keeper = get_user_model().objects.create_user(username='list-keeper')
        grant_platform_admin(keeper)
        revoke_platform_admin(self.admin, by=keeper)
        self.assertEqual(self.api.get('/api/platform/providers/?page=1').status_code, 403)

    def test_availability_catalogue_exposes_no_tenant_provider_or_credentials(self):
        public = AIProvider.objects.create(key='closure-public', display_name='Closure public')
        AIProvider.objects.create(key='closure-private', display_name='Closure private', owner_workspace=self.workspace, base_url='https://private.example/')
        response = self.api.get('/api/platform/providers/?page=1&q=closure')
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['providers'], [{'id': str(public.pk), 'key': public.key, 'display_name': public.display_name, 'is_available': public.is_available}])
        self.assertTrue(PlatformAuditLog.objects.filter(action='PLATFORM_PROVIDER_AVAILABILITY_VIEWED').exists())
        owner_api = APIClient()
        owner_api.force_authenticate(self.owner)
        url = f'/api/platform/providers/{public.pk}/availability/'
        self.assertEqual(owner_api.post(url, {'is_available': False}, format='json').status_code, 403)
        self.assertEqual(self.api.post(url, {'is_available': False}, format='json').status_code, 200)
        public.refresh_from_db()
        self.assertFalse(public.is_available)
        self.assertTrue(PlatformAuditLog.objects.filter(action='PROVIDER_AVAILABILITY_CHANGED').exists())

    def test_library_page_query_count_does_not_grow_per_row(self):
        PlatformInspiration.objects.bulk_create([PlatformInspiration(title=f'closure {i}') for i in range(30)])
        with CaptureQueriesContext(connection) as small:
            self.api.get('/api/platform/inspirations/?page_size=1')
        with CaptureQueriesContext(connection) as large:
            self.api.get('/api/platform/inspirations/?page_size=25')
        self.assertLessEqual(len(large), len(small) + 1)
