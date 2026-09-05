"""
The image text check: what the poster says, judged against the copy.

The judge is pure and pinned rule by rule, including the live failure that
motivated it. The dispatching wrapper is proven against a patched router —
no provider is ever called — for the brief it sends and for the one
property it must never lose: nothing that goes wrong turns into an
exception, only into a 'skipped' verdict.
"""
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from PIL import Image

from apps.ai.models import Capability
from apps.ai.router import NoProviderAvailable
from apps.common.testing import TenantFixtureMixin
from apps.context.services import image_text
from apps.context.services.image_text import (
    INSTRUCTION,
    TEXT_SCHEMA,
    VERDICTS,
    check_image_text,
    judge_texts,
)
from apps.universal.services import set_client_quality

DISPATCH = 'apps.ai.router.AIRouter.dispatch'
HEADLINE = 'Woven For Celebrations.'
STRAPLINE = "Sumaya's exclusive offer - limited edition pieces"
LIVE_HEADLINE = 'WOVEN FOR CELEBRATIONS: KANJIVARAM UNVEILED!'


def tiny_png_base64():
    buffer = io.BytesIO()
    Image.new('RGB', (12, 12), 'white').save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode()


class JudgeTests(SimpleTestCase):
    def verdict(self, found, headline=HEADLINE, **kwargs):
        verdict, reason = judge_texts(found, headline, **kwargs)
        self.assertIn(verdict, VERDICTS)
        self.assertTrue(reason)
        return verdict

    def test_the_live_failure_is_an_altered_headline(self):
        # Sumaya, revision 5159e3bf: the image model glued a subtitle onto
        # the headline and invented a strapline. The glued words win over
        # the strapline because a wrong headline is what the re-buy is for.
        self.assertEqual(
            self.verdict([LIVE_HEADLINE, STRAPLINE], brand_name='Sumaya'),
            'headline_altered',
        )

    def test_exact_headline_is_ok(self):
        self.assertEqual(self.verdict(['Woven For Celebrations.']), 'ok')

    def test_headline_split_across_two_fragments_is_ok(self):
        self.assertEqual(self.verdict(['Woven For', 'Celebrations.']), 'ok')

    def test_casing_and_punctuation_are_ignored(self):
        self.assertEqual(self.verdict(['WOVEN, FOR — "CELEBRATIONS"!']), 'ok')
        self.assertEqual(self.verdict(["sumaya's picks"], "Sumaya’s Picks"), 'ok')

    def test_no_text_or_unrelated_text_is_missing(self):
        self.assertEqual(self.verdict([]), 'headline_missing')
        self.assertEqual(self.verdict(['Festive silks', 'Shop now']), 'headline_missing')

    def test_missing_beats_extra_text(self):
        self.assertEqual(self.verdict([STRAPLINE]), 'headline_missing')

    def test_partial_headline_is_altered(self):
        # Two of three words present, but not the whole.
        self.assertEqual(self.verdict(['Woven For Kanjivaram']), 'headline_altered')
        # Every word present, order broken.
        self.assertEqual(self.verdict(['Celebrations Woven For']), 'headline_altered')

    def test_a_short_stray_fragment_is_tolerated(self):
        self.assertEqual(
            self.verdict(['Woven For Celebrations', 'New', '2026', 'Size XL']), 'ok',
        )

    def test_a_three_word_stray_fragment_is_extra_text(self):
        self.assertEqual(
            self.verdict(['Woven For Celebrations', STRAPLINE]), 'extra_text',
        )
        _verdict, reason = judge_texts(['Woven For Celebrations', STRAPLINE], HEADLINE)
        self.assertIn(STRAPLINE, reason)

    def test_cta_offer_and_brand_fragments_are_allowed(self):
        self.assertEqual(
            self.verdict(
                ['Sumaya', 'Woven For Celebrations', 'Shop the collection',
                 'Flat 20% off this week'],
                cta='Shop the collection', offer='Flat 20% off this week',
                brand_name='Sumaya',
            ),
            'ok',
        )

    def test_allowed_text_matches_either_way_round(self):
        # A fragment inside an allowed text is accounted for; an allowed
        # text inside a fragment leaves only the rest ("today") to judge,
        # and one word of its own is tolerated like any other short stray.
        self.assertEqual(
            self.verdict(['Woven For Celebrations', 'Shop the new'],
                         cta='Shop the new collection now'),
            'ok',
        )
        self.assertEqual(
            self.verdict(['Woven For Celebrations', 'Shop the collection today'],
                         cta='Shop the collection'),
            'ok',
        )

    def test_approved_copy_glued_to_the_headline_is_not_an_alteration(self):
        # The CTA sharing the headline's block is a layout choice, not a
        # text fault; anything else glued on still is.
        self.assertEqual(
            self.verdict(['Woven For Celebrations Shop now'], cta='Shop now'), 'ok',
        )
        self.assertEqual(
            self.verdict(['Woven For Celebrations Shop now']), 'headline_altered',
        )

    def test_approved_copy_inside_the_headline_block_excuses_nothing_around_it(self):
        # Reviewer probes: an allowed text sitting INSIDE the glued block
        # used to account for the whole block. The headline's block must be
        # exactly the headline plus approved copy.
        self.assertEqual(
            self.verdict(['WOVEN FOR CELEBRATIONS: KANJIVARAM UNVEILED! SHOP NOW'],
                         cta='Shop now'),
            'headline_altered',
        )
        self.assertEqual(
            self.verdict(
                ['Woven For Celebrations Shop the collection now - Diwali sale ends Sunday'],
                cta='Shop the collection now',
            ),
            'headline_altered',
        )
        self.assertEqual(
            self.verdict(['Woven For Celebrations by Sumaya the house of silk'],
                         brand_name='Sumaya'),
            'headline_altered',
        )
        # Even one unapproved word in the headline's own block is an
        # alteration; the same word approved as the brand is not.
        self.assertEqual(self.verdict(['Woven For Celebrations Sumaya']), 'headline_altered')
        self.assertEqual(
            self.verdict(['Woven For Celebrations Sumaya'], brand_name='Sumaya'), 'ok',
        )

    def test_every_approved_text_is_taken_out_longest_first(self):
        # The brand name inside the offer must not eat the offer's middle
        # before the offer itself is taken out.
        self.assertEqual(
            self.verdict(['Woven For Celebrations Sumaya exclusive offer', 'Sumaya'],
                         offer='Sumaya exclusive offer', brand_name='Sumaya'),
            'ok',
        )

    def test_the_headline_read_twice_is_ok(self):
        # Reviewer probe: a doubled read is the reader's doing, not a rewrite.
        self.assertEqual(
            self.verdict(['Woven For Celebrations Woven For Celebrations']), 'ok',
        )

    def test_a_percent_sign_the_reader_dropped_is_not_an_alteration(self):
        # Reviewer probe: '%' is stripped on both sides.
        self.assertEqual(self.verdict(['Flat 50 Off'], 'Flat 50% Off'), 'ok')
        self.assertEqual(self.verdict(['Flat 50% Off'], 'Flat 50 Off'), 'ok')
        self.assertEqual(
            self.verdict(['Woven For Celebrations', 'Flat 50 Off'], offer='Flat 50% Off'),
            'ok',
        )

    def test_a_price_website_date_or_hashtag_row_is_decoration(self):
        # Reviewer probes: each read as three "words" once punctuation became
        # spaces, and each cost a re-buy that painted the same badge again.
        for badge in ('Rs. 4,999', 'www.sumaya.in', '15 - 20 Oct', '#sumaya #silk #festive'):
            self.assertEqual(self.verdict(['Woven For Celebrations', badge]), 'ok', badge)

    def test_stray_text_is_counted_in_alphabetic_words(self):
        # "Ends 20 Oct" has two words; "Sale ends 20 Oct" has three.
        self.assertEqual(self.verdict(['Woven For Celebrations', 'Ends 20 Oct']), 'ok')
        self.assertEqual(
            self.verdict(['Woven For Celebrations', 'Sale ends 20 Oct']), 'extra_text',
        )

    def test_a_link_or_handle_is_decoration_with_a_short_caption(self):
        # A website or handle is dressing, and so is the word or two beside
        # it; a row of hashtags is not a licence for the copy in front.
        self.assertEqual(self.verdict(['Woven For Celebrations', 'Visit www.sumaya.in']), 'ok')
        self.assertEqual(
            self.verdict(['Woven For Celebrations', 'Follow us @sumaya.silks']), 'ok',
        )
        self.assertEqual(
            self.verdict(['Woven For Celebrations', 'Shop now today #sumaya #silk']),
            'extra_text',
        )

    def test_a_link_or_handle_excuses_only_itself(self):
        # Reviewer probes: each row was tolerated whole because a website or
        # a handle sat somewhere on it. The dressing tokens are dropped and
        # what is left is judged like any other row.
        for row in (
            'Diwali sale ends Sunday, visit www.sumaya.in',
            'Celebrate the season with us @sumaya',
            'Every saree hand woven by master weavers sumaya.com',
        ):
            self.assertEqual(self.verdict(['Woven For Celebrations', row]), 'extra_text', row)
        # A row that is nothing but dressing is still free.
        self.assertEqual(
            self.verdict(['Woven For Celebrations', 'www.sumaya.in @sumaya #silk']), 'ok',
        )
        # Three words of caption beside the link are a line of text: this
        # is where the same rule draws its line.
        self.assertEqual(
            self.verdict(['Woven For Celebrations', 'Visit us at www.sumaya.in']), 'extra_text',
        )

    def test_approved_copy_inside_a_stray_block_excuses_only_itself(self):
        # The same hole on the stray path: the CTA inside a longer block
        # accounts for the CTA, and what is left is judged on its own.
        self.assertEqual(
            self.verdict(
                ['Woven For Celebrations', 'Shop the collection now - Diwali sale ends Sunday'],
                cta='Shop the collection now',
            ),
            'extra_text',
        )

    def test_a_clean_headline_block_wins_over_a_row_that_repeats_its_words(self):
        # Reviewer probes: the headline IS painted right on its own block;
        # the row that borrows its words is a stray, judged by the stray
        # rule, never an alteration of the headline.
        self.assertEqual(
            self.verdict(['SALE', 'Shop the sale now'], 'Sale', cta='Shop now'), 'extra_text',
        )
        verdict, reason = judge_texts(
            ['Diwali Sale', 'Free shipping on all Diwali Sale orders'], 'Diwali Sale',
            brand_name='Sumaya',
        )
        self.assertEqual(verdict, 'extra_text')
        self.assertIn('Free shipping on all Diwali Sale orders', reason)
        # A short enough stray leaves the poster simply fine.
        self.assertEqual(self.verdict(['Sale', 'Sale ends Sunday'], 'Sale'), 'ok')
        # With no clean block anywhere, the glued one is the altered headline.
        self.assertEqual(
            self.verdict(['Free shipping on all Diwali Sale orders'], 'Diwali Sale'),
            'headline_altered',
        )

    def test_a_slash_bar_or_bullet_between_words_is_a_space(self):
        # Reviewer probes: the separators a poster sets between words.
        for read in ('Woven/For/Celebrations', 'Woven | For | Celebrations',
                     'Woven • For · Celebrations'):
            self.assertEqual(self.verdict([read]), 'ok', read)

    def test_an_ampersand_reads_as_and_either_way_round(self):
        # Reviewer probe: '&' and "and" are the same word on both sides.
        self.assertEqual(self.verdict(['Silk and Gold'], 'Silk & Gold'), 'ok')
        self.assertEqual(self.verdict(['Silk & Gold'], 'Silk and Gold'), 'ok')

    def test_whole_words_only(self):
        # "new" inside "renewal" is not the word "new".
        self.assertEqual(self.verdict(['Renewal Season Sale'], 'New'), 'headline_missing')

    def test_no_headline_is_skipped(self):
        self.assertEqual(self.verdict(['Anything'], ''), 'skipped')
        self.assertEqual(self.verdict(['Anything'], '...'), 'skipped')


class CheckImageTextTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Sumaya', 'sumaya-image-text')
        self.image = {
            'image_url': 'https://storage.test/generated/poster.png',
            'image_base64': tiny_png_base64(),
            'mime_type': 'image/png',
            'provider': 'openai',
        }

    def check(self, **kwargs):
        kwargs.setdefault('headline', HEADLINE)
        return check_image_text(self.workspace, self.image, **kwargs)

    def test_dispatch_shape_and_a_parsed_answer(self):
        with patch(DISPATCH, return_value={
            'analysis': {'texts': [' Woven For ', 'Celebrations.', 'Sumaya']},
            'provider': 'openai',
        }) as dispatch:
            result = self.check(brand_name='Sumaya')

        self.assertEqual(result['verdict'], 'ok')
        self.assertEqual(result['found'], ['Woven For', 'Celebrations.', 'Sumaya'])
        self.assertEqual(result['expected'], HEADLINE)
        self.assertEqual(set(result), {'verdict', 'found', 'expected', 'reason'})

        dispatch.assert_called_once()
        args, kwargs = dispatch.call_args
        self.assertEqual(args[0], Capability.IMAGE_ANALYSIS)
        brief = args[1]
        self.assertEqual(brief['task'], 'IMAGE_TEXT_AUDIT')
        self.assertEqual(brief['instruction'], INSTRUCTION)
        self.assertIs(brief['response_schema'], TEXT_SCHEMA)
        self.assertTrue(brief['reference_image_base64'].startswith('data:image/jpeg;base64,'))
        self.assertIs(kwargs.get('internal'), True)

    def test_a_json_string_answer_is_parsed_and_judged(self):
        with patch(DISPATCH, return_value={
            'raw': json.dumps({'texts': [LIVE_HEADLINE, STRAPLINE]}),
        }):
            result = self.check(brand_name='Sumaya')
        self.assertEqual(result['verdict'], 'headline_altered')
        self.assertEqual(result['found'], [LIVE_HEADLINE, STRAPLINE])
        self.assertIn(LIVE_HEADLINE, result['reason'])

    def test_a_durable_url_is_fetched_through_the_trusted_door(self):
        self.image['image_base64'] = ''
        with patch(
            'apps.layouts.images.from_trusted_url',
            return_value=Image.new('RGB', (2000, 3000), 'white'),
        ) as fetch, patch(DISPATCH, return_value={'analysis': {'texts': [HEADLINE]}}) as dispatch:
            result = self.check()
        self.assertEqual(result['verdict'], 'ok')
        fetch.assert_called_once_with('https://storage.test/generated/poster.png')
        # The copy sent for reading is downscaled, never the 6-megapixel original.
        sent = dispatch.call_args.args[1]['reference_image_base64']
        self.assertLess(len(sent), 200_000)

    def test_an_unreadable_image_skips_without_a_dispatch(self):
        self.image['image_base64'] = ''
        with patch('apps.layouts.images.from_trusted_url', return_value=None), \
                patch(DISPATCH) as dispatch:
            result = self.check()
        self.assertEqual(result['verdict'], 'skipped')
        self.assertEqual(result['found'], [])
        self.assertIn('could not be read', result['reason'])
        dispatch.assert_not_called()

    def test_no_provider_skips(self):
        with patch(DISPATCH, side_effect=NoProviderAvailable('none routed')):
            result = self.check()
        self.assertEqual(result['verdict'], 'skipped')
        self.assertIn('NoProviderAvailable', result['reason'])
        self.assertEqual(result['expected'], HEADLINE)

    def test_a_provider_error_skips(self):
        with patch(DISPATCH, side_effect=RuntimeError('boom')):
            result = self.check()
        self.assertEqual(result['verdict'], 'skipped')
        self.assertIn('RuntimeError', result['reason'])

    def test_a_malformed_answer_skips(self):
        for answer in ({'analysis': {'nope': 1}}, {'raw': 'not json'}, {'analysis': {'texts': 'x'}}):
            with patch(DISPATCH, return_value=answer):
                result = self.check()
            self.assertEqual(result['verdict'], 'skipped', answer)

    def test_an_empty_headline_skips_without_a_dispatch(self):
        with patch(DISPATCH) as dispatch:
            for headline in ('', '   ', None, '!!!'):
                result = self.check(headline=headline)
                self.assertEqual(result['verdict'], 'skipped', headline)
        dispatch.assert_not_called()

    def test_the_toggle_off_skips_without_a_dispatch(self):
        set_client_quality(self.workspace, image_text_check_enabled=False)
        with patch(DISPATCH) as dispatch:
            result = self.check()
        self.assertEqual(result['verdict'], 'skipped')
        self.assertIn('off', result['reason'])
        dispatch.assert_not_called()

    def test_a_missing_headline_verdict_carries_what_was_read(self):
        with patch(DISPATCH, return_value={'analysis': {'texts': ['Festive silks']}}):
            result = self.check()
        self.assertEqual(result['verdict'], 'headline_missing')
        self.assertEqual(result['found'], ['Festive silks'])
        self.assertIn('Festive silks', result['reason'])


