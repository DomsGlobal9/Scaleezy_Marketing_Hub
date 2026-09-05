"""
Poster variety: a brand's delegated posters rotate through composition
archetypes and scene seeds instead of reproducing one recipe.

The founder's complaint, with evidence: "all the posters are having more or
less the same template design". Every AI-original poster was told the same
framed social-sale panel, and every run of one brand template reproduced the
template's own photograph. These tests pin the fix:

  * a catalogue of 8 archetypes, each placing headline, CTA and offer;
  * a least-recently-used pick per brand over its last 8 posters, with a
    deterministic tie-break on the request id, never crossing a brand or a
    workspace;
  * the directive carries the picked archetype and never another's line;
  * template mode keeps the template's structure but demands a new
    photograph, and a scene seed rides in both modes;
  * the picks land in the generation trace, which is what the next pick
    reads back.
"""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.ai.models import Capability
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.content.models import ContentItem
from apps.context.services.context_gateway import (
    COMPOSITION_ARCHETYPES,
    DEFAULT_COMPOSITION_ARCHETYPE,
    FACE_VISIBLE_LINE,
    SCENE_VARIANTS,
    brief_cta_and_offer,
    composition_archetype,
    step1_line,
    on_image_text_lines,
    scene_directive,
)
from apps.context.services.creative_direction import (
    _prompt_lines,
    _recent_variety_keys,
    pick_composition_archetype,
    pick_scene_variant,
    pick_variety,
)
from apps.context.services.generation import generate_copy_and_image, retry_image
from apps.gemini.services.generator import GeminiGeneratorService

ARCHETYPE_KEYS = [row['key'] for row in COMPOSITION_ARCHETYPES]
SCENE_KEYS = [row['key'] for row in SCENE_VARIANTS]
FACE_SAFE_KEYS = [row['key'] for row in SCENE_VARIANTS if not row.get('crops_face')]
CLOSE_UP = next(row['key'] for row in SCENE_VARIANTS if row.get('crops_face'))
AMBASSADOR = 'data:image/png;base64,AAAA'
FRAMED_LINE = 'Compose a clean social-sale poster'
FRAMED_STEP1 = 'a framed border, a centred photo panel'
NEW_PHOTO_RULE = 'the photograph and scene must be entirely new'
SCENE_LINE = 'MUST: Shoot the photograph as'
HEADLINE = 'Roasted this week'

FAKE_TEXT = {
    'headline': HEADLINE, 'caption': 'Fresh beans.', 'hashtags': '#coffee',
    'raw': {}, 'provider': 'OPENAI', 'provider_name': 'OpenAI', 'latency_ms': 10,
}
FAKE_IMAGE = {
    'image_url': 'https://cdn.example.com/poster.png',
    'provider': 'STABILITY', 'provider_name': 'Stability', 'latency_ms': 20,
}


def opening(row):
    """The distinctive opening of an archetype's composition line."""
    return row['composition'].split(':')[0]


def poster_brief(**overrides):
    brief = {
        'contentType': 'poster',
        'offer': '30% off this weekend',
        'structured': {'identity': {'cta_keyword': 'MORE INFO'}},
        'creative_direction': {'mode': 'AI_ORIGINAL', 'selections': []},
    }
    brief.update(overrides)
    return brief


def template_brief(**overrides):
    return poster_brief(creative_direction={
        'mode': '', 'selections': [{'kind': 'BRAND_TEMPLATE', 'title': 'Diwali'}],
    }, **overrides)


def recording_router(calls):
    def dispatch(self_router, capability, brief, content_item_id=None):
        calls.append({'capability': capability, 'brief': brief})
        if capability == Capability.TEXT:
            return dict(FAKE_TEXT)
        if capability == Capability.IMAGE:
            return dict(FAKE_IMAGE)
        raise AssertionError(f'unexpected {capability}')
    return dispatch


