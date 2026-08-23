"""
P6 — authoring standards and the inspiration library from the console.

The boundary first (a workspace OWNER, `is_staff`, and anonymous all get
nothing), then the lifecycle: a draft is created and edited, published (and
its predecessor retired), previewed honestly, retired with a reason; and a
published standard refuses in-place edits. The library side: curate, publish,
list with a live adoption count, retire.
"""
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import PlatformAuditLog
from apps.audit.services import grant_platform_admin
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.inspirations.models import BrandInspiration
from apps.universal.models import (
    LifecycleStatus,
    PlatformInspiration,
    UniversalScope,
    UniversalStandard,
)
from apps.universal.services import adopt_inspiration, publish_inspiration, publish_standard
from apps.workspaces.models import WorkspaceMember

User = get_user_model()

STANDARDS = '/api/platform/standards/'
INSPIRATIONS = '/api/platform/inspirations/'

STANDARD_BODY = {
    'title': 'Short headlines',
    'rationale': 'Long headlines lose the scroll.',
    'category': 'COPY_STYLE',
    'attribute': 'length',
    'value': 'short',
    'guidance': 'Keep headlines under nine words.',
    'scope': 'GLOBAL',
}

INSPIRATION_BODY = {
    'title': 'Great minimal poster',
    'reference_url': 'https://example.test/poster',
    'annotation': 'Negative space doing the work.',
    'tags': ['minimal', 'poster'],
    'industry': 'Coffee',
    'channel': 'instagram',
}


class UniversalConsoleTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.owner, self.owner_api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner@acme.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', industry='Coffee',
            website='https://acme.test', is_default=True, status=Brand.Status.ACTIVE,
        )
        self.staff = User.objects.create_user(username='staff@scaleezy.test', password='pw')
        grant_platform_admin(self.staff, note='test')
        self.staff_api = APIClient()
        self.staff_api.force_authenticate(user=self.staff)

    def actions(self):
        return set(PlatformAuditLog.objects.values_list('action', flat=True))

    # ───────────────────────────────────────────── the boundary

    def test_workspace_owner_staff_flag_and_anonymous_are_all_refused(self):
        for url in (STANDARDS, INSPIRATIONS):
            self.assertEqual(self.owner_api.get(url).status_code, status.HTTP_403_FORBIDDEN, url)
            self.assertEqual(
                self.owner_api.post(url, STANDARD_BODY, format='json').status_code,
                status.HTTP_403_FORBIDDEN, url,
            )
            self.assertEqual(APIClient().get(url).status_code, status.HTTP_401_UNAUTHORIZED, url)

        self.owner.is_staff = True
        self.owner.is_superuser = True
        self.owner.save(update_fields=['is_staff', 'is_superuser'])
        self.assertEqual(self.owner_api.get(STANDARDS).status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(UniversalStandard.objects.count(), 0)
        self.assertEqual(PlatformInspiration.objects.count(), 0)

    # ───────────────────────────────────────────── standards

    def test_create_draft_then_edit_it(self):
        response = self.staff_api.post(STANDARDS, STANDARD_BODY, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()['data']
        self.assertEqual(data['status'], LifecycleStatus.DRAFT)
        self.assertEqual(data['authored_by'], 'staff@scaleezy.test')
        self.assertIsNone(data['supersedes'])
        self.assertIn('UNIVERSAL_STANDARD_CREATED', self.actions())

        response = self.staff_api.patch(
            f"{STANDARDS}{data['id']}/", {'guidance': 'Under eight words.'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['guidance'], 'Under eight words.')
        edit = PlatformAuditLog.objects.get(action='UNIVERSAL_STANDARD_EDITED')
        self.assertEqual(edit.detail['changes']['guidance']['to'], 'Under eight words.')

        listing = self.staff_api.get(STANDARDS, {'status': 'DRAFT'})
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([s['id'] for s in listing.json()['data']['standards']], [data['id']])
        self.assertIn('UNIVERSAL_STANDARDS_VIEWED', self.actions())

    def test_create_refuses_missing_fields_and_bad_scope(self):
        missing = dict(STANDARD_BODY)
        missing.pop('guidance')
        response = self.staff_api.post(STANDARDS, missing, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('guidance', response.json()['message'])

        response = self.staff_api.post(
            STANDARDS, {**STANDARD_BODY, 'scope': 'GALAXY'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # A narrowed standard with no value applies to nobody: refused too.
        response = self.staff_api.post(
            STANDARDS, {**STANDARD_BODY, 'scope': 'INDUSTRY'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(UniversalStandard.objects.count(), 0)

    def test_publish_retires_the_superseded_standard_and_retire_takes_a_reason(self):
        old = publish_standard(UniversalStandard.objects.create(
            title='Old rule', category='COPY_STYLE', attribute='length',
            value='medium', guidance='Medium headlines.',
        ))
        response = self.staff_api.post(
            STANDARDS, {**STANDARD_BODY, 'supersedes': str(old.pk)}, format='json',
        )
        new_id = response.json()['data']['id']
        self.assertEqual(response.json()['data']['supersedes'], str(old.pk))

        response = self.staff_api.post(f'{STANDARDS}{new_id}/publish/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['status'], LifecycleStatus.PUBLISHED)
        old.refresh_from_db()
        self.assertEqual(old.status, LifecycleStatus.RETIRED)
        self.assertIn('UNIVERSAL_STANDARD_PUBLISHED', self.actions())

        response = self.staff_api.post(
            f'{STANDARDS}{new_id}/retire/', {'reason': 'too blunt'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['status'], LifecycleStatus.RETIRED)
        entry = PlatformAuditLog.objects.filter(
            action='UNIVERSAL_STANDARD_RETIRED', target=f'standard:{new_id}'
        ).get()
        self.assertEqual(entry.detail['reason'], 'too blunt')

    def test_a_published_standard_cannot_be_edited_in_place(self):
        live = publish_standard(UniversalStandard.objects.create(**{
            k: v for k, v in STANDARD_BODY.items()
        }))
        response = self.staff_api.patch(
            f'{STANDARDS}{live.pk}/', {'guidance': 'changed'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('supersede', response.json()['message'])
        live.refresh_from_db()
        self.assertEqual(live.guidance, STANDARD_BODY['guidance'])

    def test_preview_names_the_brands_a_standard_would_touch_and_audits(self):
        draft = UniversalStandard.objects.create(
            **{**STANDARD_BODY, 'scope': UniversalScope.INDUSTRY, 'scope_value': 'Coffee'}
        )
        response = self.staff_api.get(f'{STANDARDS}{draft.pk}/preview/')
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual(data['matched_brand_count'], 1)
        self.assertEqual(data['brands'][0]['id'], str(self.brand.pk))
        self.assertTrue(data['exact_match_only'])
        self.assertEqual(data['standard']['id'], str(draft.pk))
        self.assertIn('UNIVERSAL_STANDARD_PREVIEWED', self.actions())

    def test_unknown_standard_is_404(self):
        self.assertEqual(
            self.staff_api.get(f'{STANDARDS}{uuid.uuid4()}/preview/').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.staff_api.post(f'{STANDARDS}{uuid.uuid4()}/publish/', {}, format='json').status_code,
            status.HTTP_404_NOT_FOUND,
        )

    # ───────────────────────────────────────────── inspirations

    def test_create_publish_and_list_inspiration_with_live_adoption_count(self):
        response = self.staff_api.post(INSPIRATIONS, INSPIRATION_BODY, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()['data']
        self.assertEqual(data['status'], LifecycleStatus.DRAFT)
        self.assertEqual(data['curated_by'], 'staff@scaleezy.test')
        self.assertEqual(data['adoption_count'], 0)
        self.assertIn('PLATFORM_INSPIRATION_CREATED', self.actions())

        response = self.staff_api.post(f"{INSPIRATIONS}{data['id']}/publish/", {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['status'], LifecycleStatus.PUBLISHED)
        self.assertIn('PLATFORM_INSPIRATION_PUBLISHED', self.actions())

        # A client adopts it; the console count is the real row count.
        adopt_inspiration(PlatformInspiration.objects.get(pk=data['id']), self.brand, user=self.owner)
        self.assertEqual(BrandInspiration.objects.filter(brand=self.brand).count(), 1)

        listing = self.staff_api.get(INSPIRATIONS, {'status': 'PUBLISHED'})
        self.assertEqual(listing.status_code, 200)
        rows = listing.json()['data']['inspirations']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['adoption_count'], 1)
        self.assertEqual(rows[0]['tags'], ['minimal', 'poster'])
        self.assertIn('PLATFORM_INSPIRATIONS_VIEWED', self.actions())

    def test_inspiration_url_must_be_http_and_edit_and_retire_are_audited(self):
        response = self.staff_api.post(
            INSPIRATIONS, {**INSPIRATION_BODY, 'reference_url': 'ftp://x.test/a'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PlatformInspiration.objects.count(), 0)

        reference = publish_inspiration(PlatformInspiration.objects.create(**INSPIRATION_BODY))
        response = self.staff_api.patch(
            f'{INSPIRATIONS}{reference.pk}/', {'annotation': 'Updated note.'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['annotation'], 'Updated note.')
        self.assertIn('PLATFORM_INSPIRATION_EDITED', self.actions())

        response = self.staff_api.post(
            f'{INSPIRATIONS}{reference.pk}/retire/', {'reason': 'site gone'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        reference.refresh_from_db()
        self.assertEqual(reference.status, LifecycleStatus.RETIRED)
        entry = PlatformAuditLog.objects.get(action='PLATFORM_INSPIRATION_RETIRED')
        self.assertEqual(entry.detail['reason'], 'site gone')

        # Retired means out of the client gallery — and no further edits.
        from apps.universal.services import gallery_for

        self.assertEqual(gallery_for(self.workspace), [])
        response = self.staff_api.patch(
            f'{INSPIRATIONS}{reference.pk}/', {'annotation': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
