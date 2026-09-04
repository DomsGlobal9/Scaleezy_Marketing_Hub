"""Phase 7 — the layout and export engine."""
import base64
import io
import json
import uuid as uuid_mod
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from apps.brands.models import Brand
from apps.content.models import ContentItem
from apps.layouts import export, focus, fonts, images, registry, services, variants
from apps.layouts.patterns.base import LayoutPattern, Spec
from apps.layouts.render import compose, compose_at, spec_from
from apps.marketing.models import MarketingAsset
from apps.marketing.services.storage import StorageError
from apps.universal.services import set_client_quality
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


class StyleVariantTests(APITestCase):
    """A template is a (pattern, variant) pair; the space must be real."""

    @staticmethod
    def an_item(n):
        import uuid as uuid_mod
        from types import SimpleNamespace
        return SimpleNamespace(pk=uuid_mod.UUID(int=n))

    def test_the_catalogue_holds_more_than_a_thousand_templates(self):
        self.assertGreater(variants.catalogue_size(), 1000)

    def test_the_pick_is_deterministic_per_item(self):
        item = self.an_item(42)
        self.assertEqual(variants.variant_for(item), variants.variant_for(item))

    def test_restyle_pick_changes_even_when_the_uuid_pick_collides(self):
        item = self.an_item(42)
        inherited = variants.variant_for(item)

        picked = variants.different_variant_for(item, inherited)

        self.assertNotEqual(picked, inherited)
        self.assertEqual(picked, variants.different_variant_for(item, inherited))
        self.assertEqual(picked, variants.coerce(picked))

    def test_nearby_items_dress_differently(self):
        seen = {tuple(sorted(variants.variant_for(self.an_item(n)).items()))
                for n in range(48)}
        self.assertGreater(len(seen), 24)

    def test_a_flat_pattern_never_gets_a_photo_treatment(self):
        for n in range(24):
            picked = variants.variant_for(self.an_item(n), uses_photo=False)
            self.assertEqual(picked['photo'], 'asis')

    def test_coerce_degrades_junk_without_failing(self):
        cleaned = variants.coerce({'palette': 'neon-explosion', 'photo': 42})
        self.assertEqual(cleaned['palette'], 'classic')
        self.assertEqual(cleaned['photo'], 'asis')
        self.assertEqual(variants.coerce('not-a-dict')['casing'], 'asis')

    def test_inverted_swaps_ink_and_paper(self):
        spec = variants.apply(base_spec(), variants.coerce({'palette': 'inverted'}))
        self.assertEqual(spec.palette['primary'], PALETTE['light'])
        self.assertEqual(spec.palette['light'], PALETTE['primary'])

    def test_upper_casing_and_flipped_pairing_apply(self):
        spec = variants.apply(
            base_spec(), variants.coerce({'casing': 'upper', 'pairing': 'flipped'})
        )
        self.assertEqual(spec.headline, spec.headline.upper())
        self.assertEqual(spec.fonts['primary'], 'Noto Serif')
        self.assertEqual(spec.fonts['secondary'], 'DM Sans')

    def test_every_axis_option_still_composes(self):
        """No variant may take down a render — the whole point is safety."""
        for axis, options in (
            ('palette', variants.PALETTES), ('photo', variants.PHOTOS),
            ('paper', variants.PAPERS), ('casing', variants.CASINGS),
            ('pairing', variants.PAIRINGS),
        ):
            for option in options:
                spec = variants.apply(
                    base_spec(photo=a_photo()), variants.coerce({axis: option})
                )
                image = compose(spec, 'agency_column')
                self.assertEqual(image.size, (1080, 1350), f"{axis}={option}")

    def test_derived_papers_are_valid_hex(self):
        for paper in variants.PAPERS:
            spec = variants.apply(base_spec(), variants.coerce({'paper': paper}))
            value = spec.palette['light']
            self.assertRegex(value, r'^#[0-9a-fA-F]{6}$')


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

    def test_preview_requires_an_explicit_layout(self):
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/preview/', {'headline': 'Hi'}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_preview_honours_the_requested_size(self):
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/preview/',
            {'headline': 'Hi', 'size': 'x', 'layout': 'agency_column'},
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
            {'headline': 'Hi', 'brand': str(theirs.id), 'layout': 'agency_column'},
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

    def test_manual_render_becomes_the_explicit_per_content_template_choice(self):
        self.item.layout_config = {
            'creative_direction': {
                'mode': 'REFERENCE',
                'selection_count': 1,
                'selections': [{'id': 'reference-1'}],
            }
        }
        self.item.save(update_fields=['layout_config'])
        self.as_(self.editor)

        res = self.client.post(
            '/api/marketing/layouts/render/',
            {'content_item': str(self.item.id), 'layout': 'data_hero'},
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.item.refresh_from_db()
        direction = self.item.layout_config['creative_direction']
        self.assertEqual(direction['mode'], 'CATALOG_TEMPLATE')
        self.assertEqual(direction['layout'], 'data_hero')
        self.assertEqual(direction['selections'], [])
        self.assertEqual(
            self.item.layout_config['source_creative_direction']['mode'],
            'REFERENCE',
        )

    def test_render_persists_the_copy_it_composed_with(self):
        """The studio's edited words survive the render: headline/offer land on
        the item, the slots without columns land in layout_config['copy'], so
        an export — whose serializer carries no copy fields — reproduces the
        poster that was actually on screen."""
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/render/',
            {
                'content_item': str(self.item.id),
                'layout': 'data_hero',
                'headline': 'Rewritten in the studio',
                'subheadline': 'Handloom silk, forty pieces.',
                'offer': '60% OFF',
                'cta': 'Shop the edit',
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        self.item.refresh_from_db()
        self.assertEqual(self.item.headline, 'Rewritten in the studio')
        self.assertEqual(self.item.cta, '60% OFF')
        copy = self.item.layout_config['copy']
        self.assertEqual(copy['subheadline'], 'Handloom silk, forty pieces.')
        self.assertEqual(copy['cta'], 'Shop the edit')

        # And a later export composes without error from the persisted copy.
        export = self.client.post(
            '/api/marketing/layouts/export/',
            {'content_item': str(self.item.id), 'sizes': ['instagram_portrait']},
            format='json',
        )
        self.assertEqual(export.status_code, status.HTTP_201_CREATED)

    def test_an_explicit_blank_clears_a_saved_line(self):
        """Deleting a subheadline in the studio must remove it — not have the
        saved value resurrected on every later compose."""
        self.as_(self.editor)
        first = self.client.post(
            '/api/marketing/layouts/render/',
            {
                'content_item': str(self.item.id),
                'layout': 'cos_split',
                'subheadline': 'Weekend drop only.',
            },
            format='json',
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.item.refresh_from_db()
        self.assertEqual(
            self.item.layout_config['copy']['subheadline'], 'Weekend drop only.'
        )

        second = self.client.post(
            '/api/marketing/layouts/render/',
            {'content_item': str(self.item.id), 'subheadline': ''},
            format='json',
        )
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.item.refresh_from_db()
        self.assertNotIn('subheadline', self.item.layout_config.get('copy', {}))

    def test_export_accepts_the_copy_on_screen(self):
        """The export serializer takes the same overrides as preview/render,
        so exporting without a prior save cannot ship different words."""
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/export/',
            {
                'content_item': str(self.item.id),
                'layout': 'cos_split',
                'sizes': ['instagram_portrait'],
                'headline': 'Words from the screen',
                'subheadline': 'Exactly as previewed.',
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:300])

    def test_a_poisoned_copy_config_degrades_instead_of_500ing(self):
        """layout_config is client-writable JSON; a malformed 'copy' must fall
        back to defaults, never brick every later preview of the item."""
        self.item.layout_config = {'copy': ['not', 'a', 'dict']}
        self.item.save(update_fields=['layout_config'])
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/layouts/preview/',
            {'content_item': str(self.item.id), 'layout': 'cos_split'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:300])

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
            {'content_item': str(self.item.id), 'layout': 'cos_split'},
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
            layout_config={'creative_direction': {'mode': 'AI_ORIGINAL'}},
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

    def test_selected_template_failure_is_not_reported_as_success(self):
        self.item.layout_plugin = 'cos_split'
        self.item.layout_config = {
            'creative_direction': {
                'mode': 'CATALOG_TEMPLATE',
                'layout': 'cos_split',
            }
        }
        self.item.save(update_fields=['layout_plugin', 'layout_config'])

        with patch(
            'apps.layouts.services.SupabaseStorageService.upload_and_describe',
            side_effect=StorageError('down'),
        ), self.assertRaises(services.PosterCompositionError):
            services.compose_generated_poster(self.item)

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


class CoverFocusTests(APITestCase):
    """Focal-point-aware crop-to-fill — the face-cutting fix, by geometry."""

    @staticmethod
    def gradient(width, height):
        """Every column and row uniquely coloured, so a crop's position is
        readable straight off its pixels."""
        image = Image.new('RGB', (width, height))
        px = image.load()
        for x in range(width):
            for y in range(height):
                px[x, y] = (x % 256, y % 256, (x + y) % 256)
        return image

    @staticmethod
    def legacy_cover(photo, width, height):
        """The exact pre-focus algorithm, kept verbatim as the golden."""
        width, height = max(1, int(width)), max(1, int(height))
        source = photo.convert('RGB')
        scale = max(width / source.width, height / source.height)
        resized = source.resize(
            (max(1, int(source.width * scale)), max(1, int(source.height * scale))),
            Image.LANCZOS,
        )
        left = (resized.width - width) // 2
        top = (resized.height - height) // 2
        return resized.crop((left, top, left + width, top + height))

    @classmethod
    def resized(cls, photo, width, height):
        """The intermediate scaled image, for computing expected windows."""
        source = photo.convert('RGB')
        scale = max(width / source.width, height / source.height)
        return source.resize(
            (max(1, int(source.width * scale)), max(1, int(source.height * scale))),
            Image.LANCZOS,
        )

    def assertWindow(self, photo, size, focus, left, top):
        """cover() with `focus` lands the (left, top) window exactly."""
        width, height = size
        expected = self.resized(photo, width, height).crop(
            (left, top, left + width, top + height)
        )
        actual = LayoutPattern.cover(photo, width, height, focus)
        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_no_focus_is_the_legacy_centred_crop_pixel_for_pixel(self):
        # 305->100 leaves odd slack: the case where round() would drift.
        for source_size, crop in (
            ((305, 100), (100, 100)),
            ((300, 200), (90, 120)),
            ((101, 103), (50, 50)),
        ):
            photo = self.gradient(*source_size)
            self.assertEqual(
                LayoutPattern.cover(photo, *crop).tobytes(),
                self.legacy_cover(photo, *crop).tobytes(),
                f"{source_size} -> {crop}",
            )

    def test_an_explicit_centre_focus_is_also_the_legacy_crop(self):
        photo = self.gradient(305, 100)  # odd slack on x
        self.assertEqual(
            LayoutPattern.cover(photo, 100, 100, {'x': 0.5, 'y': 0.5}).tobytes(),
            self.legacy_cover(photo, 100, 100).tobytes(),
        )

    def test_edge_focal_points_clamp_to_the_frame(self):
        photo = self.gradient(400, 100)  # scale 1.0: window slides on x only
        self.assertWindow(photo, (100, 100), {'x': 0.0, 'y': 0.5}, 0, 0)
        self.assertWindow(photo, (100, 100), {'x': 1.0, 'y': 0.5}, 300, 0)

    def test_the_focal_point_steers_the_window(self):
        photo = self.gradient(400, 100)
        # left = floor(0.25 * 400 - 100 / 2) = 50
        self.assertWindow(photo, (100, 100), {'x': 0.25, 'y': 0.5}, 50, 0)

    def test_a_vertical_focal_point_clamps_too(self):
        photo = self.gradient(100, 400)
        # top = floor(0.9 * 400 - 50) = 310, clamped to 400 - 100 = 300.
        self.assertWindow(photo, (100, 100), {'x': 0.5, 'y': 0.9}, 0, 300)

    def test_a_bbox_that_fits_is_shifted_fully_inside(self):
        photo = self.gradient(400, 100)
        # Focal pulls the window to the far left; the subject sits at
        # x 280..360 and fits an 100-wide window, so the window shifts the
        # minimum distance: left = ceil(360) - 100 = 260.
        focus_dict = {'x': 0.1, 'y': 0.5, 'bbox': [0.7, 0.0, 0.9, 1.0]}
        self.assertWindow(photo, (100, 100), focus_dict, 260, 0)

    def test_a_bbox_bigger_than_the_window_centres_on_it(self):
        photo = self.gradient(400, 100)
        # Subject spans x 40..360 (320 wide, window 100): centre on its
        # midpoint 200 -> left = floor(200 - 50) = 150.
        focus_dict = {'x': 0.1, 'y': 0.5, 'bbox': [0.1, 0.0, 0.9, 1.0]}
        self.assertWindow(photo, (100, 100), focus_dict, 150, 0)

    def test_junk_focus_degrades_to_the_centred_crop(self):
        photo = self.gradient(305, 100)
        golden = self.legacy_cover(photo, 100, 100).tobytes()
        for junk in (
            {'x': 'oops', 'y': None, 'bbox': 'junk'},
            {'bbox': [0.5, 0.5, 0.2, 'x']},
            {'bbox': [0.9, 0.1, 0.9, 0.6]},  # zero-width bbox
            'not-a-dict',
            {'skipped': 'NoProviderAvailable'},
        ):
            self.assertEqual(
                LayoutPattern.cover(photo, 100, 100, junk).tobytes(),
                golden,
                repr(junk),
            )

    def test_the_focus_travels_through_the_spec_into_a_pattern(self):
        photo = self.gradient(2160, 400)
        centred = compose(base_spec(photo=photo), 'cos_split')
        steered = compose(
            base_spec(photo=photo, photo_focus={'x': 0.05, 'y': 0.5}), 'cos_split'
        )
        self.assertNotEqual(centred.tobytes(), steered.tobytes())


class PhotoFocusDetectionTests(APITestCase):
    """One cached vision call per source photo, degrading to centred."""

    GOOD = {
        'analysis': {
            'focal': {'x': 0.3, 'y': 0.4},
            'subject_bbox': [0.2, 0.2, 0.5, 0.6],
            'has_face': True,
        },
        'provider': 'gemini',
    }

    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='f', workspace_name='Focus')

    def test_a_good_payload_is_shaped_and_clamped(self):
        payload = {
            'analysis': {
                'focal': {'x': 1.7, 'y': -0.2},
                'subject_bbox': [0.9, 0.1, 0.4, 0.6],  # inverted on x
                'has_face': 1,
            },
            'provider': 'gemini',
        }
        with patch('apps.ai.router.AIRouter.dispatch', return_value=payload):
            result = focus.detect_photo_focus(self.ws, a_photo(200, 100))
        self.assertEqual(result, {
            'x': 1.0, 'y': 0.0, 'bbox': [0.4, 0.1, 0.9, 0.6],
            'has_face': True, 'provider': 'gemini',
        })

    def test_the_brief_follows_the_inspiration_idiom(self):
        with patch('apps.ai.router.AIRouter.dispatch', return_value=self.GOOD) as dispatch:
            focus.detect_photo_focus(self.ws, a_photo(2000, 1000))
        (capability, brief), _kwargs = dispatch.call_args
        from apps.ai.models import Capability
        self.assertEqual(capability, Capability.IMAGE_ANALYSIS)
        self.assertEqual(brief['task'], 'SUBJECT_FOCUS')
        self.assertIs(brief['response_schema'], focus.FOCUS_SCHEMA)
        self.assertIn('untrusted evidence', brief['instruction'])
        self.assertTrue(brief['reference_image_base64'].startswith('data:image/jpeg;base64,'))
        # The photo is thumbnailed before the call — resolution buys nothing
        # for normalized output, and small images are what keeps this cheap.
        sent = images.from_base64(brief['reference_image_base64'])
        self.assertLessEqual(max(sent.width, sent.height), focus.ANALYSIS_MAX_EDGE)

    def test_dispatch_failure_becomes_a_skipped_marker_not_an_exception(self):
        from apps.ai.router import NoProviderAvailable
        with patch(
            'apps.ai.router.AIRouter.dispatch',
            side_effect=NoProviderAvailable('nobody home'),
        ):
            result = focus.detect_photo_focus(self.ws, a_photo())
        self.assertEqual(result, {'skipped': 'NoProviderAvailable'})

    def test_malformed_payloads_are_skipped_not_raised(self):
        for payload, reason in (
            ({'analysis': {'nope': 1}}, 'MALFORMED_RESPONSE'),
            ({'analysis': {'focal': {'x': 'a', 'y': 0.2}}}, 'MALFORMED_RESPONSE'),
            ({'analysis': 'not json {'}, 'JSONDecodeError'),
        ):
            with patch('apps.ai.router.AIRouter.dispatch', return_value=payload):
                result = focus.detect_photo_focus(self.ws, a_photo())
            self.assertEqual(result, {'skipped': reason}, repr(payload))

    def test_a_broken_bbox_loses_only_the_bbox(self):
        payload = {
            'analysis': {
                'focal': {'x': 0.6, 'y': 0.6},
                'subject_bbox': [0.1, 'x', 0.9, 0.9],
                'has_face': False,
            },
        }
        with patch('apps.ai.router.AIRouter.dispatch', return_value=payload):
            result = focus.detect_photo_focus(self.ws, a_photo())
        self.assertEqual(result['x'], 0.6)
        self.assertIsNone(result['bbox'])