class ArchetypeCatalogueTests(SimpleTestCase):
    """Eight distinct compositions, each complete, the legacy one first."""

    def test_magazine_cover_asks_for_one_title_and_no_cover_lines(self):
        # Live, 2026-09-05: the masthead/strapline wording came back with a
        # second headline glued on and an invented strapline.
        row = composition_archetype('magazine_cover')
        for text in (row['composition'], row['step1']):
            self.assertNotIn('masthead', text)
            self.assertNotIn('strapline', text)
            self.assertIn('no cover lines', text)
        self.assertNotIn('strapline', row['offer'])

    def test_eight_unique_complete_archetypes_with_the_framed_panel_first(self):
        self.assertEqual(len(COMPOSITION_ARCHETYPES), 8)
        self.assertEqual(len(set(ARCHETYPE_KEYS)), 8)
        self.assertEqual(ARCHETYPE_KEYS[0], 'framed_panel')
        self.assertEqual(DEFAULT_COMPOSITION_ARCHETYPE, 'framed_panel')
        for row in COMPOSITION_ARCHETYPES:
            for field in ('key', 'label', 'composition', 'step1', 'cta', 'offer'):
                self.assertTrue(row.get(field), (row['key'], field))
            self.assertIn('headline', row['composition'])
            self.assertIn('{cta}', row['composition'])
            self.assertIn('{offer}', row['composition'])
            self.assertIn('headline', row['step1'])
            self.assertIn('{cta}', row['step1'])
            self.assertIn('{offer}', row['step1'])
            self.assertIn('call-to-action', row['step1_cta'])
            self.assertIn('offer', row['step1_offer'])
            # The bare description names neither: a pill or an offer line the
            # brief does not carry must never be described.
            bare = step1_line(row, '', '')
            self.assertNotIn('offer', bare)
            self.assertNotIn('call-to-action', bare)
            full = step1_line(row, 'SHOP NOW', '20% off')
            self.assertIn('call-to-action', full)
            self.assertIn('offer', full)
        self.assertEqual(
            len({opening(row) for row in COMPOSITION_ARCHETYPES}), 8,
            'every archetype must open with its own distinct directive',
        )

    def test_six_unique_scene_variants(self):
        self.assertEqual(len(SCENE_VARIANTS), 6)
        self.assertEqual(len(set(SCENE_KEYS)), 6)
        self.assertTrue(all(row['directive'] for row in SCENE_VARIANTS))

    def test_scene_seeds_are_product_neutral_and_one_frames_tighter_than_a_face(self):
        # A saree brand, a coffee roaster and a furniture maker share these
        # seeds: none may presume a garment, a fabric or a model's hair.
        for row in SCENE_VARIANTS:
            with self.subTest(row['key']):
                directive = row['directive'].lower()
                self.assertIn('hero', directive)
                for word in ('garment', 'fabric', 'jewellery', 'hair', 'twirl'):
                    self.assertNotIn(word, directive)
        cropping = [row['key'] for row in SCENE_VARIANTS if row.get('crops_face')]
        self.assertEqual(cropping, ['detail_close_up'])
        self.assertEqual(len(FACE_SAFE_KEYS), 5)

    def test_type_first_keeps_the_subject_off_the_letters(self):
        # A subject cut out over the headline occluded the words the
        # legibility MUSTs demand: the type is the background, the subject
        # sits beside or beneath it.
        row = composition_archetype('type_first')
        self.assertIn('BESIDE or BENEATH', row['composition'])
        self.assertIn('never covering a letter', row['composition'])
        self.assertIn('never covering the letters', row['step1'])
        for text in (row['composition'], row['step1']):
            self.assertNotIn('overlapping the letters', text)
            self.assertNotIn('cut-out', text)
            self.assertNotIn('cut out', text)

    def test_unknown_or_absent_archetype_falls_back_to_the_framed_panel(self):
        self.assertEqual(composition_archetype(None)['key'], 'framed_panel')
        self.assertEqual(composition_archetype('')['key'], 'framed_panel')
        self.assertEqual(composition_archetype('no-such-thing')['key'], 'framed_panel')
        joined = '\n'.join(on_image_text_lines(poster_brief(), HEADLINE))
        self.assertIn(FRAMED_LINE, joined)


