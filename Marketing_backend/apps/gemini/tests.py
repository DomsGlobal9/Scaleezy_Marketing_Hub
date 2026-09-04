"""
Poster variety — what keeps two similar briefs from producing the same poster.

Verified live on production (2026-09-01): every automatically composed poster
wore the registry's default layout because nothing ever varied the fallback,
and near-identical briefs came back with near-identical headlines because the
prompt never said what the brand had already published. These tests pin the
two counter-measures: the per-item layout rotation and the do-not-repeat
headline block in the copy prompt.
"""
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.common.testing import TenantFixtureMixin
from apps.content.models import ContentItem
from apps.context.services.context_gateway import NO_TEXT_LINE
from apps.context.services.generation import recent_headlines
from apps.gemini.services.generator import GeminiGeneratorService
from apps.layouts import registry
from apps.layouts.services import generated_layout


class GeneratedLayoutRotationTests(SimpleTestCase):
    """The automatic compose no longer parks every brand on one skeleton.

    Since the no-default-dress decision the rotation serves only callers
    without a delegated creative direction (kept for the user-uploaded
    template pipeline); AI_ORIGINAL and REFERENCE items get None and ship
    the provider's poster raw."""

    @staticmethod
    def item(n):
        return SimpleNamespace(pk=uuid.UUID(int=n))

    def test_a_delegated_design_gets_no_layout(self):
        for mode in ('AI_ORIGINAL', 'REFERENCE'):
            delegated = SimpleNamespace(
                pk=uuid.UUID(int=3),
                layout_config={'creative_direction': {'mode': mode}},
            )
            self.assertIsNone(generated_layout(delegated), mode)

    def test_rotation_stays_inside_the_photo_patterns(self):
        photo_keys = {k for k in registry.keys() if registry.get(k).uses_photo}
        picks = {generated_layout(self.item(n)) for n in range(24)}
        self.assertTrue(picks <= photo_keys)

    def test_rotation_actually_rotates(self):
        picks = {generated_layout(self.item(n)) for n in range(24)}
        self.assertGreater(len(picks), 1)

    def test_type_only_patterns_are_never_chosen(self):
        # They would throw away the photograph the generation just paid for.
        picks = {generated_layout(self.item(n)) for n in range(24)}
        self.assertNotIn('data_hero', picks)
        self.assertNotIn('vs_table', picks)

    def test_the_pick_is_stable_for_one_item(self):
        # A recompose or revision must not reshuffle a poster mid-review.
        item = self.item(7)
        self.assertEqual(generated_layout(item), generated_layout(item))

    def test_a_malformed_pk_still_returns_a_pattern(self):
        pick = generated_layout(SimpleNamespace(pk='not-a-uuid'))
        self.assertIn(pick, registry.keys())


class VarietyBlockTests(SimpleTestCase):
    """The copy prompt tells the model what it must not say again."""

    def test_recent_headlines_become_a_hard_constraint(self):
        block = GeminiGeneratorService._variety_block(
            ['Your Voice, Our Art', 'Threads of Tradition']
        )
        self.assertIn('ALREADY PUBLISHED', block)
        self.assertIn('Your Voice, Our Art', block)
        self.assertIn('Threads of Tradition', block)
        self.assertIn('must NOT reuse', block)

    def test_no_history_leaves_the_prompt_unchanged(self):
        self.assertEqual(GeminiGeneratorService._variety_block([]), '')
        self.assertEqual(GeminiGeneratorService._variety_block(None), '')
        self.assertEqual(GeminiGeneratorService._variety_block(['', '   ']), '')

    def test_the_list_is_capped_inside_the_prompt(self):
        block = GeminiGeneratorService._variety_block([f'Headline {n}' for n in range(20)])
        self.assertIn('Headline 5', block)
        self.assertNotIn('Headline 6', block)

    def test_the_block_reaches_the_model(self):
        captured = {}

        class FakeModels:
            def generate_content(self, model, contents):
                captured['prompt'] = contents[0]
                return SimpleNamespace(text=json.dumps({
                    'postTitle': 'Fresh angle',
                    'postDescription': 'New words.',
                    'postHashtags': '#new',
                    'imagePrompt': 'A different scene.',
                }))

        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_text_and_image_prompt({
                'campaign_name': 'Launch',
                'recent_headlines': ['Echoes of Elegance'],
            })
        self.assertIn('ALREADY PUBLISHED', captured['prompt'])
        self.assertIn('Echoes of Elegance', captured['prompt'])


