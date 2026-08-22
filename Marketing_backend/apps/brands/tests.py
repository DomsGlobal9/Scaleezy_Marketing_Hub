"""
Phase 2 — Brand.

Covers the model's own rules plus the tenancy and role constraints every
viewset in this project must satisfy, since the Phase 1c audit showed those
are exactly what gets missed on a new endpoint.
"""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from apps.brands.models import Brand
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()

# A 1x1 PNG, so ImageField validation passes.
PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
    b'\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05'
    b'\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)


class BrandModelTests(APITestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='c', workspace_name='Alpha')

    def test_defaults_are_sensible(self):
        brand = Brand.objects.create(workspace=self.ws, name='Islands of Loom')
        self.assertIn('primary', brand.palette)
        self.assertIn('primary', brand.fonts)
        self.assertEqual(brand.competitors, [])
        self.assertEqual(brand.creative_brain, {})
        self.assertEqual(brand.layout_preference, Brand.Layout.AGENCY_COLUMN)
        self.assertFalse(brand.has_logo)

    def test_name_is_unique_within_a_workspace_but_not_across(self):
        from django.db.utils import IntegrityError

        other = MarketingWorkspace.objects.create(customer_id='d', workspace_name='Beta')
        Brand.objects.create(workspace=self.ws, name='Duplicate')
        # Same name in a different workspace is fine.
        Brand.objects.create(workspace=other, name='Duplicate')
        with self.assertRaises(IntegrityError):
            Brand.objects.create(workspace=self.ws, name='Duplicate')

    def test_promoting_a_default_demotes_the_previous_one(self):
        first = Brand.objects.create(workspace=self.ws, name='First', is_default=True)
        second = Brand.objects.create(workspace=self.ws, name='Second', is_default=True)
        first.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)

    def test_default_flag_is_per_workspace(self):
        other = MarketingWorkspace.objects.create(customer_id='d', workspace_name='Beta')
        mine = Brand.objects.create(workspace=self.ws, name='Mine', is_default=True)
        theirs = Brand.objects.create(workspace=other, name='Theirs', is_default=True)
        mine.refresh_from_db()
        # Promoting Beta's default must not touch Alpha's.
        self.assertTrue(mine.is_default)
        self.assertTrue(theirs.is_default)