class ArchetypeDirectiveTests(SimpleTestCase):
    """The image call composes the picked archetype - and only that one."""

    def test_the_directive_carries_the_picked_archetype_and_never_the_framed_panel(self):
        for row in COMPOSITION_ARCHETYPES[1:]:
            with self.subTest(row['key']):
                lines = on_image_text_lines(
                    poster_brief(composition_archetype=row['key']), HEADLINE,
                )
                joined = '\n'.join(lines)
                self.assertIn('MUST: ' + opening(row), joined)
                self.assertNotIn(FRAMED_LINE, joined)
                for other in COMPOSITION_ARCHETYPES:
                    if other['key'] != row['key']:
                        self.assertNotIn(opening(other), joined)

    def test_every_archetype_keeps_the_on_image_text_rules_and_places_cta_and_offer(self):
        for row in COMPOSITION_ARCHETYPES:
            with self.subTest(row['key']):
                lines = on_image_text_lines(
                    poster_brief(composition_archetype=row['key']), HEADLINE,
                )
                self.assertTrue(all(line.startswith('MUST:') for line in lines), lines)
                joined = '\n'.join(lines)
                self.assertIn(f'"{HEADLINE}"', joined)
                self.assertIn('word for word and correctly spelled', joined)
                self.assertIn('call-to-action pill/button reading "MORE INFO"', joined)
                self.assertIn('"30% off this weekend"', joined)
                self.assertIn('No other words on the image', joined)
                composition = [line for line in lines if opening(row) in line]
                self.assertEqual(len(composition), 1, lines)
                self.assertIn('CTA', composition[0])
                self.assertIn('offer line', composition[0])

    def test_an_absent_cta_and_offer_are_not_invented_by_any_archetype(self):
        for row in COMPOSITION_ARCHETYPES:
            with self.subTest(row['key']):
                lines = on_image_text_lines(
                    poster_brief(
                        composition_archetype=row['key'], offer='',
                        structured={'identity': {'cta_keyword': ''}},
                    ),
                    HEADLINE,
                )
                joined = '\n'.join(lines)
                self.assertNotIn('CTA', joined)
                self.assertNotIn('offer line', joined)
                self.assertIn(opening(row), joined)

    def test_reference_mode_mirrors_typography_but_composes_the_picked_archetype(self):
        brief = poster_brief(
            creative_direction={'mode': 'REFERENCE', 'selections': []},
            composition_archetype='magazine_cover',
        )
        joined = '\n'.join(on_image_text_lines(brief, HEADLINE))
        self.assertIn("Mirror the reference's typographic hierarchy", joined)
        self.assertIn(opening(composition_archetype('magazine_cover')), joined)
        self.assertNotIn(FRAMED_LINE, joined)

    def test_step_one_is_told_the_picked_archetype_not_the_framed_panel(self):
        brief = poster_brief(composition_archetype='split_vertical')
        block = GeminiGeneratorService._on_image_text_block(brief)
        self.assertIn(
            step1_line(composition_archetype('split_vertical'), *brief_cta_and_offer(brief)),
            block,
        )
        self.assertIn('Vertical split', block)
        self.assertIn('call-to-action pill', block)
        self.assertIn('vertical offer line', block)
        self.assertNotIn(FRAMED_STEP1, block)
        self.assertIn('Do NOT write the headline', block)
        self.assertNotIn('The brief carries no offer', block)
        # Absent, the legacy recipe - existing behaviour.
        self.assertIn(FRAMED_STEP1, GeminiGeneratorService._on_image_text_block(poster_brief()))

    def test_step_one_describes_no_offer_line_when_the_brief_has_no_offer(self):
        # Live, 2026-09-05: an edge "kept clear for a vertical offer line" on
        # a brief with no offer came back filled with an invented strapline.
        brief = poster_brief(composition_archetype='magazine_cover', offer='')
        block = GeminiGeneratorService._on_image_text_block(brief)
        self.assertNotIn('offer line', block)
        self.assertNotIn('strapline', block.split('The brief carries no offer')[0])
        self.assertIn('The brief carries no offer: describe no strapline', block)
        self.assertIn('the headline and the CTA pill are the only words', block)
        # And with neither a CTA nor an offer, the headline alone.
        bare = poster_brief(
            composition_archetype='magazine_cover', offer='',
            structured={'identity': {'cta_keyword': ''}},
        )
        block = GeminiGeneratorService._on_image_text_block(bare)
        self.assertNotIn('call-to-action', block)
        self.assertIn('the headline is the only words', block)


