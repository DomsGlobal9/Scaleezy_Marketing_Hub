"""The caption speaks the customer's language; the headline stays English.

The headline is painted INTO the image, and the image model's non-Latin
glyph rendering is not yet trustworthy enough to bet a client's poster on —
so `caption_language` steers `postDescription` (and a few hashtags) only,
and says so explicitly to Step 1.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

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

    def test_an_english_only_guardrail_outranks_the_chip(self):
        # The exact line guardrails.prompt_lines() emits for
        # language_rule='english_only' — written law wins.
        prompt = self.prompt_for(
            caption_language='telugu',
            guardrail_rules=['Write in English only.'],
        )
        self.assertNotIn('CAPTION LANGUAGE', prompt)

    def test_the_allowlist_is_the_views_contract(self):
        # The async view coerces anything off this list to English; the list
        # living on the service keeps the two ends from drifting apart.
        self.assertEqual(
            GeminiGeneratorService.CAPTION_LANGUAGES,
            ('english', 'hindi', 'hinglish', 'telugu', 'tamil'),
        )


class LanguageSurvivesReviewRoundsTests(APITestCase):
    """Round 1 worked off the parent fallback and then forgot: the language
    must ride the request-edits whitelist so round 2 (whose parent is the
    round-1 revision) still speaks it."""

    def test_the_revision_inherits_the_language(self):
        from apps.content.models import ContentItem
        from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

        workspace = MarketingWorkspace.objects.create(
            customer_id='lang1', workspace_name='Lang'
        )
        manager = get_user_model().objects.create_user(username='lmgr', password='pw')
        WorkspaceMember.objects.create(
            workspace=workspace, user=manager, role=WorkspaceMember.Role.MANAGER
        )
        item = ContentItem.objects.create(
            workspace=workspace, headline='Telugu drop',
            status=ContentItem.Status.PENDING_REVIEW,
            layout_config={'caption_language': 'telugu'},
        )
        self.client.force_authenticate(user=manager)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
        res = self.client.post(
            f'/api/marketing/content/{item.pk}/request-edits/',
            {'note': 'Make the caption warmer.'}, format='json',
        )
        self.assertEqual(res.status_code, 200, res.data)
        revision = ContentItem.objects.get(parent=item)
        self.assertEqual(revision.layout_config.get('caption_language'), 'telugu')


class ProviderNeutralBackstopTests(SimpleTestCase):
    """Non-Gemini TEXT providers see only the brief — the note spells the
    contract out, and the validator refuses an un-paintable headline."""

    def test_a_non_english_brief_carries_the_note(self):
        from apps.context.services.generation import _caption_language_note

        brief = _caption_language_note({'caption_language': 'hindi'})
        self.assertIn('postTitle MUST remain in English', brief['caption_language_note'])
        self.assertNotIn(
            'caption_language_note', _caption_language_note({'caption_language': 'english'})
        )
        self.assertNotIn('caption_language_note', _caption_language_note({}))

    def test_a_non_latin_headline_is_refused_when_the_caption_went_local(self):
        from apps.ai.models import Capability
        from apps.context.services.generation import OutputRejected, validate_output

        devanagari = {'headline': 'रूबी रेडियंस दुल्हन संग्रह', 'raw': {}}
        with self.assertRaises(OutputRejected):
            validate_output(
                Capability.TEXT, devanagari, {'hard_rules': []},
                brief={'caption_language': 'hindi'},
            )
        # English headline (emoji and all) passes; and with no language asked,
        # the guard never runs at all.
        validate_output(
            Capability.TEXT, {'headline': 'Ruby Radiance is Live! ✨', 'raw': {}},
            {'hard_rules': []}, brief={'caption_language': 'hindi'},
        )
        validate_output(
            Capability.TEXT, devanagari, {'hard_rules': []},
            brief={'caption_language': 'english'},
        )