class ComposeFocusTests(APITestCase):
    """The automatic compose pays for at most one vision call per photo."""

    PAYLOAD = PhotoFocusDetectionTests.GOOD
    STORED = {
        'x': 0.3, 'y': 0.4, 'bbox': [0.2, 0.2, 0.5, 0.6],
        'has_face': True, 'provider': 'gemini',
    }

    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='d', workspace_name='Delta')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Delta Co', palette=dict(PALETTE), is_default=True,
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
            layout_config={'creative_direction': {'mode': 'AI_ORIGINAL'}},
        )
        # The photograph resolves locally; nothing is fetched in tests.
        patcher = patch('apps.layouts.render.photo_for', return_value=a_photo(800, 600))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_first_compose_detects_once_and_recompose_never_pays_again(self):
        with patch('apps.ai.router.AIRouter.dispatch', return_value=self.PAYLOAD) as dispatch:
            self.assertIsNotNone(services.compose_generated_poster(self.item))
            self.item.refresh_from_db()
            self.assertEqual(self.item.layout_config['photo_focus'], self.STORED)
            self.assertEqual(dispatch.call_count, 1)
            chosen = self.item.layout_plugin

            # Recompose: stored focus wins; the layout never reshuffles.
            self.assertIsNotNone(services.compose_generated_poster(self.item))
            self.item.refresh_from_db()
            self.assertEqual(dispatch.call_count, 1)
            self.assertEqual(self.item.layout_plugin, chosen)
            self.assertEqual(self.item.layout_config['photo_focus'], self.STORED)

    def test_a_failed_detection_degrades_and_is_never_retried(self):
        with patch(
            'apps.ai.router.AIRouter.dispatch', side_effect=RuntimeError('boom')
        ) as dispatch:
            self.assertIsNotNone(services.compose_generated_poster(self.item))
            self.item.refresh_from_db()
            self.assertEqual(
                self.item.layout_config['photo_focus'], {'skipped': 'RuntimeError'}
            )
            self.assertIsNotNone(services.compose_generated_poster(self.item))
            self.assertEqual(dispatch.call_count, 1)

    def test_the_toggle_off_never_dispatches(self):
        set_client_quality(self.ws, focus_crop_enabled=False)
        with patch('apps.ai.router.AIRouter.dispatch', return_value=self.PAYLOAD) as dispatch:
            self.assertIsNotNone(services.compose_generated_poster(self.item))
        self.assertEqual(dispatch.call_count, 0)
        self.item.refresh_from_db()
        self.assertNotIn('photo_focus', self.item.layout_config)

    def test_a_pre_stored_focus_wins_without_a_dispatch(self):
        config = dict(self.item.layout_config)
        config['photo_focus'] = dict(self.STORED)
        self.item.layout_config = config
        self.item.save(update_fields=['layout_config'])
        with patch('apps.ai.router.AIRouter.dispatch', return_value=self.PAYLOAD) as dispatch:
            self.assertIsNotNone(services.compose_generated_poster(self.item))
        self.assertEqual(dispatch.call_count, 0)
        self.item.refresh_from_db()
        self.assertEqual(self.item.layout_config['photo_focus'], self.STORED)

    def test_the_focus_survives_a_storage_failure(self):
        """A paid vision result is cached even when the compose itself fails,
        so the retry after a storage hiccup does not pay twice."""
        with patch('apps.ai.router.AIRouter.dispatch', return_value=self.PAYLOAD) as dispatch:
            with patch(
                'apps.layouts.services.SupabaseStorageService.upload_and_describe',
                side_effect=StorageError('down'),
            ):
                self.assertIsNone(services.compose_generated_poster(self.item))
            self.item.refresh_from_db()
            self.assertEqual(self.item.layout_config['photo_focus'], self.STORED)

            # Storage recovers; the vision call is not repeated.
            self.assertIsNotNone(services.compose_generated_poster(self.item))
            self.assertEqual(dispatch.call_count, 1)


