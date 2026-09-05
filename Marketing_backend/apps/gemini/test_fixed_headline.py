"""
A brief that carries `headline` is a re-buy of a poster whose words are won:
Step 2 paints THAT headline, never the fresh title Step 1 just wrote.

Live, 2026-09-05: the image-text re-buy went through Capability.IMAGE, the
Gemini adapter re-ran Step 1, and the second poster came back under a
headline the saved copy never had.
"""
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.gemini.services.generator import GeminiGeneratorService

SAVED = 'Woven For Celebrations.'
FRESH = 'Silk Stories For Diwali'
SERVICE = 'apps.gemini.services.generator.GeminiGeneratorService'


def brief(**overrides):
    data = {
        'contentType': 'poster',
        'offer': '',
        'structured': {'identity': {'cta_keyword': 'Shop the collection'}},
        'creative_direction': {'mode': 'AI_ORIGINAL', 'selections': []},
    }
    data.update(overrides)
    return data


@override_settings(GEMINI_API_KEY='server-key')
class FixedHeadlineTests(SimpleTestCase):
    def run_pipeline(self, request_data):
        painted = {}

        def poster(**kwargs):
            painted.update(kwargs)
            return 'https://storage.test/poster.png'

        with patch(f'{SERVICE}.generate_text_and_image_prompt', return_value={
            'postTitle': FRESH, 'postDescription': 'Fresh copy.',
            'postHashtags': '#silk', 'imagePrompt': 'a poster composition',
        }), patch(f'{SERVICE}.generate_poster_image', side_effect=poster), \
                patch(f'{SERVICE}.poster_render_options', return_value=('4:5', '1K')):
            result = GeminiGeneratorService.generate_marketing_content(request_data)
        return result, painted

    def test_a_fixed_headline_is_what_step_two_paints(self):
        result, painted = self.run_pipeline(brief(headline=SAVED))
        lines = '\n'.join(painted['text_lines'])
        self.assertIn(f'"{SAVED}"', lines)
        self.assertNotIn(FRESH, lines)
        # And the copy handed back agrees with the picture.
        self.assertEqual(result['postTitle'], SAVED)
        self.assertEqual(result['posterImageUrl'], 'https://storage.test/poster.png')

    def test_without_a_fixed_headline_step_one_still_names_the_poster(self):
        result, painted = self.run_pipeline(brief())
        lines = '\n'.join(painted['text_lines'])
        self.assertIn(f'"{FRESH}"', lines)
        self.assertEqual(result['postTitle'], FRESH)

    def test_a_blank_fixed_headline_is_ignored(self):
        result, painted = self.run_pipeline(brief(headline='   '))
        self.assertIn(f'"{FRESH}"', '\n'.join(painted['text_lines']))
        self.assertEqual(result['postTitle'], FRESH)
