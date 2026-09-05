"""Pixels never ride in a prompt string.

`_brief_json` is what both OpenAI-shaped adapters paste into their TEXT and
IMAGE prompts. A reference photo in the brief (`ambassador_image_base64`,
`template_image_base64`) is tens of thousands of characters that mean
nothing as text and blow the prompt limit - which is how a brand with a
model photo could never buy a picture, or repair one, on these providers.
"""
import json

from django.test import SimpleTestCase

from apps.ai.adapters.openai import OpenAIAdapter
from apps.ai.adapters.openai_compatible import OpenAICompatibleTextAdapter

BRIEF = {
    'headline': 'Roasted this week',
    'ambassador_image_base64': 'data:image/png;base64,' + 'A' * 60000,
    'template_image_base64': 'data:image/png;base64,' + 'B' * 60000,
    'reference_image_base64': 'data:image/png;base64,CCCC',
    'pre_image_hook': lambda payload: payload,
    'must': ['Say "Roasted this week"'],
}


class BriefJsonKeepsPixelsOutOfPromptsTests(SimpleTestCase):
    def check(self, adapter_cls):
        text = adapter_cls._brief_json(BRIEF)
        data = json.loads(text)
        self.assertEqual(data['headline'], 'Roasted this week')
        self.assertEqual(data['must'], ['Say "Roasted this week"'])
        for key in ('ambassador_image_base64', 'template_image_base64',
                    'reference_image_base64', 'pre_image_hook'):
            self.assertNotIn(key, data)
        self.assertLess(len(text), 2000)

    def test_openai_prompt_json_drops_every_pixel_key_and_hooks(self):
        self.check(OpenAIAdapter)

    def test_openai_compatible_prompt_json_drops_every_pixel_key_and_hooks(self):
        self.check(OpenAICompatibleTextAdapter)