class BrandAPITests(APITestCase):
    def setUp(self):
        self.ws_a = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.ws_b = MarketingWorkspace.objects.create(customer_id='b', workspace_name='Beta')

        self.alice = User.objects.create_user(username='alice', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws_a, user=self.alice, role=WorkspaceMember.Role.ADMIN
        )
        self.mallory = User.objects.create_user(username='mallory', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws_b, user=self.mallory, role=WorkspaceMember.Role.OWNER
        )
        self.brand_a = Brand.objects.create(
            workspace=self.ws_a, name='Alpha Brand', is_default=True
        )

    def as_(self, user, workspace=None):
        self.client.force_authenticate(user=user)
        if workspace:
            self.client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))

    # ── access control ───────────────────────────────────────────────────
    def test_anonymous_is_rejected(self):
        self.assertEqual(
            self.client.get('/api/marketing/brands/').status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_list_is_scoped_to_the_callers_workspaces(self):
        Brand.objects.create(workspace=self.ws_b, name='Beta Brand')
        self.as_(self.alice, self.ws_a)
        res = self.client.get('/api/marketing/brands/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual([b['name'] for b in res.data], ['Alpha Brand'])

    def test_cannot_read_another_workspaces_brand(self):
        self.as_(self.mallory, self.ws_b)
        res = self.client.get(f'/api/marketing/brands/{self.brand_a.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_edit_another_workspaces_brand(self):
        self.as_(self.mallory, self.ws_b)
        res = self.client.patch(
            f'/api/marketing/brands/{self.brand_a.id}/', {'tagline': 'pwned'}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.brand_a.refresh_from_db()
        self.assertEqual(self.brand_a.tagline, '')

    def test_workspace_cannot_be_chosen_by_the_client(self):
        """Regression against the Phase 1c class of bug."""
        self.as_(self.mallory, self.ws_b)
        res = self.client.post(
            '/api/marketing/brands/',
            {'name': 'Planted', 'workspace': str(self.ws_a.id)},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        # Created in Mallory's own workspace, not the one they asked for.
        self.assertEqual(Brand.objects.get(name='Planted').workspace, self.ws_b)

    def test_viewer_cannot_create_or_edit(self):
        viewer = User.objects.create_user(username='v', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws_a, user=viewer, role=WorkspaceMember.Role.VIEWER
        )
        self.as_(viewer, self.ws_a)
        self.assertEqual(
            self.client.post('/api/marketing/brands/', {'name': 'Nope'}, format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.patch(
                f'/api/marketing/brands/{self.brand_a.id}/', {'tagline': 'x'}, format='json'
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_viewer_can_still_read(self):
        viewer = User.objects.create_user(username='v2', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws_a, user=viewer, role=WorkspaceMember.Role.VIEWER
        )
        self.as_(viewer, self.ws_a)
        self.assertEqual(
            self.client.get('/api/marketing/brands/').status_code, status.HTTP_200_OK
        )

    # ── /current ─────────────────────────────────────────────────────────
    def test_current_returns_the_default_brand(self):
        self.as_(self.alice, self.ws_a)
        res = self.client.get('/api/marketing/brands/current/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['data']['name'], 'Alpha Brand')

    def test_current_creates_a_brand_on_first_use(self):
        self.as_(self.mallory, self.ws_b)
        self.assertEqual(Brand.objects.filter(workspace=self.ws_b).count(), 0)
        res = self.client.get('/api/marketing/brands/current/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(Brand.objects.filter(workspace=self.ws_b).count(), 1)
        self.assertTrue(res.data['data']['is_default'])

    def test_current_is_idempotent(self):
        self.as_(self.mallory, self.ws_b)
        first = self.client.get('/api/marketing/brands/current/').data['data']['id']
        second = self.client.get('/api/marketing/brands/current/').data['data']['id']
        self.assertEqual(first, second)
        self.assertEqual(Brand.objects.filter(workspace=self.ws_b).count(), 1)

    # ── logo ─────────────────────────────────────────────────────────────
    def test_logo_upload_stores_url_and_enables_the_toggle(self):
        self.as_(self.alice, self.ws_a)
        res = self.client.post(
            f'/api/marketing/brands/{self.brand_a.id}/logo/',
            {'file': SimpleUploadedFile('logo.png', PNG, content_type='image/png')},
            format='multipart',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.brand_a.refresh_from_db()
        self.assertTrue(self.brand_a.logo_url)
        self.assertEqual(self.brand_a.logo_file_name, 'logo.png')
        self.assertTrue(self.brand_a.show_logo_on_posters)

    def test_logo_upload_rejects_a_non_image(self):
        self.as_(self.alice, self.ws_a)
        res = self.client.post(
            f'/api/marketing/brands/{self.brand_a.id}/logo/',
            {'file': SimpleUploadedFile('x.txt', b'not an image', content_type='text/plain')},
            format='multipart',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logo_upload_rejects_oversized_files(self):
        self.as_(self.alice, self.ws_a)
        big = SimpleUploadedFile('big.png', PNG + b'\x00' * (2 * 1024 * 1024), 'image/png')
        res = self.client.post(
            f'/api/marketing/brands/{self.brand_a.id}/logo/', {'file': big}, format='multipart'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_upload_a_logo_to_another_workspaces_brand(self):
        self.as_(self.mallory, self.ws_b)
        res = self.client.post(
            f'/api/marketing/brands/{self.brand_a.id}/logo/',
            {'file': SimpleUploadedFile('logo.png', PNG, content_type='image/png')},
            format='multipart',
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_logo_delete_clears_it_and_the_toggle(self):
        self.brand_a.logo_url = 'https://example.test/logo.png'
        self.brand_a.show_logo_on_posters = True
        self.brand_a.save()

        self.as_(self.alice, self.ws_a)
        res = self.client.delete(f'/api/marketing/brands/{self.brand_a.id}/logo/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.brand_a.refresh_from_db()
        self.assertEqual(self.brand_a.logo_url, '')
        self.assertFalse(self.brand_a.show_logo_on_posters)

    # ── field validation ─────────────────────────────────────────────────
    def test_palette_must_be_an_object(self):
        self.as_(self.alice, self.ws_a)
        res = self.client.patch(
            f'/api/marketing/brands/{self.brand_a.id}/', {'palette': ['#fff']}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_brand_kit_fields_round_trip(self):
        self.as_(self.alice, self.ws_a)
        res = self.client.patch(
            f'/api/marketing/brands/{self.brand_a.id}/',
            {
                'tagline': 'Values never go out of style',
                'cta_keyword': 'EXPERIENCE COMFORT',
                'contact_phone': '+91 98765 43210',
                'show_phone_on_posters': True,
                'palette': {'primary': '#221F3C', 'accent': '#D2FFAA'},
                'competitors': ['@andamen'],
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.brand_a.refresh_from_db()
        self.assertEqual(self.brand_a.cta_keyword, 'EXPERIENCE COMFORT')
        self.assertTrue(self.brand_a.show_phone_on_posters)
        self.assertEqual(self.brand_a.competitors, ['@andamen'])

    # ── business profile ─────────────────────────────────────────────────
    PROFILE = {
        'website': 'https://loom.example/',
        'location': 'Kochi, Kerala',
        'audience': 'Coastal homeowners furnishing a first house.',
        'description': 'Handwoven textiles made on the Malabar coast.',
        'products_services': [
            {'name': 'Throw blankets', 'description': 'Cotton, handloom.'},
            {'name': 'Cushion covers', 'description': ''},
        ],
        'social_links': {'instagram': 'https://instagram.com/loom'},
    }

    def test_business_profile_fields_round_trip_through_the_api(self):
        """`fields = '__all__'` is the only thing making these writable.

        If that ever narrows to an explicit list, the six fields go read-only
        without any error, and the settings form silently stops saving.
        """
        self.as_(self.alice, self.ws_a)
        res = self.client.post(
            '/api/marketing/brands/', {'name': 'Loom & Co', **self.PROFILE}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)

        brand = Brand.objects.get(name='Loom & Co')
        for field, expected in self.PROFILE.items():
            with self.subTest(field=field):
                self.assertEqual(getattr(brand, field), expected)

        read = self.client.get(f'/api/marketing/brands/{brand.id}/')
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        for field, expected in self.PROFILE.items():
            with self.subTest(field=field):
                self.assertEqual(read.data[field], expected)

    def test_a_product_without_a_description_reads_back_with_an_empty_one(self):
        self.as_(self.alice, self.ws_a)
        res = self.client.patch(
            f'/api/marketing/brands/{self.brand_a.id}/',
            {'products_services': [{'name': '  Cushion covers  '}]},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.brand_a.refresh_from_db()
        self.assertEqual(
            self.brand_a.products_services, [{'name': 'Cushion covers', 'description': ''}]
        )

    def test_products_services_stores_only_the_two_known_keys(self):
        """A JSONField keeps whatever it is handed for the life of the row."""
        self.as_(self.alice, self.ws_a)
        self.client.patch(
            f'/api/marketing/brands/{self.brand_a.id}/',
            {'products_services': [{'name': 'Rug', 'description': 'Jute', 'price': 4999}]},
            format='json',
        )
        self.brand_a.refresh_from_db()
        self.assertEqual(
            self.brand_a.products_services, [{'name': 'Rug', 'description': 'Jute'}]
        )

    def test_products_services_rejects_anything_that_is_not_a_named_item(self):
        self.as_(self.alice, self.ws_a)
        for bad in (
            {'name': 'an object, not a list'},
            ['a bare string'],
            [{'description': 'no name at all'}],
            [{'name': '   '}],
            [{'name': 'Rug', 'description': 4999}],
        ):
            with self.subTest(bad=bad):
                res = self.client.patch(
                    f'/api/marketing/brands/{self.brand_a.id}/',
                    {'products_services': bad},
                    format='json',
                )
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.data)
        self.brand_a.refresh_from_db()
        self.assertEqual(self.brand_a.products_services, [])

    def test_social_links_rejects_anything_that_is_not_platform_to_url(self):
        self.as_(self.alice, self.ws_a)
        for bad in (
            ['https://instagram.com/loom'],
            {'instagram': ['https://instagram.com/loom']},
            {'instagram': {'url': 'https://instagram.com/loom'}},
            {'instagram': 12345},
            {'  ': 'https://instagram.com/loom'},
        ):
            with self.subTest(bad=bad):
                res = self.client.patch(
                    f'/api/marketing/brands/{self.brand_a.id}/',
                    {'social_links': bad},
                    format='json',
                )
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.data)
        self.brand_a.refresh_from_db()
        self.assertEqual(self.brand_a.social_links, {})

    def test_a_business_profile_is_invisible_to_another_workspace(self):
        """The profile carries location and audience — the fields a competitor
        would most want, so scoping is asserted on them specifically."""
        for field, value in self.PROFILE.items():
            setattr(self.brand_a, field, value)
        self.brand_a.save()

        self.as_(self.mallory, self.ws_b)
        detail = self.client.get(f'/api/marketing/brands/{self.brand_a.id}/')
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

        listing = self.client.get('/api/marketing/brands/')
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertNotIn(str(self.brand_a.id), [str(row['id']) for row in listing.data])
