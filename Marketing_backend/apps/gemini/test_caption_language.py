"""The caption speaks the customer's language; the headline stays English.

The headline is painted INTO the image, and the image model's non-Latin
glyph rendering is not yet trustworthy enough to bet a client's poster on —
so `caption_language` steers `postDescription` (and a few hashtags) only,
and says so explicitly to Step 1.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.gemini.services.generator import GeminiGeneratorService

STEP1_JSON = json.dumps({
    'postTitle': 'Ruby Radiance', 'postDescription': 'A caption.',
    'postHashtags': '#silk', 'imagePrompt': 'a composition',
})


class Recorder:
    def __init__(self):
        self.prompts = []

    def generate_content(self, model=None, contents=None, config=None):
        self.prompts.append(contents[0] if contents else '')
        return SimpleNamespace(text=STEP1_JSON)


@override_settings(GEMINI_API_KEY='server-key')
class CaptionLanguageTests(SimpleTestCase):
    def prompt_for(self, **brief):
        recorder = Recorder()
        fake = SimpleNamespace(models=recorder)
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_text_and_image_prompt(
                {'contentType': 'poster', **brief}
            )
        return recorder.prompts[0]

    def test_telugu_steers_the_caption_and_protects_the_headline(self):
        prompt = self.prompt_for(caption_language='telugu')
        self.assertIn('CAPTION LANGUAGE', prompt)
        self.assertIn('Telugu script', prompt)
        self.assertIn('Keep `postTitle` in English', prompt)
        self.assertIn('brand and product tags in English', prompt)

    def test_hinglish_is_latin_script_by_design(self):
        prompt = self.prompt_for(caption_language='hinglish')
        self.assertIn('Latin script', prompt)
        self.assertIn('the way Indian social media actually talks', prompt)

    def test_english_and_unknown_languages_add_no_block(self):
        self.assertNotIn('CAPTION LANGUAGE', self.prompt_for())
        self.assertNotIn('CAPTION LANGUAGE', self.prompt_for(caption_language='english'))
        self.assertNotIn('CAPTION LANGUAGE', self.prompt_for(caption_language='klingon'))

    def test_the_allowlist_is_the_views_contract(self):
        # The async view coerces anything off this list to English; the list
        # living on the service keeps the two ends from drifting apart.
        self.assertEqual(
            GeminiGeneratorService.CAPTION_LANGUAGES,
            ('english', 'hindi', 'hinglish', 'telugu', 'tamil'),
        )