class TemplateVariationTests(SimpleTestCase):
    """Template mode keeps the structure and demands a new photograph."""

    def test_the_template_branch_emits_the_new_photograph_rule(self):
        joined = '\n'.join(on_image_text_lines(template_brief(), HEADLINE))
        self.assertIn("MUST: Keep the template's structure; " + NEW_PHOTO_RULE, joined)
        self.assertIn('vary pose, setting and hero colour treatment', joined)
        self.assertNotIn(FRAMED_LINE, joined)
        for row in COMPOSITION_ARCHETYPES:
            self.assertNotIn(opening(row), joined)

    def test_the_creative_direction_exception_demands_a_new_photograph(self):
        row = {
            'kind': 'BRAND_TEMPLATE', 'title': 'Diwali', 'role': 'PRIMARY',
            'direction': 'USE', 'focus_areas': [], 'annotation': '', 'body': '',
            'tags': [], 'signals': [],
        }
        joined = '\n'.join(_prompt_lines([row], ''))
        self.assertIn('Match its layout structure', joined)
        self.assertIn('PRODUCE A NEW PHOTOGRAPH every time', joined)
        self.assertIn("never reproduce the template's photo, model, scene or props", joined)
        self.assertNotIn('faithfully', joined)
        # Product-neutral: "styling" varies for any brand; "garment" only fits one.
        self.assertIn('setting and styling', joined)
        self.assertNotIn('garment', joined)

    def test_step_one_in_template_mode_keeps_the_words_out_and_asks_for_a_new_photo(self):
        block = GeminiGeneratorService._on_image_text_block(
            template_brief(template_image_base64='data:image/png;base64,AAAA'),
        )
        self.assertIn("template's own text slots", block)
        self.assertIn('Do NOT write the headline', block)
        self.assertNotIn(FRAMED_STEP1, block)

    def test_the_scene_seed_rides_in_both_template_and_archetype_mode(self):
        scene = SCENE_VARIANTS[2]
        for brief in (
            template_brief(scene_variant=scene['key']),
            poster_brief(scene_variant=scene['key'], composition_archetype='type_first'),
        ):
            with self.subTest(brief['creative_direction']):
                lines = on_image_text_lines(brief, HEADLINE)
                seeded = [line for line in lines if line.startswith(SCENE_LINE)]
                self.assertEqual(len(seeded), 1, lines)
                self.assertIn(scene['directive'], seeded[0])
                self.assertIn(
                    scene['directive'],
                    GeminiGeneratorService._on_image_text_block(brief),
                )
        # No seed, no scene line: an un-seeded brief reads as it always did.
        self.assertFalse(
            [line for line in on_image_text_lines(poster_brief(), HEADLINE)
             if line.startswith(SCENE_LINE)]
        )


