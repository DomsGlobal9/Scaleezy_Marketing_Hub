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
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.common.testing import TenantFixtureMixin
from apps.content.models import ContentItem
from apps.context.services.generation import recent_headlines
from apps.gemini.services.generator import GeminiGeneratorService
from apps.layouts import registry
from apps.layouts.services import generated_layout


class GeneratedLayoutRotationTests(SimpleTestCase):
    """The automatic compose no longer parks every brand on one skeleton."""

    @staticmethod
    def item(n):
        return SimpleNamespace(pk=uuid.UUID(int=n))

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
