"""Phase 7 — the layout and export engine."""
import base64
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from apps.brands.models import Brand
from apps.content.models import ContentItem
from apps.layouts import export, fonts, images, registry, services
from apps.layouts.patterns.base import Spec
from apps.layouts.render import compose, compose_at, spec_from
from apps.marketing.models import MarketingAsset
from apps.marketing.services.storage import StorageError
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()

PALETTE = {'primary': '#101020', 'light': '#FAFAF0', 'accent': '#C0FFA0'}


def a_photo(width=1600, height=900, colour='#446677'):
    return Image.new('RGB', (width, height), colour)


def base_spec(**kwargs):
    defaults = dict(
        width=1080, height=1350,
        headline='Festive drop lands this Friday only',
        subheadline='Handwoven silk, limited to forty pieces.',
        offer='50% OFF',
        cta='Shop now',
        tagline='Diwali',
        palette=dict(PALETTE),
        fonts={'primary': 'DM Sans', 'secondary': 'Noto Serif'},
    )
    defaults.update(kwargs)
    return Spec(**defaults)


class RegistryTests(APITestCase):
    def test_all_six_layouts_are_discovered(self):
        self.assertEqual(
            registry.keys(),
            ['agency_column', 'cos_split', 'data_hero', 'ghost_word', 'jil_sander', 'vs_table'],
        )

    def test_layout_keys_match_the_brands_choices(self):
        # A brand can only pick a layout that is installed, and vice versa.
        self.assertEqual(set(registry.keys()), {c[0] for c in Brand.Layout.choices})

    def test_unknown_layout_falls_back_rather_than_failing(self):
        self.assertIsNotNone(registry.resolve('no_such_layout'))
        self.assertIsNone(registry.get('no_such_layout'))

    def test_catalogue_describes_every_pattern(self):
        entries = registry.catalogue()
        self.assertEqual(len(entries), 6)
        for entry in entries:
            self.assertTrue(entry['key'] and entry['display_name'] and entry['description'])


class FontTests(APITestCase):
    def test_a_missing_family_still_returns_a_font(self):
        self.assertIsNotNone(fonts.load('No Such Typeface 9000', 40))

    def test_an_empty_family_still_returns_a_font(self):
        self.assertIsNotNone(fonts.load('', 24, bold=True))

    def test_sizes_are_independent(self):
        small, large = fonts.load('DM Sans', 12), fonts.load('DM Sans', 96)
        self.assertNotEqual(small.getbbox('M'), large.getbbox('M'))


class ComposeTests(APITestCase):
    def test_every_layout_renders_at_every_export_size(self):
        for key in registry.keys():
            for size_key, (_label, width, height, _p) in export.SIZES.items():
                image = compose(base_spec(width=width, height=height, photo=a_photo()), key)
                self.assertEqual(image.size, (width, height), f"{key} @ {size_key}")

    def test_composing_wide_is_a_re_render_not_a_crop(self):
        spec = base_spec(photo=a_photo())
        wide = compose_at(spec, 'agency_column', 1600, 900)
        self.assertEqual(wide.size, (1600, 900))
        # The source spec is untouched — compose_at works on a copy.
        self.assertEqual((spec.width, spec.height), (1080, 1350))

    def test_renders_without_a_photo(self):
        image = compose(base_spec(), 'agency_column')
        self.assertEqual(image.size, (1080, 1350))

    def test_renders_with_nothing_at_all(self):
        for key in registry.keys():
            self.assertIsNotNone(compose(Spec(), key))

    def test_absurd_copy_does_not_raise(self):
        spec = base_spec(headline='x' * 600, offer='y' * 200, subheadline='z' * 800)
        for key in registry.keys():
            self.assertIsNotNone(compose(spec, key))

    def test_brand_palette_is_actually_used(self):
        """The point of composing locally: the brand's own colours appear."""
        spec = base_spec(palette={'primary': '#FF0000', 'light': '#00FF00', 'accent': '#0000FF'})
        colours = {c for _count, c in compose(spec, 'agency_column').getcolors(maxcolors=1 << 20)}
        self.assertIn((255, 0, 0), colours)

    def test_phone_strip_only_when_a_phone_is_set(self):
        without = compose(base_spec(), 'jil_sander')
        with_phone = compose(base_spec(phone='+91 98765 43210'), 'jil_sander')
        self.assertNotEqual(without.tobytes(), with_phone.tobytes())
        # The strip lands on the bottom edge.
        self.assertEqual(with_phone.getpixel((5, 1349)), (16, 16, 32))

    def test_logo_overlay_lands_top_right(self):
        logo = Image.new('RGB', (200, 80), '#FF00FF')
        without = compose(base_spec(photo=a_photo()), 'cos_split')
        with_logo = compose(base_spec(photo=a_photo(), logo=logo), 'cos_split')
        self.assertNotEqual(without.tobytes(), with_logo.tobytes())
        self.assertEqual(with_logo.getpixel((1010, 90)), (255, 0, 255))

    def test_a_bad_palette_falls_back_instead_of_crashing(self):
        for palette in ({'primary': 'not-a-colour'}, {'primary': 123}, {}, None):
            spec = base_spec(palette=palette)
            self.assertIsNotNone(compose(spec, 'agency_column'))


