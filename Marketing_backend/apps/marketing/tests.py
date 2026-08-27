import io
from unittest.mock import patch

from django.test import TestCase
from PIL import Image

from apps.marketing.services.compositor import BrandAddonCompositor


class BrandAddonCompositorTests(TestCase):
    def setUp(self):
        # Create a test 1080x1350 RGB image
        img = Image.new('RGB', (1080, 1350), color=(30, 40, 60))
        out = io.BytesIO()
        img.save(out, format='JPEG')
        self.sample_bytes = out.getvalue()

    def test_composite_returns_untouched_when_no_addons_requested(self):
        result = BrandAddonCompositor.composite_poster(
            self.sample_bytes,
            include_logo=False,
            include_phone=False,
        )
        self.assertEqual(result, self.sample_bytes)

    def test_composite_returns_empty_when_empty_bytes(self):
        result = BrandAddonCompositor.composite_poster(
            b'',
            include_logo=True,
            logo_url='https://example.com/logo.png',
        )
        self.assertEqual(result, b'')

    def test_make_white_transparent(self):
        # Create a 50x50 image with a white background and red center
        img = Image.new('RGBA', (50, 50), (255, 255, 255, 255))
        for x in range(15, 35):
            for y in range(15, 35):
                img.putpixel((x, y), (220, 20, 20, 255))

        transparent_img = BrandAddonCompositor._make_white_transparent(img)
        # Corner should now have alpha 0 (transparent)
        corner_pixel = transparent_img.getpixel((0, 0))
        self.assertEqual(corner_pixel[3], 0)
        # Center should remain opaque
        center_pixel = transparent_img.getpixel((25, 25))
        self.assertEqual(center_pixel[3], 255)

    @patch('apps.marketing.services.compositor.requests.get')
    def test_composite_with_logo_and_footer(self, mock_get):
        # Mock logo response
        logo_img = Image.new('RGBA', (200, 80), (255, 255, 255, 255))
        logo_bytes = io.BytesIO()
        logo_img.save(logo_bytes, format='PNG')
        
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.content = logo_bytes.getvalue()
        mock_response.raise_for_status = lambda: None

        result = BrandAddonCompositor.composite_poster(
            self.sample_bytes,
            logo_url='https://example.com/logo.png',
            include_logo=True,
            phone_number='9988048400',
            include_phone=True,
            website='https://visaworx.klartravels.com/',
            cta='Start Application',
            brand_name='Visaworx',
        )

        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)
        
        # Verify it's a valid JPEG image
        out_img = Image.open(io.BytesIO(result))
        self.assertEqual(out_img.size, (1080, 1350))
