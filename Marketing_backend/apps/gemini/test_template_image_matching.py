"""Template-exact generation: the chosen BRAND_TEMPLATE's own pixels reach
the image model with a recreate-this-design directive, so matching the
template is image-conditioned instead of reconstructed from a written
description. Ordinary generations stay text-only — the anti-copy design
decision stands everywhere except the brand's own template.
"""
import base64
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.context.services.generation import _ambassador_image, _template_image
from apps.inspirations.models import BrandInspiration
from apps.gemini.services.generator import GeminiGeneratorService

from .test_template_defaulting import make_template

PNG_BYTES = b'not-really-a-png'
DATA_URL = 'data:image/png;base64,' + base64.b64encode(PNG_BYTES).decode('ascii')


class FakeModels:
    def __init__(self, reject_image_config=False):
        self.calls = []
        self.reject_image_config = reject_image_config

    def generate_content(self, *, model, contents, config=None):
        self.calls.append({'model': model, 'contents': contents, 'config': config})
        if self.reject_image_config and getattr(config, 'image_config', None) is not None:
            raise ValueError('image_config is not supported by this model')
        part = SimpleNamespace(
            inline_data=SimpleNamespace(mime_type='image/png', data=b'poster-bytes')
        )
        return SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))]
        )


class PosterImageTemplateTests(TestCase):
    def test_template_pixels_and_recreate_directive_reach_the_image_model(self):
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            url = GeminiGeneratorService.generate_poster_image(
                'A serene product scene.',
                api_key='k',
                text_lines=['MUST: render "Big Sale"'],
                template_image_base64=DATA_URL,
            )
        self.assertTrue(url.startswith('data:image/png;base64,'))
        contents = fake.models.calls[0]['contents']
        self.assertEqual(len(contents), 2)
        image_part, directive = contents
        self.assertEqual(image_part.inline_data.data, PNG_BYTES)
        self.assertIn("BRAND'S OWN POSTER TEMPLATE", directive)
        # Structure fidelity, scene novelty: the template is a layout
        # reference, and the photograph inside it must be new every run.
        self.assertIn('LAYOUT REFERENCE, not a scene to copy', directive)
        self.assertIn('Recreate its design STRUCTURE exactly', directive)
        self.assertIn('NEW photograph inside the photo area', directive)
        self.assertIn("never reproduce the template's photo, model, scene or props", directive)
        # Product-neutral: "styling" varies for any brand; "garment" only fits one.
        self.assertIn('framing, setting and styling', directive)
        self.assertNotIn('garment', directive)
        # Step 1's composition and the verbatim headline still ride along.
        self.assertIn('A serene product scene.', directive)
        self.assertIn('Big Sale', directive)

    def test_without_a_template_the_call_stays_text_only(self):
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_poster_image(
                'A serene product scene.', api_key='k',
            )
        contents = fake.models.calls[0]['contents']
        self.assertEqual(len(contents), 1)
        self.assertIsInstance(contents[0], str)

    def test_the_ambassador_photo_rides_along_with_an_identity_directive(self):
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_poster_image(
                'A serene product scene.', api_key='k',
                template_image_base64=DATA_URL,
                ambassador_image_base64=DATA_URL,
            )
        contents = fake.models.calls[0]['contents']
        # Two image parts, then one directive that labels them by number.
        self.assertEqual(len(contents), 3)
        directive = contents[2]
        self.assertIn('ATTACHED IMAGE 1 IS THIS BRAND', directive)
        self.assertIn("ATTACHED IMAGE 2 IS THE BRAND'S MODEL/AMBASSADOR", directive)
        self.assertIn('THIS EXACT person', directive)

    def test_the_ambassador_works_without_a_template_too(self):
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_poster_image(
                'A serene product scene.', api_key='k',
                ambassador_image_base64=DATA_URL,
            )
        contents = fake.models.calls[0]['contents']
        self.assertEqual(len(contents), 2)
        self.assertIn("ATTACHED IMAGE 1 IS THE BRAND'S MODEL/AMBASSADOR", contents[1])

    def test_the_image_call_requests_full_resolution_at_the_poster_aspect(self):
        # The reported blur: model-default ~1K output stretched to 1080x1350
        # and beyond by exports. Every poster call must ask for 4K at 4:5
        # (founder's call) — and ONLY those two fields: output_mime_type and
        # output_compression_quality are Vertex-only, and on the api-key path
        # the SDK raises for them client-side, which silently rode the
        # fallback and shipped 1K posters.
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_poster_image('A scene.', api_key='k')
        self.assertEqual(len(fake.models.calls), 1, 'the config must not trip the fallback')
        config = fake.models.calls[0]['config']
        self.assertEqual(config.image_config.aspect_ratio, '4:5')
        self.assertEqual(config.image_config.image_size, '4K')
        self.assertIsNone(config.image_config.output_mime_type)
        self.assertIsNone(config.image_config.output_compression_quality)

    def test_a_model_that_rejects_the_resolution_hint_still_delivers(self):
        fake = SimpleNamespace(models=FakeModels(reject_image_config=True))
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            url = GeminiGeneratorService.generate_poster_image('A scene.', api_key='k')
        self.assertTrue(url.startswith('data:image/png;base64,'))
        self.assertEqual(len(fake.models.calls), 2)
        self.assertIsNone(getattr(fake.models.calls[1]['config'], 'image_config', None))

    def test_platforms_map_to_aspects_and_quality_tiers_to_sizes(self):
        cases = [
            ({'platform': 'instagram_story', 'image_quality': '2K'}, ('9:16', '2K')),
            ({'platform': 'linkedin', 'image_quality': '1K'}, ('16:9', '1K')),
            ({'platform': 'print'}, ('2:3', '4K')),
            ({'platform': 'nonsense', 'image_quality': '8K'}, ('4:5', '4K')),
            ({}, ('4:5', '4K')),
        ]
        for request_data, expected in cases:
            self.assertEqual(
                GeminiGeneratorService.poster_render_options(request_data), expected,
            )

    def test_the_requested_aspect_and_size_reach_the_image_call(self):
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_poster_image(
                'A scene.', api_key='k', aspect_ratio='9:16', image_size='2K',
            )
        config = fake.models.calls[0]['config']
        self.assertEqual(config.image_config.aspect_ratio, '9:16')
        self.assertEqual(config.image_config.image_size, '2K')

    def test_a_non_poster_aspect_tells_the_template_to_recompose(self):
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_poster_image(
                'A scene.', api_key='k', template_image_base64=DATA_URL,
                aspect_ratio='9:16',
            )
        directive = fake.models.calls[0]['contents'][-1]
        self.assertIn('FORMAT ADAPTATION', directive)
        self.assertIn('9:16', directive)

    def test_the_native_aspect_needs_no_adaptation_note(self):
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_poster_image(
                'A scene.', api_key='k', template_image_base64=DATA_URL,
            )
        self.assertNotIn('FORMAT ADAPTATION', fake.models.calls[0]['contents'][-1])

    def test_all_three_references_ride_together_numbered(self):
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_poster_image(
                'A scene.', api_key='k',
                template_image_base64=DATA_URL,
                ambassador_image_base64=DATA_URL,
                product_image_base64=DATA_URL,
            )
        contents = fake.models.calls[0]['contents']
        self.assertEqual(len(contents), 4)
        directive = contents[3]
        self.assertIn('ATTACHED IMAGE 1 IS THIS BRAND', directive)
        self.assertIn("ATTACHED IMAGE 2 IS THE BRAND'S MODEL/AMBASSADOR", directive)
        self.assertIn("ATTACHED IMAGE 3 IS THE BRAND'S ACTUAL PRODUCT", directive)
        self.assertIn('buy exactly what they see', directive)

    def test_the_product_photo_works_alone_too(self):
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_poster_image(
                'A scene.', api_key='k', product_image_base64=DATA_URL,
            )
        contents = fake.models.calls[0]['contents']
        self.assertEqual(len(contents), 2)
        self.assertIn("ATTACHED IMAGE 1 IS THE BRAND'S ACTUAL PRODUCT", contents[1])

    def test_product_photos_are_uploadable(self):
        from apps.inspirations.serializers import IMAGE_INSPIRATION_TYPES

        self.assertIn(
            BrandInspiration.InspirationType.BRAND_PRODUCT, IMAGE_INSPIRATION_TYPES,
        )

    def test_copy_complaints_rebuy_the_image_when_the_words_live_in_it(self):
        # Seen live: a headline-tagged request-edits on an undressed poster
        # regenerated the caption to title case while the image kept shouting
        # ALL CAPS — the words are painted into a delegated poster, so a
        # copy-only pass cannot fix them.
        from apps.content.models import ContentItem
        from apps.gemini.tasks import _scope_for_revision

        feedback = SimpleNamespace(element_keys=['headline'])
        undressed = SimpleNamespace(
            content_format=ContentItem.Format.POSTER,
            layout_plugin='',
            Format=ContentItem.Format,
        )
        dressed = SimpleNamespace(
            content_format=ContentItem.Format.POSTER,
            layout_plugin='agency_column',
            Format=ContentItem.Format,
        )
        carousel = SimpleNamespace(
            content_format=ContentItem.Format.CAROUSEL,
            layout_plugin='',
            Format=ContentItem.Format,
        )
        with patch(
            'apps.gemini.tasks._regeneration_scope',
            side_effect=lambda f: {'copy': True, 'image': False, 'restyle': False},
        ):
            self.assertTrue(_scope_for_revision(feedback, undressed)['image'])
            self.assertFalse(_scope_for_revision(feedback, dressed)['image'])
            self.assertFalse(_scope_for_revision(feedback, carousel)['image'])

    def test_a_garbage_template_payload_degrades_to_text_only(self):
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_poster_image(
                'A serene product scene.', api_key='k',
                template_image_base64='not-a-data-url',
            )
        contents = fake.models.calls[0]['contents']
        self.assertEqual(len(contents), 1)


class TemplateImageResolutionTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'tpl1')
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme', is_default=True,
            status=Brand.Status.ACTIVE,
        )
        self.template = make_template(self.workspace, self.brand, 'Signature')

    def _direction(self, **row):
        return {'mode': 'REFERENCE', 'selections': [{
            'kind': 'BRAND_TEMPLATE', 'id': str(self.template.pk),
            'direction': 'USE', **row,
        }]}

    def test_a_used_template_resolves_to_its_stored_pixels(self):
        with patch(
            'apps.inspirations.analysis._stored_media_data', return_value=DATA_URL,
        ) as loader:
            self.assertEqual(_template_image(self._direction()), DATA_URL)
        loader.assert_called_once()

    def test_everything_else_resolves_to_nothing_without_failing(self):
        # AVOID means "do not look like this" — attaching it would do the
        # opposite of what the user asked.
        self.assertEqual(_template_image(self._direction(direction='AVOID')), '')
        # A row that no longer exists, storage being down, and no direction
        # at all: each degrades to prompt-only, never an exception.
        self.assertEqual(
            _template_image({'selections': [
                {'kind': 'BRAND_TEMPLATE', 'id': 'not-a-uuid', 'direction': 'USE'},
            ]}),
            '',
        )
        with patch(
            'apps.inspirations.analysis._stored_media_data',
            side_effect=RuntimeError('storage down'),
        ):
            self.assertEqual(_template_image(self._direction()), '')
        self.assertEqual(_template_image(None), '')
        self.assertEqual(_template_image({'selections': []}), '')

    def test_inspired_fidelity_keeps_the_template_pixels_home(self):
        # INSPIRED is the variety valve: the template lends its flavour
        # through analysed observations, never its pixels — so the layout can
        # differ every run.
        from apps.context.services.generation import _reference_pixels

        brief = {'creative_direction': self._direction(), 'feature_ambassador': False}
        with patch(
            'apps.inspirations.analysis._stored_media_data', return_value=DATA_URL,
        ):
            exact = _reference_pixels(self.brand, brief)
            inspired = _reference_pixels(
                self.brand, {**brief, 'template_fidelity': 'INSPIRED'}
            )
        self.assertIn('template_image_base64', exact)
        self.assertNotIn('template_image_base64', inspired)

    def test_the_newest_active_ambassador_photo_is_the_one_attached(self):
        for title in ('First shoot', 'Latest shoot'):
            BrandInspiration.objects.create(
                workspace=self.workspace, brand=self.brand, title=title,
                inspiration_type=BrandInspiration.InspirationType.BRAND_AMBASSADOR,
                file_url=f'https://storage.test/amb/{title}.jpg',
                mime_type='image/jpeg',
            )
        with patch(
            'apps.inspirations.analysis._stored_media_data', return_value=DATA_URL,
        ) as loader:
            self.assertEqual(_ambassador_image(self.brand), DATA_URL)
        self.assertEqual(loader.call_args.args[0].title, 'Latest shoot')

    def test_ambassador_photos_are_uploadable(self):
        # The upload serializer allowlists image-based types; leaving
        # BRAND_AMBASSADOR out made the studio's "Your model" upload 400 in
        # production while every direct-ORM test stayed green.
        from apps.inspirations.serializers import IMAGE_INSPIRATION_TYPES

        self.assertIn(
            BrandInspiration.InspirationType.BRAND_AMBASSADOR,
            IMAGE_INSPIRATION_TYPES,
        )

    def test_a_product_photo_resolves_only_within_its_own_brand(self):
        from apps.context.services.generation import _product_image

        product = BrandInspiration.objects.create(
            workspace=self.workspace, brand=self.brand, title='Silk hamper',
            inspiration_type=BrandInspiration.InspirationType.BRAND_PRODUCT,
            file_url='https://storage.test/products/hamper.jpg',
            mime_type='image/jpeg',
        )
        with patch(
            'apps.inspirations.analysis._stored_media_data', return_value=DATA_URL,
        ):
            self.assertEqual(_product_image(self.brand, str(product.pk)), DATA_URL)
            # Another brand's id, a non-product row, and garbage all resolve
            # to nothing — the id comes straight from the request payload.
            other_brand = Brand.objects.create(
                workspace=self.workspace, name='Other', status=Brand.Status.ACTIVE,
            )
            self.assertEqual(_product_image(other_brand, str(product.pk)), '')
            self.assertEqual(_product_image(self.brand, str(self.template.pk)), '')
            self.assertEqual(_product_image(self.brand, 'not-a-uuid'), '')
            self.assertEqual(_product_image(self.brand, ''), '')
        product.lifecycle_status = BrandInspiration.LifecycleStatus.ARCHIVED
        product.save(update_fields=['lifecycle_status'])
        self.assertEqual(_product_image(self.brand, str(product.pk)), '')

    def test_no_ambassador_or_archived_only_means_no_photo(self):
        self.assertEqual(_ambassador_image(self.brand), '')
        BrandInspiration.objects.create(
            workspace=self.workspace, brand=self.brand, title='Old face',
            inspiration_type=BrandInspiration.InspirationType.BRAND_AMBASSADOR,
            file_url='https://storage.test/amb/old.jpg', mime_type='image/jpeg',
            lifecycle_status=BrandInspiration.LifecycleStatus.ARCHIVED,
        )
        self.assertEqual(_ambassador_image(self.brand), '')
