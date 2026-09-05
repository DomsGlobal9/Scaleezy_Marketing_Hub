"""Oversized PNG posters are transcoded at the persistence boundary.

The Developer API cannot be asked for JPEG output (Vertex-only knob), so a
4K poster arrives as PNG and can brush the 20 MB cap. Rejecting it there
would forfeit an image that is already paid for; transcoding to q95 JPEG
keeps the poster and the cap.
"""
import base64
import io
from unittest.mock import patch

from django.test import TestCase
from PIL import Image

from apps.common.testing import TenantFixtureMixin
from apps.context.services import generation


class PngTranscodeTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'png1')

    def _png_result(self):
        image = Image.new('RGB', (64, 80), 'red')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode()
        return {'image_url': f'data:image/png;base64,{encoded}'}

    def test_a_png_past_the_threshold_becomes_a_jpeg(self):
        with patch.object(generation, 'PNG_TRANSCODE_OVER_BYTES', 10):
            result = generation.persist_generated_image(self.workspace, self._png_result())
        self.assertEqual(result['mime_type'], 'image/jpeg')
        self.assertTrue(result['file_name'].endswith('.jpg'))
        self.assertLess(result['file_size'], generation.MAX_GENERATED_IMAGE_BYTES)

    def test_a_small_png_is_stored_untouched(self):
        result = generation.persist_generated_image(self.workspace, self._png_result())
        self.assertEqual(result['mime_type'], 'image/png')
        self.assertTrue(result['file_name'].endswith('.png'))