class OnImageTextPipelineTests(SimpleTestCase):
    """The Gemini two-step pipeline paints the headline onto the poster.

    Step 1 describes the composition around the headline without wording it;
    Step 2 carries the exact postTitle, CTA and offer verbatim. Where the
    compose engine still owns the words (carousel slides, catalogue
    templates) both steps keep the no-text rule."""

    POSTER = {
        'campaign_name': 'Launch',
        'offer': '30% off',
        'contentType': 'poster',
        'structured': {'identity': {'cta_keyword': 'MORE INFO'}},
        'creative_direction': {'mode': 'AI_ORIGINAL', 'selections': []},
    }
    STEP_ONE = {
        'postTitle': 'Roasted this week', 'postDescription': 'D',
        'postHashtags': '#h', 'imagePrompt': 'A warm cafe scene.',
    }

    def step_one_prompt(self, request_data):
        captured = {}

        class FakeModels:
            def generate_content(self, model, contents):
                captured['prompt'] = contents[0]
                return SimpleNamespace(text=json.dumps(OnImageTextPipelineTests.STEP_ONE))

        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_text_and_image_prompt(request_data)
        return captured['prompt']

    def image_call(self, request_data):
        captured = {}

        class FakeModels:
            def generate_content(self, model, contents, config=None):
                captured['contents'] = contents
                part = SimpleNamespace(
                    inline_data=SimpleNamespace(mime_type='image/png', data=b'img'),
                )
                return SimpleNamespace(
                    candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))],
                )

        fake = SimpleNamespace(models=FakeModels())
        with override_settings(GEMINI_API_KEY='key', GEMINI_MOCK_MODE=False), patch.object(
            GeminiGeneratorService, 'generate_text_and_image_prompt',
            return_value=dict(self.STEP_ONE),
        ), patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            result = GeminiGeneratorService.generate_marketing_content(request_data)
        return captured['contents'][0], result

    def test_step_one_describes_a_poster_composition_for_delegated_designs(self):
        prompt = self.step_one_prompt(self.POSTER)
        self.assertIn('ON-IMAGE TEXT', prompt)
        self.assertIn('Do NOT write the headline', prompt)
        self.assertNotIn('NO TEXT IN THE IMAGE', prompt)

    def test_step_one_keeps_the_no_text_rule_where_the_compose_engine_owns_the_words(self):
        slide = {**self.POSTER, 'contentType': 'carousel_slide'}
        self.assertIn('NO TEXT IN THE IMAGE', self.step_one_prompt(slide))
        template = {
            **self.POSTER,
            'creative_direction': {'mode': 'CATALOG_TEMPLATE', 'layout': 'x'},
        }
        self.assertIn('NO TEXT IN THE IMAGE', self.step_one_prompt(template))

    def test_the_image_call_carries_the_exact_headline_and_the_cta_offer(self):
        sent, result = self.image_call(self.POSTER)
        self.assertTrue(sent.startswith('A warm cafe scene.'), sent)
        self.assertIn('"Roasted this week"', sent)
        self.assertIn('"MORE INFO"', sent)
        self.assertIn('"30% off"', sent)
        self.assertIn('Compose a clean social-sale poster', sent)
        self.assertNotIn(NO_TEXT_LINE, sent)
        self.assertTrue(result['posterImageUrl'].startswith('data:image/png;base64,'))

    def test_the_image_call_mirrors_a_reference(self):
        sent, _result = self.image_call({
            **self.POSTER,
            'creative_direction': {'mode': 'REFERENCE', 'selections': []},
        })
        self.assertIn("Mirror the reference's typographic hierarchy", sent)
        self.assertIn('"Roasted this week"', sent)

    def test_a_carousel_slide_image_call_stays_textless(self):
        sent, _result = self.image_call({**self.POSTER, 'contentType': 'carousel_slide'})
        self.assertIn(NO_TEXT_LINE, sent)
        self.assertNotIn('"Roasted this week"', sent)

    def test_step_two_paints_the_headline_the_pre_image_hook_settled(self):
        """The caller's copy gate runs between the steps, on Step 1's copy,
        and Step 2 carries the words it returned — never the first draft."""
        seen = []

        def hook(copy):
            seen.append(dict(copy))
            return {**copy, 'postTitle': 'Final words'}

        sent, result = self.image_call({**self.POSTER, 'pre_image_hook': hook})
        self.assertEqual(seen, [{
            'postTitle': 'Roasted this week', 'postDescription': 'D',
            'postHashtags': '#h',
        }])
        self.assertIn('"Final words"', sent)
        self.assertNotIn('"Roasted this week"', sent)
        self.assertEqual(result['postTitle'], 'Final words')
        self.assertEqual(result['postDescription'], 'D')
        self.assertTrue(result['posterImageUrl'].startswith('data:image/png;base64,'))

    def test_a_copy_only_call_never_runs_the_hook(self):
        hook = Mock()
        with override_settings(GEMINI_API_KEY='key', GEMINI_MOCK_MODE=False), patch.object(
            GeminiGeneratorService, 'generate_text_and_image_prompt',
            return_value=dict(self.STEP_ONE),
        ), patch.object(GeminiGeneratorService, 'generate_poster_image') as step_two:
            GeminiGeneratorService.generate_marketing_content(
                {**self.POSTER, 'copy_only': True, 'pre_image_hook': hook}
            )
        hook.assert_not_called()
        step_two.assert_not_called()


class RecentHeadlineMemoryTests(TenantFixtureMixin, TestCase):
    """The workspace's own history feeds the constraint, newest first."""

    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.created_at = timezone.now()

    def poster(self, headline):
        item = ContentItem.objects.create(workspace=self.workspace, headline=headline)
        # SQLite's database clock is only millisecond-precise, so rapid test
        # inserts can tie even though production orders them by creation time.
        self.created_at += timedelta(seconds=1)
        ContentItem.objects.filter(pk=item.pk).update(created_at=self.created_at)
        return item

    def test_newest_distinct_headlines_only(self):
        for line in ['First drop', 'Second drop', 'Second drop', '', 'Third drop']:
            self.poster(line)
        recent = recent_headlines(self.workspace)
        self.assertEqual(recent[:3], ['Third drop', 'Second drop', 'First drop'])
        self.assertNotIn('', recent)

    def test_the_list_is_capped(self):
        for n in range(10):
            self.poster(f'Campaign {n}')
        self.assertEqual(len(recent_headlines(self.workspace)), 6)

    def test_other_workspaces_do_not_leak_in(self):
        other = self.make_workspace('Rival', 'c2')
        ContentItem.objects.create(workspace=other, headline='Rival secret launch')
        self.poster('Our own line')
        self.assertEqual(recent_headlines(self.workspace), ['Our own line'])

    def test_an_empty_workspace_returns_nothing(self):
        self.assertEqual(recent_headlines(self.workspace), [])