class AmbassadorFramingTests(SimpleTestCase):
    """A poster that carries the brand ambassador never crops the face."""

    def test_without_an_ambassador_the_seed_reads_as_written(self):
        for row in SCENE_VARIANTS:
            with self.subTest(row['key']):
                directive = scene_directive(poster_brief(scene_variant=row['key']))
                self.assertEqual(directive, row['directive'])
                self.assertNotIn(FACE_VISIBLE_LINE, directive)
        self.assertEqual(scene_directive(poster_brief()), '')

    def test_an_attached_ambassador_keeps_the_face_visible_in_every_seed(self):
        face_safe_first = next(row for row in SCENE_VARIANTS if not row.get('crops_face'))
        for row in SCENE_VARIANTS:
            for brief in (
                poster_brief(scene_variant=row['key'], ambassador_image_base64=AMBASSADOR),
                template_brief(scene_variant=row['key'], ambassador_image_base64=AMBASSADOR),
            ):
                with self.subTest(key=row['key'], mode=brief['creative_direction']['mode']):
                    directive = scene_directive(brief)
                    self.assertTrue(directive.endswith(FACE_VISIBLE_LINE), directive)
                    # The close-up would crop the face: the first face-safe
                    # seed stands in for it. Every other seed is itself.
                    expected = face_safe_first if row.get('crops_face') else row
                    self.assertTrue(directive.startswith(expected['directive']), directive)
                    if row.get('crops_face'):
                        self.assertNotIn('partly in frame', directive)
                    # Both readers - the image call and Step 1 - shoot the
                    # same scene.
                    seeded = [
                        line for line in on_image_text_lines(brief, HEADLINE)
                        if line.startswith(SCENE_LINE)
                    ]
                    self.assertEqual(len(seeded), 1)
                    self.assertIn(directive, seeded[0])
                    self.assertIn(directive, GeminiGeneratorService._on_image_text_block(brief))