class VarietySelectionTests(APITestCase):
    """Recency-weighted layout picking: the same brand stops getting the
    same skeleton, without ever reshuffling an item under review."""

    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='v', workspace_name='Var')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Var Co', palette=dict(PALETTE), is_default=True,
        )
        self.options = [
            key for key in registry.keys()
            if getattr(registry.get(key), 'uses_photo', True)
        ]

    def composed(self, layout, age_minutes):
        item = ContentItem.objects.create(
            workspace=self.ws, brand=self.brand, headline='old', layout_plugin=layout,
        )
        ContentItem.objects.filter(pk=item.pk).update(
            created_at=timezone.now() - timedelta(minutes=age_minutes)
        )
        return item

    def fresh_item(self):
        return ContentItem.objects.create(
            workspace=self.ws, brand=self.brand, headline='new',
        )

    def legacy_pick(self, item):
        seed = uuid_mod.UUID(str(item.pk)).int
        return self.options[seed % len(self.options)]

    def test_history_steers_away_from_the_recent_pattern(self):
        for age in (1, 2, 3):
            self.composed('cos_split', age)
        item = self.fresh_item()
        pick = services.generated_layout(item)
        self.assertIn(pick, self.options)
        self.assertNotEqual(pick, 'cos_split')
        # Deterministic for a given (item, history).
        self.assertEqual(pick, services.generated_layout(item))

    def test_equal_counts_prefer_the_oldest_recent_use(self):
        # Newest -> oldest: every option used exactly once; the winner is the
        # one whose last outing is furthest back.
        for age, layout in enumerate(self.options, start=1):
            self.composed(layout, age)
        pick = services.generated_layout(self.fresh_item())
        self.assertEqual(pick, self.options[-1])

    def test_no_history_falls_back_to_the_legacy_modulo(self):
        item = self.fresh_item()
        self.assertEqual(services.generated_layout(item), self.legacy_pick(item))

    def test_disabled_variety_keeps_the_legacy_modulo(self):
        set_client_quality(self.ws, variety_enabled=False)
        item = self.fresh_item()
        # Crowd the legacy pick's pattern; the toggle keeps the old maths.
        for age in (1, 2, 3):
            self.composed(self.legacy_pick(item), age)
        self.assertEqual(services.generated_layout(item), self.legacy_pick(item))

    def test_an_item_without_a_brand_keeps_the_stateless_pick(self):
        # The gemini test-suite calls generated_layout with bare namespaces;
        # nothing here may add a query (or a crash) to that path.
        item = SimpleNamespace(pk=uuid_mod.UUID(int=5))
        self.assertEqual(
            services.generated_layout(item), self.options[5 % len(self.options)]
        )