class SpecFromBrandTests(APITestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Alpha Co', palette=dict(PALETTE),
            tagline='Woven well', cta_keyword='Visit us', contact_phone='+91 12345',
            show_phone_on_posters=True, layout_preference=Brand.Layout.COS_SPLIT,
        )

    def test_brand_supplies_palette_tagline_and_cta(self):
        spec = spec_from(self.brand, headline='Hello')
        self.assertEqual(spec.ink, '#101020')
        self.assertEqual(spec.tagline, 'Woven well')
        self.assertEqual(spec.cta, 'Visit us')

    def test_phone_follows_the_brand_setting(self):
        self.assertEqual(spec_from(self.brand, headline='x').phone, '+91 12345')

    def test_per_generation_override_beats_the_brand_default(self):
        spec = spec_from(self.brand, headline='x', include_phone=False)
        self.assertEqual(spec.phone, '')

    def test_a_caller_supplied_phone_wins(self):
        spec = spec_from(self.brand, headline='x', phone='+44 999')
        self.assertEqual(spec.phone, '+44 999')

    def test_no_brand_at_all_still_produces_a_spec(self):
        self.assertIsNotNone(compose(spec_from(None, headline='Hello'), 'agency_column'))


class ImageIntakeTests(APITestCase):
    def test_base64_round_trip(self):
        buffer = io.BytesIO()
        Image.new('RGB', (40, 40), '#123456').save(buffer, format='PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode()
        self.assertIsNotNone(images.from_base64(encoded))
        self.assertIsNotNone(images.from_base64(f"data:image/png;base64,{encoded}"))

    def test_junk_is_rejected_quietly(self):
        for value in ('', None, 'not base64 at all', 'data:image/png;base64,zzzz'):
            self.assertIsNone(images.from_base64(value))

    def test_non_http_urls_are_never_fetched(self):
        for url in ('file:///etc/passwd', 'ftp://host/x.png', '', None, 'javascript:x'):
            self.assertIsNone(images.from_trusted_url(url))


class ExportCatalogueTests(APITestCase):
    def test_every_documented_platform_size_is_present(self):
        by_key = {s['key']: s for s in export.catalogue()}
        self.assertEqual(
            (by_key['instagram_portrait']['width'], by_key['instagram_portrait']['height']),
            (1080, 1350),
        )
        self.assertEqual((by_key['facebook']['width'], by_key['facebook']['height']), (1200, 630))
        self.assertEqual((by_key['x']['width'], by_key['x']['height']), (1600, 900))
        self.assertEqual((by_key['linkedin']['width'], by_key['linkedin']['height']), (1200, 627))
        self.assertEqual(by_key['print_a4']['format'], 'PDF')

    def test_unknown_sizes_are_filtered_out(self):
        self.assertEqual(export.valid(['x', 'nope', 'facebook']), ['facebook', 'x'])

    def test_pdf_export_produces_a_pdf(self):
        image, fmt, _ = export.render_size(base_spec(), 'jil_sander', 'print_a4')
        self.assertEqual(fmt, 'PDF')
        self.assertTrue(export.to_file(image, fmt).read().startswith(b'%PDF'))

    def test_jpeg_export_carries_a_content_type(self):
        image, fmt, _ = export.render_size(base_spec(), 'jil_sander', 'x')
        buffer = export.to_file(image, fmt)
        self.assertEqual(buffer.content_type, 'image/jpeg')
        self.assertTrue(buffer.read(3), b'\xff\xd8\xff')


class LayoutAPITests(APITestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.other = MarketingWorkspace.objects.create(customer_id='b', workspace_name='Beta')

        self.editor = User.objects.create_user(username='ed', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.editor, role=WorkspaceMember.Role.EDITOR
        )
        self.viewer = User.objects.create_user(username='vw', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.viewer, role=WorkspaceMember.Role.VIEWER
        )
        self.outsider = User.objects.create_user(username='out', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.other, user=self.outsider, role=WorkspaceMember.Role.OWNER
        )

        self.brand = Brand.objects.create(
            workspace=self.ws, name='Alpha Co', palette=dict(PALETTE), is_default=True,
            layout_preference=Brand.Layout.COS_SPLIT,
        )
        self.item = ContentItem.objects.create(
            workspace=self.ws, brand=self.brand, headline='Festive drop', cta='50% OFF',
        )

    def as_(self, user, ws=None):
        self.client.force_authenticate(user=user)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str((ws or self.ws).id))

    # -- catalogue -------------------------------------------------------
    def test_anonymous_rejected(self):
        self.client.credentials()
        self.assertEqual(
            self.client.get('/api/marketing/layouts/').status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_catalogue_lists_layouts_and_sizes(self):
        self.as_(self.viewer)
        res = self.client.get('/api/marketing/layouts/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['data']['layouts']), 6)
        self.assertTrue(res.data['data']['sizes'])

    # -- preview ---------------------------------------------------------
    def test_preview_returns_pixels_and_stores_nothing(self):
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/preview/',
            {'headline': 'Festive drop', 'layout': 'agency_column'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['data']['preview'].startswith('data:image/jpeg;base64,'))
        self.assertFalse(MarketingAsset.objects.exists())

    def test_preview_uses_the_brands_layout_when_none_is_named(self):
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/preview/', {'headline': 'Hi'}, format='json'
        )
        self.assertEqual(res.data['data']['layout'], 'cos_split')

    def test_preview_honours_the_requested_size(self):
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/preview/',
            {'headline': 'Hi', 'size': 'x'},
            format='json',
        )
        self.assertEqual((res.data['data']['width'], res.data['data']['height']), (1600, 900))

    def test_unknown_layout_is_a_400(self):
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/preview/',
            {'headline': 'Hi', 'layout': 'not_installed'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_viewer_cannot_compose(self):
        self.as_(self.viewer)
        res = self.client.post(
            '/api/marketing/layouts/preview/', {'headline': 'Hi'}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_another_tenants_brand_is_not_reachable(self):
        theirs = Brand.objects.create(workspace=self.other, name='Beta Co',
                                      palette={'primary': '#FF0000'})
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/preview/',
            {'headline': 'Hi', 'brand': str(theirs.id)},
            format='json',
        )
        # Falls back to no brand rather than rendering with theirs.
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['data']['layout'], 'agency_column')

    # -- render ----------------------------------------------------------
    def test_render_persists_and_points_the_item_at_it(self):
        # Storage is stubbed by STORAGE_TEST_MODE, so this exercises the real
        # success path without uploading anything.
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/render/',
            {'content_item': str(self.item.id), 'layout': 'data_hero'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        self.item.refresh_from_db()
        self.assertEqual(self.item.layout_plugin, 'data_hero')
        self.assertTrue(self.item.preview_url)
        self.assertIsNotNone(self.item.asset)
        self.assertEqual(self.item.asset.source, MarketingAsset.Source.COMPOSED)
        self.assertEqual((self.item.asset.width, self.item.asset.height), (1080, 1350))

    def test_render_of_another_tenants_content_is_a_404(self):
        theirs = ContentItem.objects.create(workspace=self.other, headline='Theirs')
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/render/',
            {'content_item': str(theirs.id)},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(MarketingAsset.objects.exists())

    def test_render_cannot_replace_media_after_content_is_approved(self):
        approved_asset = MarketingAsset.objects.create(
            workspace=self.ws,
            file_name='approved.jpg',
            file_url='https://storage.test/approved.jpg',
            source=MarketingAsset.Source.MANUAL_UPLOAD,
        )
        self.item.asset = approved_asset
        self.item.preview_url = approved_asset.file_url
        self.item.status = ContentItem.Status.APPROVED
        self.item.save(update_fields=['asset', 'preview_url', 'status'])
        self.as_(self.editor)

        res = self.client.post(
            '/api/marketing/layouts/render/',
            {'content_item': str(self.item.id), 'layout': 'data_hero'},
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['error']['code'], 'CONTENT_LOCKED')
        self.item.refresh_from_db()
        self.assertEqual(self.item.asset, approved_asset)
        self.assertEqual(self.item.preview_url, approved_asset.file_url)
        self.assertEqual(self.item.layout_plugin, '')
        self.assertEqual(MarketingAsset.objects.count(), 1)

    @patch('apps.layouts.services.SupabaseStorageService.upload_and_describe')
    def test_render_reports_a_storage_failure_rather_than_lying(self, upload):
        upload.side_effect = StorageError("Storage rejected the upload (500).")
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/render/',
            {'content_item': str(self.item.id)},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_502_BAD_GATEWAY)
        # And the item is left alone rather than pointed at a URL that 404s.
        self.item.refresh_from_db()
        self.assertEqual(self.item.layout_plugin, '')
        self.assertFalse(MarketingAsset.objects.exists())

    # -- export ----------------------------------------------------------
    def test_export_produces_one_asset_per_size(self):
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/export/',
            {
                'content_item': str(self.item.id),
                'layout': 'cos_split',
                'sizes': ['instagram_portrait', 'x', 'linkedin'],
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        exports = res.data['data']['exports']
        self.assertEqual(len(exports), 3)
        self.assertEqual(
            {(e['width'], e['height']) for e in exports},
            {(1080, 1350), (1600, 900), (1200, 627)},
        )
        self.assertEqual(MarketingAsset.objects.count(), 3)

    def test_export_rejects_an_unknown_size(self):
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/export/',
            {'content_item': str(self.item.id), 'sizes': ['instagram_portrait', 'myspace']},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_export_of_another_tenants_content_is_a_404(self):
        theirs = ContentItem.objects.create(workspace=self.other, headline='Theirs')
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/export/',
            {'content_item': str(theirs.id), 'sizes': ['x']},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class AutoComposeTests(APITestCase):
    """The compose engine running automatically after a generation persists."""

    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='c', workspace_name='Gamma')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Gamma Co', palette=dict(PALETTE), is_default=True,
        )
        self.photo = MarketingAsset.objects.create(
            workspace=self.ws,
            file_name='generated.png',
            file_url='https://storage.test/generated/x/generated.png',
            source=MarketingAsset.Source.AI_GENERATED,
        )
        self.item = ContentItem.objects.create(
            workspace=self.ws, brand=self.brand, asset=self.photo,
            headline='Festive drop', cta='50% OFF',
            preview_url=self.photo.file_url,
        )

    def test_composes_and_points_the_item_at_the_poster(self):
        asset = services.compose_generated_poster(self.item)

        self.assertIsNotNone(asset)
        self.item.refresh_from_db()
        self.assertEqual(self.item.asset_id, asset.id)
        self.assertEqual(asset.source, MarketingAsset.Source.COMPOSED)
        self.assertEqual(self.item.preview_url, asset.file_url)
        self.assertTrue(self.item.layout_plugin)
        # The original photograph survives, recorded as the source.
        self.assertEqual(self.item.layout_config['source_asset'], str(self.photo.id))
        self.assertTrue(MarketingAsset.objects.filter(pk=self.photo.pk).exists())

    def test_a_compose_failure_leaves_the_generation_untouched(self):
        with patch(
            'apps.layouts.services.SupabaseStorageService.upload_and_describe',
            side_effect=StorageError('down'),
        ):
            self.assertIsNone(services.compose_generated_poster(self.item))

        self.item.refresh_from_db()
        self.assertEqual(self.item.asset_id, self.photo.id)
        self.assertEqual(self.item.preview_url, self.photo.file_url)

    def test_only_posters_with_copy_and_media_are_composed(self):
        bare = ContentItem.objects.create(
            workspace=self.ws, brand=self.brand, headline='No media',
        )
        self.assertIsNone(services.compose_generated_poster(bare))

        video = ContentItem.objects.create(
            workspace=self.ws, brand=self.brand, asset=self.photo, headline='Video',
            content_format=ContentItem.Format.VIDEO,
        )
        self.assertIsNone(services.compose_generated_poster(video))

    def test_recomposing_reads_the_original_photo_not_the_poster(self):
        services.compose_generated_poster(self.item)
        self.item.refresh_from_db()
        # The composed poster is the asset, but the photograph is the source.
        self.assertEqual(services.source_photo_asset(self.item).pk, self.photo.pk)