class RotationTests(TenantFixtureMixin, TestCase):
    """Least-recently-used per brand, deterministic, tenant-isolated."""

    def setUp(self):
        self.ws = self.make_workspace('Acme', 'c1')
        self.brand = Brand.objects.create(workspace=self.ws, name='Acme Co', is_default=True)
        self.sibling = Brand.objects.create(workspace=self.ws, name='Acme Two')
        self.other_ws = self.make_workspace('Other', 'c2')
        self.other_brand = Brand.objects.create(
            workspace=self.other_ws, name='Other Co', is_default=True,
        )
        self.clock = timezone.now() - timedelta(days=1)
        self.request_id = uuid.uuid4()

    def remember(self, brand, **trace):
        """A persisted poster carrying `trace` in its generation trace, with
        a strictly increasing created_at so recency is unambiguous."""
        item = ContentItem.objects.create(
            workspace=brand.workspace, brand=brand,
            layout_config={'generation_trace': trace},
        )
        self.clock += timedelta(minutes=1)
        ContentItem.objects.filter(pk=item.pk).update(created_at=self.clock)
        return item

    def test_with_no_history_the_pick_is_the_uuid_ring_pick(self):
        seed = self.request_id.int
        self.assertEqual(
            pick_composition_archetype(self.ws, self.brand, self.request_id),
            ARCHETYPE_KEYS[seed % len(ARCHETYPE_KEYS)],
        )
        self.assertEqual(
            pick_scene_variant(self.ws, self.brand, self.request_id),
            SCENE_KEYS[seed % len(SCENE_KEYS)],
        )

    def test_the_pick_is_deterministic_for_the_same_request_and_history(self):
        first = pick_composition_archetype(self.ws, self.brand, self.request_id)
        self.assertEqual(
            pick_composition_archetype(self.ws, self.brand, self.request_id), first,
        )
        self.remember(self.brand, composition_archetype=first)
        second = pick_composition_archetype(self.ws, self.brand, self.request_id)
        self.assertNotEqual(second, first)
        self.assertEqual(
            pick_composition_archetype(self.ws, self.brand, self.request_id), second,
        )
        # A garbage request id degrades to the seed-0 ring, never an error.
        self.assertIn(pick_composition_archetype(self.ws, self.brand, 'nope'), ARCHETYPE_KEYS)

    def test_lru_avoids_the_brands_recent_archetypes_and_cycles(self):
        picks = []
        for _ in range(16):
            key = pick_composition_archetype(self.ws, self.brand, uuid.uuid4())
            picks.append(key)
            self.remember(self.brand, composition_archetype=key)
        # The first eight picks visit every archetype once; after that every
        # window of eight consecutive posters is still all eight.
        self.assertEqual(sorted(picks[:8]), sorted(ARCHETYPE_KEYS))
        for start in range(0, 9):
            window = picks[start:start + 8]
            self.assertEqual(len(set(window)), 8, (start, picks))
        # And within the cycle, the one used longest ago comes back first.
        self.assertEqual(picks[8:16], picks[:8])

    def test_scene_variants_rotate_the_same_way(self):
        picks = []
        for _ in range(12):
            key = pick_scene_variant(self.ws, self.brand, uuid.uuid4())
            picks.append(key)
            self.remember(self.brand, scene_variant=key)
        self.assertEqual(sorted(picks[:6]), sorted(SCENE_KEYS))
        self.assertEqual(picks[6:12], picks[:6])

    def test_history_never_crosses_a_brand_or_a_workspace(self):
        baseline = pick_composition_archetype(self.ws, self.brand, self.request_id)
        # Seven of eight archetypes remembered by a sibling brand in the same
        # workspace and by a brand in another workspace ...
        for key in ARCHETYPE_KEYS:
            if key != baseline:
                self.remember(self.sibling, composition_archetype=key)
                self.remember(self.other_brand, composition_archetype=key)
        # ... and this brand's pick is unmoved.
        self.assertEqual(
            pick_composition_archetype(self.ws, self.brand, self.request_id), baseline,
        )
        # Whereas the brand that DID use those seven is pushed to the eighth.
        self.assertEqual(
            pick_composition_archetype(self.ws, self.sibling, self.request_id), baseline,
        )
        # Fill this brand's own history with everything but one and the
        # pick is forced onto the one that is left.
        for key in ARCHETYPE_KEYS:
            if key != 'diagonal_cut':
                self.remember(self.brand, composition_archetype=key)
        self.assertEqual(
            pick_composition_archetype(self.ws, self.brand, self.request_id),
            'diagonal_cut',
        )

    def test_older_rows_without_a_pick_do_not_crowd_out_the_window(self):
        for _ in range(10):
            self.remember(self.brand, brain_version='v1')
        for key in ARCHETYPE_KEYS[:7]:
            self.remember(self.brand, composition_archetype=key)
        self.assertEqual(
            pick_composition_archetype(self.ws, self.brand, self.request_id),
            ARCHETYPE_KEYS[7],
        )

    def test_a_history_read_failure_degrades_to_the_ring_pick(self):
        with patch(
            'apps.content.models.ContentItem.objects.filter',
            side_effect=RuntimeError('db away'),
        ):
            self.assertEqual(
                pick_composition_archetype(self.ws, self.brand, self.request_id),
                ARCHETYPE_KEYS[self.request_id.int % len(ARCHETYPE_KEYS)],
            )

    def test_a_missing_brand_gets_the_stateless_ring_pick(self):
        self.assertEqual(
            pick_composition_archetype(self.ws, None, self.request_id),
            ARCHETYPE_KEYS[self.request_id.int % len(ARCHETYPE_KEYS)],
        )

    def test_a_face_safe_pick_never_draws_the_close_up(self):
        picks = []
        for _ in range(10):
            key = pick_scene_variant(self.ws, self.brand, uuid.uuid4(), face_safe=True)
            picks.append(key)
            self.remember(self.brand, scene_variant=key)
        self.assertNotIn(CLOSE_UP, picks)
        self.assertEqual(sorted(picks[:5]), sorted(FACE_SAFE_KEYS))
        self.assertEqual(picks[5:10], picks[:5])
        # A close-up in the history is simply not an option, never an error.
        self.remember(self.brand, scene_variant=CLOSE_UP)
        self.assertIn(
            pick_scene_variant(self.ws, self.brand, self.request_id, face_safe=True),
            FACE_SAFE_KEYS,
        )

    def test_both_picks_come_from_one_history_read(self):
        from apps.context.services import creative_direction as module

        self.remember(
            self.brand, composition_archetype='diagonal_cut', scene_variant='street_golden_hour',
        )
        with patch.object(
            module, '_recent_variety_keys', wraps=module._recent_variety_keys,
        ) as reads:
            picks = pick_variety(self.ws, self.brand, self.request_id)
        self.assertEqual(reads.call_count, 1)
        self.assertEqual(set(picks), {'composition_archetype', 'scene_variant'})
        self.assertNotEqual(picks['composition_archetype'], 'diagonal_cut')
        self.assertNotEqual(picks['scene_variant'], 'street_golden_hour')
        # The one read carries both fields, each over its own window.
        self.assertEqual(
            _recent_variety_keys(self.ws, self.brand),
            {'composition_archetype': ['diagonal_cut'], 'scene_variant': ['street_golden_hour']},
        )