class AdapterRoutingTests(SimpleTestCase):
    """IMAGE_TEXT_AUDIT takes the same structured-schema path SUBJECT_FOCUS
    does in both vision adapters, so the schema is honoured and the answer
    is never the generic campaign-analysis shape."""

    BRIEF = {
        'task': 'IMAGE_TEXT_AUDIT',
        'instruction': INSTRUCTION,
        'response_schema': TEXT_SCHEMA,
        'reference_image_base64': 'data:image/jpeg;base64,AAAA',
    }

    def test_openai_registers_the_audit_schema(self):
        from apps.ai.adapters.openai import OpenAIAdapter

        with patch.object(
            OpenAIAdapter, '_responses_json',
            return_value=({'texts': ['Woven For Celebrations']}, {'id': 'resp_1'}),
        ) as responses:
            result = OpenAIAdapter(credentials='workspace-test-key').analyze_image(
                dict(self.BRIEF)
            )
        self.assertEqual(result['analysis'], {'texts': ['Woven For Celebrations']})
        kwargs = responses.call_args.kwargs
        self.assertEqual(kwargs['schema_name'], 'scaleezy_image_text_audit')
        self.assertIs(kwargs['schema'], TEXT_SCHEMA)
        self.assertEqual(kwargs['prompt'], INSTRUCTION)

    def test_gemini_takes_the_structured_path(self):
        from apps.ai.adapters.gemini import GeminiAdapter

        calls = {}

        class Stub:
            TEXT_MODEL = 'gemini-test'

            @staticmethod
            def _parse_base64_image(b64):
                return 'image/jpeg', b'img-bytes'

            @staticmethod
            def _get_client(credentials):
                def generate_content(**kwargs):
                    calls['kwargs'] = kwargs
                    return SimpleNamespace(text=json.dumps({'texts': []}))
                return SimpleNamespace(
                    models=SimpleNamespace(generate_content=generate_content)
                )

            @staticmethod
            def analyze_reference_image(b64, api_key=''):
                calls['legacy'] = True
                return {'legacy': True}

        with patch.object(GeminiAdapter, '_service', lambda adapter: Stub):
            result = GeminiAdapter().analyze_image(dict(self.BRIEF))
        # An empty transcript (a poster with no text) is a valid answer.
        self.assertEqual(result['analysis'], {'texts': []})
        self.assertNotIn('legacy', calls)
        self.assertIn('config', calls['kwargs'])
        self.assertEqual(calls['kwargs']['contents'][0], INSTRUCTION)

    def test_the_module_never_imports_the_router_at_load_time(self):
        # Mirrors focus.py: the router is imported inside the call so the
        # module stays importable from generation.py without a cycle.
        self.assertFalse(hasattr(image_text, 'AIRouter'))