class VariantNudgeTests(APITestCase):
    """A repeated skeleton must not repeat its predecessor's dress too."""

    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='n', workspace_name='Nudge')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Nudge Co', palette=dict(PALETTE), is_default=True,
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
            layout_config={'creative_direction': {'mode': 'AI_ORIGINAL'}},
        )
        # No photo -> no focus dispatch; the nudge is what is under test.
        patcher = patch('apps.layouts.render.photo_for', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

        # Every photo pattern used once, oldest last: the picker will choose
        # the pattern of the OLDEST prior, which this test controls.
        self.options = [
            key for key in registry.keys()
            if getattr(registry.get(key), 'uses_photo', True)
        ]
        self.priors = []
        for age, layout in enumerate(self.options, start=1):
            prior = ContentItem.objects.create(
                workspace=self.ws, brand=self.brand, headline='old',
                layout_plugin=layout,
            )
            ContentItem.objects.filter(pk=prior.pk).update(
                created_at=timezone.now() - timedelta(minutes=age)
            )
            self.priors.append(prior)
        self.chosen = self.options[-1]
        self.candidate = variants.variant_for(self.item, uses_photo=True)

    def dress_prior(self, variant):
        prior = self.priors[-1]  # the oldest: its pattern is the one chosen
        prior.layout_config = {'style_variant': variant}
        prior.save(update_fields=['layout_config'])

    def test_a_same_dress_prior_triggers_a_deterministic_restyle(self):
        self.dress_prior(dict(self.candidate))
        self.assertIsNotNone(services.compose_generated_poster(self.item))
        self.item.refresh_from_db()
        self.assertEqual(self.item.layout_plugin, self.chosen)
        expected = variants.different_variant_for(
            self.item, self.candidate, uses_photo=True
        )
        self.assertEqual(self.item.layout_config['style_variant'], expected)
        self.assertNotEqual(self.item.layout_config['style_variant'], self.candidate)

    def test_a_different_palette_prior_keeps_the_uuid_variant(self):
        different = dict(self.candidate)
        index = variants.PALETTES.index(different['palette'])
        different['palette'] = variants.PALETTES[(index + 1) % len(variants.PALETTES)]
        self.dress_prior(different)
        self.assertIsNotNone(services.compose_generated_poster(self.item))
        self.item.refresh_from_db()
        self.assertEqual(self.item.layout_config['style_variant'], self.candidate)

    def test_variety_off_never_nudges(self):
        set_client_quality(self.ws, variety_enabled=False)
        self.dress_prior(dict(self.candidate))
        self.assertIsNotNone(services.compose_generated_poster(self.item))
        self.item.refresh_from_db()
        self.assertEqual(self.item.layout_config['style_variant'], self.candidate)


class GeminiFocusGateTests(APITestCase):
    """The adapter honours response_schema for SUBJECT_FOCUS and keeps the
    legacy behaviour for every unlisted task. Lives here to keep the whole
    quality-engine change set reviewable in one app."""

    PAYLOAD = {
        'focal': {'x': 0.5, 'y': 0.4},
        'subject_bbox': [0.1, 0.1, 0.9, 0.9],
        'has_face': True,
    }

    def stub(self, payload):
        calls = {}

        class Stub:
            TEXT_MODEL = 'gemini-test'

            @staticmethod
            def _parse_base64_image(b64):
                return 'image/jpeg', b'img-bytes'

            @staticmethod
            def _get_client(credentials):
                def generate_content(**kwargs):
                    calls['kwargs'] = kwargs
                    return SimpleNamespace(text=json.dumps(payload))
                return SimpleNamespace(
                    models=SimpleNamespace(generate_content=generate_content)
                )

            @staticmethod
            def analyze_reference_image(b64, api_key=''):
                calls['legacy'] = True
                return {'legacy': True}

        return Stub, calls

    def analyze(self, brief, payload=None):
        from apps.ai.adapters.gemini import GeminiAdapter

        stub, calls = self.stub(payload or self.PAYLOAD)
        with patch.object(GeminiAdapter, '_service', lambda adapter: stub):
            return GeminiAdapter().analyze_image(brief), calls

    def test_subject_focus_goes_through_the_structured_path(self):
        result, calls = self.analyze({
            'task': 'SUBJECT_FOCUS',
            'instruction': 'find the subject',
            'response_schema': focus.FOCUS_SCHEMA,
            'reference_image_base64': 'data:image/jpeg;base64,AAAA',
        })
        self.assertEqual(result['analysis'], self.PAYLOAD)
        self.assertNotIn('legacy', calls)
        # response_schema was actually forwarded to the model call.
        self.assertIn('config', calls['kwargs'])

    def test_an_incomplete_structured_payload_is_rejected(self):
        from apps.ai.adapters.base import AIProviderError

        with self.assertRaises(AIProviderError):
            self.analyze(
                {
                    'task': 'SUBJECT_FOCUS',
                    'response_schema': focus.FOCUS_SCHEMA,
                    'reference_image_base64': 'data:image/jpeg;base64,AAAA',
                },
                payload={'focal': {'x': 0.5, 'y': 0.4}},  # missing required keys
            )

    def test_other_tasks_keep_the_legacy_path_identically(self):
        result, calls = self.analyze({'reference_image_base64': 'AAAA'})
        self.assertEqual(result, {'analysis': {'legacy': True}})
        self.assertTrue(calls.get('legacy'))
        self.assertNotIn('kwargs', calls)