class VarietyInTheGenerationTests(TenantFixtureMixin, TestCase):
    """The picks ride in both briefs and land in the trace the next pick reads."""

    def setUp(self):
        self.ws = self.make_workspace('Acme', 'c1')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Acme Co', is_default=True, cta_keyword='MORE INFO',
        )

    def generate(self, **overrides):
        extra = {
            'contentType': 'poster', 'offer': '30% off',
            'creative_direction': {'mode': 'AI_ORIGINAL', 'selections': []},
            'request_id': str(uuid.uuid4()),
        }
        extra.update(overrides)
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', recording_router(calls)):
            outcome = generate_copy_and_image(self.ws, self.brand, extra, instruction='Launch')
        return outcome, calls

    def test_the_picks_reach_both_briefs_and_the_trace(self):
        outcome, calls = self.generate()
        trace = outcome['trace']
        archetype = trace['composition_archetype']
        scene = trace['scene_variant']
        self.assertIn(archetype, ARCHETYPE_KEYS)
        self.assertIn(scene, SCENE_KEYS)
        text_brief, image_brief = calls[0]['brief'], calls[1]['brief']
        self.assertEqual(text_brief['composition_archetype'], archetype)
        self.assertEqual(image_brief['composition_archetype'], archetype)
        self.assertEqual(text_brief['scene_variant'], scene)
        image_lines = '\n'.join(image_brief['brand_context'])
        self.assertIn(opening(composition_archetype(archetype)), image_lines)
        self.assertIn(SCENE_LINE, image_lines)
        for row in COMPOSITION_ARCHETYPES:
            if row['key'] != archetype:
                self.assertNotIn(opening(row), image_lines)

    def test_a_stored_trace_steers_the_next_generation_away(self):
        first, _ = self.generate()
        ContentItem.objects.create(
            workspace=self.ws, brand=self.brand,
            layout_config={'generation_trace': first['trace']},
        )
        second, calls = self.generate()
        self.assertNotEqual(
            second['trace']['composition_archetype'], first['trace']['composition_archetype'],
        )
        self.assertNotEqual(second['trace']['scene_variant'], first['trace']['scene_variant'])
        self.assertNotIn(
            opening(composition_archetype(first['trace']['composition_archetype'])),
            '\n'.join(calls[1]['brief']['brand_context']),
        )

    def test_a_caller_fixed_pick_is_kept(self):
        outcome, calls = self.generate(composition_archetype='polaroid_card')
        self.assertEqual(outcome['trace']['composition_archetype'], 'polaroid_card')
        self.assertIn(
            opening(composition_archetype('polaroid_card')),
            '\n'.join(calls[1]['brief']['brand_context']),
        )

    def test_a_brand_template_seeds_a_scene_but_owns_its_own_layout(self):
        outcome, calls = self.generate(creative_direction={
            'mode': 'REFERENCE',
            'selections': [{'kind': 'BRAND_TEMPLATE', 'title': 'Diwali', 'direction': 'USE'}],
        })
        trace = outcome['trace']
        self.assertIn(trace['scene_variant'], SCENE_KEYS)
        self.assertNotIn('composition_archetype', trace)
        image_lines = '\n'.join(calls[1]['brief']['brand_context'])
        self.assertIn(NEW_PHOTO_RULE, image_lines)
        self.assertIn(SCENE_LINE, image_lines)
        self.assertNotIn(FRAMED_LINE, image_lines)

    def test_no_variety_where_the_compose_engine_owns_the_words(self):
        outcome, calls = self.generate(
            creative_direction={'mode': 'CATALOG_TEMPLATE', 'layout': 'x'},
        )
        self.assertNotIn('composition_archetype', outcome['trace'])
        self.assertNotIn('scene_variant', outcome['trace'])
        self.assertNotIn('composition_archetype', calls[1]['brief'])

    def test_one_generation_reads_the_brand_history_once(self):
        from apps.context.services import creative_direction as module

        with patch.object(
            module, '_recent_variety_keys', wraps=module._recent_variety_keys,
        ) as reads:
            outcome, _ = self.generate()
        self.assertEqual(reads.call_count, 1)
        self.assertIn(outcome['trace']['composition_archetype'], ARCHETYPE_KEYS)
        self.assertIn(outcome['trace']['scene_variant'], SCENE_KEYS)
        # With every key fixed by the caller there is nothing to read.
        with patch.object(
            module, '_recent_variety_keys', wraps=module._recent_variety_keys,
        ) as reads:
            self.generate(composition_archetype='polaroid_card', scene_variant=CLOSE_UP)
        self.assertEqual(reads.call_count, 0)

    def test_an_attached_ambassador_gets_a_face_safe_seed_and_keeps_the_face(self):
        # Even with every face-safe seed just used, the close-up is never
        # the answer for a poster that carries the ambassador.
        for key in FACE_SAFE_KEYS:
            ContentItem.objects.create(
                workspace=self.ws, brand=self.brand,
                layout_config={'generation_trace': {'scene_variant': key}},
            )
        with patch(
            'apps.context.services.generation._ambassador_image', return_value=AMBASSADOR,
        ):
            outcome, calls = self.generate()
        scene = outcome['trace']['scene_variant']
        self.assertIn(scene, FACE_SAFE_KEYS)
        text_brief, image_brief = calls[0]['brief'], calls[1]['brief']
        self.assertEqual(text_brief['ambassador_image_base64'], AMBASSADOR)
        self.assertEqual(image_brief['scene_variant'], scene)
        image_lines = '\n'.join(image_brief['brand_context'])
        self.assertIn(FACE_VISIBLE_LINE, image_lines)
        self.assertNotIn('partly in frame', image_lines)
        # Without the ambassador the same history sends the close-up out.
        outcome, calls = self.generate()
        self.assertEqual(outcome['trace']['scene_variant'], CLOSE_UP)
        self.assertNotIn(FACE_VISIBLE_LINE, '\n'.join(calls[1]['brief']['brand_context']))

    def test_retry_image_hands_its_picks_to_the_caller(self):
        calls = []
        trace = {}
        with patch('apps.ai.router.AIRouter.dispatch', recording_router(calls)):
            retry_image(
                self.ws, self.brand,
                {'contentType': 'poster', 'headline': HEADLINE, 'request_id': str(uuid.uuid4())},
                instruction='Launch', trace=trace,
            )
        self.assertIn(trace['composition_archetype'], ARCHETYPE_KEYS)
        self.assertIn(trace['scene_variant'], SCENE_KEYS)
        self.assertEqual(calls[0]['brief']['composition_archetype'], trace['composition_archetype'])
        self.assertEqual(calls[0]['brief']['scene_variant'], trace['scene_variant'])
        # Fixed by the caller - a repair of a saved draft - the picks are
        # kept, and reported back as exactly those.
        trace = {}
        with patch('apps.ai.router.AIRouter.dispatch', recording_router(calls)):
            retry_image(
                self.ws, self.brand,
                {
                    'contentType': 'poster', 'headline': HEADLINE,
                    'composition_archetype': 'diagonal_cut', 'scene_variant': CLOSE_UP,
                },
                trace=trace,
            )
        # (`image_text`, the words-on-the-picture check's own record, rides
        # in the same trace - see test_image_text_gate.)
        self.assertEqual(
            {key: trace[key] for key in ('composition_archetype', 'scene_variant')},
            {'composition_archetype': 'diagonal_cut', 'scene_variant': CLOSE_UP},
        )
        self.assertIn(
            opening(composition_archetype('diagonal_cut')),
            '\n'.join(calls[1]['brief']['brand_context']),
        )
