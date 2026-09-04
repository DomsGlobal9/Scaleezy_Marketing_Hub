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
from apps.context.services.generation import _template_image
from apps.gemini.services.generator import GeminiGeneratorService

from .test_template_defaulting import make_template

PNG_BYTES = b'not-really-a-png'
DATA_URL = 'data:image/png;base64,' + base64.b64encode(PNG_BYTES).decode('ascii')


class FakeModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, *, model, contents, config=None):
        self.calls.append({'model': model, 'contents': contents})
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
        self.assertIn('Recreate THIS EXACT design', directive)
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
