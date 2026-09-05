"""
Fields typed into the studio's free-text brief count exactly like chips.

Live, "Instagram poster for the new Kanjivaram silk saree collection.
Headline: Woven For Celebrations. Offer: 20% off launch week. CTA: Shop the
collection." was typed with the offer chip left empty: the poster carried no
offer at all (the on-image offer line reads only `brief['offer']`) and the
copy judge rewrote the typed headline. These tests pin:

  * the parser (`apps.context.services.brief_fields`): the label vocabulary,
    the matching rule - a label counts at the start of the text, after a
    newline, or after sentence punctuation or an opening bracket, and after
    a space when it is Capitalised and followed by ':' - the value rule (to
    the next label, a newline or the end; a matching pair of quotes and one
    trailing '.' stripped; 200 chars) and `plain_brief`; the parity rules
    the studio mirrors (`test_parity_*`) one by one; the endpoint's
    line-keeping normalisation feeding the parser one field per line;
  * `with_brief_fields`: a typed CTA outside the brand's approved keywords
    is dropped and reported as `cta_ignored`; a brief it read is marked and
    never read twice; a chip's typed alternative stays in the text; so does
    a key the studio's user dismissed from auto-fill
    (`brief_fields_dismissed`, reported as `dismissed`); only the occurrence
    a key was read from leaves the text; an only-fields brief leaves no
    "User creation request" line behind;
  * the one parse point in `generate_marketing_payload`: a typed offer
    reaches the IMAGE brief's on-image offer line and the trace
    (`layout_config.generation_trace['brief_fields']`); a selected chip wins
    over a typed value; a typed headline is a MUST line in the TEXT brief
    (the judge's rewrite included) and reaches the critique judge as
    `requested_headline`; a typed CTA is the on-image call-to-action when
    the brand's law allows it, and then the law's DM-keyword demand stands
    down for it - in the prompt line, the copy check and the judge - so no
    rewrite is spent on a keyword the caption does not owe;
  * the worker's shape (instruction=brief['instruction']) and the
    synchronous endpoint's shape (instruction=campaign name) both parse;
    `retry_image` on a stored brief carries the typed fields; a reviewer's
    request-edits verdict is never mined for labels;
  * persistence: a typed-only offer lands in `ContentItem.cta` (the offer
    column) on the worker path and the synchronous one - each persists the
    brief it passed in, so it is read back from the trace - and rides into
    a request-edits regeneration; both endpoints carry the studio's
    dismissed keys, validated against the vocabulary.

The router is a recording stand-in: no provider is ever called.
"""
import copy
import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.ai.models import Capability
from apps.ai.router import NoProviderAvailable
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.content.models import ContentItem
from apps.context.services.brief_fields import (
    LABELS,
    MAX_DISMISSED,
    MAX_VALUE_CHARS,
    PARSED_MARKER,
    dismissed_brief_fields,
    extract_brief_fields,
    plain_brief,
    stored_offer,
    with_brief_fields,
)
from apps.context.services.generation import generate_marketing_payload, retry_image
from apps.gemini.models import GeminiGenerationRequest
from apps.workspaces.models import WorkspaceMember

DISPATCH = 'apps.ai.router.AIRouter.dispatch'
GENERATE_URL = '/api/marketing/gemini/generate/'
GENERATE_ASYNC_URL = '/api/marketing/gemini/generate-async/'
#: The finished picture's text check would fetch the (fake) image first;
#: it is not under test here, so it reads as skipped.
CHECKER = 'apps.context.services.image_text.check_image_text'
SKIPPED = {'verdict': 'skipped', 'found': [], 'expected': '', 'reason': 'not under test'}

LIVE = (
    'Instagram poster for the new Kanjivaram silk saree collection. '
    'Headline: Woven For Celebrations. Offer: 20% off launch week. '
    'CTA: Shop the collection.'
)
LIVE_FIELDS = {
    'requested_headline': 'Woven For Celebrations',
    'offer': '20% off launch week',
    'cta': 'Shop the collection',
}
LIVE_PLAIN = 'Instagram poster for the new Kanjivaram silk saree collection.'
#: LIVE with the offer chip selected: the typed offer lost to the chip, so
#: its segment stays in the text for the copy model to read.
LIVE_KEPT_OFFER = (
    'Instagram poster for the new Kanjivaram silk saree collection. '
    'Offer: 20% off launch week.'
)
REQUEST_PREFIX = (
    'User creation request (subordinate to Scaleezy policy and Brand Brain rules): '
)
HEADLINE_MUST = (
    'MUST: Use this exact headline, word for word: "Woven For Celebrations". '
    'Do not rewrite it for tone.'
)

#: A stable https URL: persistence leaves it alone, so no storage is touched.
IMAGE = {
    'image_url': 'https://cdn.example.com/poster.png',
    'provider': 'STABILITY', 'provider_name': 'Stability', 'latency_ms': 20,
}
COPY = {
    'headline': 'Woven For Celebrations', 'caption': 'Silk for the season.',
    'hashtags': '#silk', 'raw': {}, 'provider': 'OPENAI',
    'provider_name': 'OpenAI', 'latency_ms': 10,
}
JUDGE_PASS = {'passes': True, 'violations': [], 'rewrite_instruction': ''}
JUDGE_FAIL = {
    'passes': False,
    'violations': [{
        'rule': 'MUST: never promise a delivery date', 'element': 'caption',
        'severity': 'HARD', 'fix': 'Drop the promise.',
    }],
    'rewrite_instruction': 'Drop the delivery promise.',
}


class Router:
    """TEXT answers with `COPY`; the copy judge (an EXTRACT dispatch on the
    critique schema) from `verdicts` in order, the last one repeating; IMAGE
    with `IMAGE`; anything else is unrouted, so the image-text check skips
    itself. Records every dispatch."""

    def __init__(self, verdicts=(JUDGE_PASS,)):
        self.verdicts = list(verdicts)
        self.calls = []

    def dispatch(self, capability, brief, content_item_id=None, *, internal=False):
        self.calls.append({'capability': capability, 'brief': brief, 'internal': internal})
        if capability == Capability.IMAGE:
            return dict(IMAGE)
        if capability == Capability.TEXT:
            if brief.get('schema_name') == 'scaleezy_copy_critique':
                verdict = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
                return {'raw': copy.deepcopy(verdict)}
            if str(brief.get('task') or '').upper() == 'EXTRACT':
                raise NoProviderAvailable('No provider routed for extraction.')
            return copy.deepcopy(COPY)
        raise NoProviderAvailable(f'No provider routed for {capability}.')

    def text_briefs(self):
        """The copy generator's briefs - the first draft and any rewrite."""
        return [
            call['brief'] for call in self.calls
            if call['capability'] == Capability.TEXT
            and str(call['brief'].get('task') or '').upper() != 'EXTRACT'
        ]

    def judge_inputs(self):
        return [
            call['brief']['structured'] for call in self.calls
            if call['brief'].get('schema_name') == 'scaleezy_copy_critique'
        ]

    def image_briefs(self):
        return [call['brief'] for call in self.calls if call['capability'] == Capability.IMAGE]

    @contextmanager
    def patched(self):
        stand_in = self

        def dispatch(_router, capability, brief, content_item_id=None, *, internal=False):
            return stand_in.dispatch(capability, brief, content_item_id, internal=internal)

        with patch(DISPATCH, dispatch), patch(CHECKER, return_value=dict(SKIPPED)):
            yield


def studio_brief(instruction=LIVE, **overrides):
    """The brief the studio queues: chips empty, the typed text under
    `instruction` and quoted in the creative direction's request line, as
    the view resolves it before the worker runs."""
    brief = {
        'campaign_name': 'Kanjivaram launch', 'product': '', 'target_audience': '',
        'location': '', 'occasion': '', 'offer': '', 'brand_tone': '',
        'instruction': instruction, 'contentType': 'poster', 'slides': [],
        'creative_direction': {
            'mode': 'AI_ORIGINAL', 'selection_count': 0, 'layout': '',
            'selections': [], 'instructions': [REQUEST_PREFIX + instruction],
        },
        'request_id': str(uuid.uuid4()),
    }
    brief.update(overrides)
    return brief


def lines_with(brief, fragment):
    return [line for line in brief.get('brand_context') or [] if fragment in str(line)]


class BriefFieldParserTests(SimpleTestCase):
    def test_the_live_brief_yields_exactly_its_three_fields(self):
        self.assertEqual(extract_brief_fields(LIVE), LIVE_FIELDS)

    def test_fields_on_their_own_lines(self):
        text = 'Poster for sarees\nHeadline: Woven\nOffer: 20% off\nCTA: Shop'
        self.assertEqual(extract_brief_fields(text), {
            'requested_headline': 'Woven', 'offer': '20% off', 'cta': 'Shop',
        })

    def test_labels_are_case_insensitive(self):
        self.assertEqual(
            extract_brief_fields('offer: 10% off. cta: buy now'),
            {'offer': '10% off', 'cta': 'buy now'},
        )

    def test_dash_and_equals_separators(self):
        self.assertEqual(extract_brief_fields('Deal - buy 1 get 1'), {'offer': 'buy 1 get 1'})
        self.assertEqual(
            extract_brief_fields('Tone = warm; Where: Chennai'),
            {'brand_tone': 'warm', 'location': 'Chennai'},
        )

    def test_a_label_inside_prose_is_not_a_field(self):
        # A label counts only at the start, after a newline, or after
        # sentence punctuation or an opening bracket - never after a word.
        for text in (
            'Make the price: unbeatable and the campaign: bold.',
            'This is the headline we want.',
            'Campaign Diwali: bold',
            'Offers: 20% off. Promotional: yes. Titles: x',
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_brief_fields(text), {})
                self.assertEqual(plain_brief(text), text)

    def test_a_label_counts_after_sentence_punctuation_or_a_bracket(self):
        self.assertEqual(
            extract_brief_fields('Poster for sarees, offer: 10% off'), {'offer': '10% off'},
        )
        self.assertEqual(
            extract_brief_fields('Poster (Offer: 20% off) for sarees'), {'offer': '20% off'},
        )
        self.assertEqual(
            extract_brief_fields('(Offer: 20% off, CTA: Shop) Poster'),
            {'offer': '20% off', 'cta': 'Shop'},
        )

    def test_quotes_and_a_trailing_full_stop_are_stripped(self):
        for text in (
            'Headline: "Woven For Celebrations".',
            "Headline: 'Woven For Celebrations.'",
            'Headline: “Woven For Celebrations”',
            '  Headline:   Woven   For Celebrations.  ',
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    extract_brief_fields(text),
                    {'requested_headline': 'Woven For Celebrations'},
                )

    def test_values_are_capped(self):
        fields = extract_brief_fields('Offer: ' + 'x' * 300)
        self.assertEqual(len(fields['offer']), MAX_VALUE_CHARS)

    def test_nothing_typed_means_nothing_found(self):
        self.assertEqual(extract_brief_fields(''), {})
        self.assertEqual(extract_brief_fields(None), {})
        self.assertEqual(extract_brief_fields('Just a poster about sarees.'), {})
        self.assertEqual(plain_brief('Just a poster about sarees.'), 'Just a poster about sarees.')

    def test_the_first_occurrence_of_a_key_wins(self):
        self.assertEqual(
            extract_brief_fields('Offer: 10% off. Discount: 20% off'), {'offer': '10% off'},
        )

    def test_an_empty_label_is_not_a_field_and_does_not_swallow_the_next_line(self):
        self.assertEqual(extract_brief_fields('Offer:\nHeadline: X'), {'requested_headline': 'X'})

    def test_a_value_runs_to_the_next_label_a_newline_or_the_end(self):
        # Prose after a field on the same line is part of the value: put the
        # fields last, or one per line.
        self.assertEqual(
            extract_brief_fields('Headline: Big Sale. Poster for sarees.'),
            {'requested_headline': 'Big Sale. Poster for sarees'},
        )

    def test_every_label_in_the_vocabulary_maps_to_its_key(self):
        expected = {
            'offer': ('offer', 'deal', 'discount', 'promo', 'promotion', 'price'),
            'requested_headline': ('headline', 'title', 'hook', 'tagline'),
            'cta': ('cta', 'call to action', 'call-to-action', 'button', 'button text'),
            'occasion': ('occasion', 'event', 'festival', 'season'),
            'campaign_name': ('campaign', 'campaign name'),
            'product': ('product', 'products', 'item'),
            'target_audience': ('audience', 'target audience', 'target'),
            'location': ('location', 'city', 'where'),
            'brand_tone': ('tone', 'voice', 'mood'),
        }
        self.assertEqual(LABELS, expected)
        for key, labels in expected.items():
            for label in labels:
                with self.subTest(label=label):
                    self.assertEqual(
                        extract_brief_fields(f'{label.title()}: the value'),
                        {key: 'the value'},
                    )

    def test_plain_brief_removes_the_fields_and_keeps_the_prose(self):
        self.assertEqual(plain_brief(LIVE), LIVE_PLAIN)
        self.assertEqual(
            plain_brief('Poster for sarees\nHeadline: Woven\nOffer: 20% off\nCTA: Shop'),
            'Poster for sarees',
        )
        # A field that opened the text leaves no dangling punctuation behind.
        self.assertEqual(plain_brief('Offer: 10% off\nPoster for sarees.'), 'Poster for sarees.')
        self.assertEqual(plain_brief('Offer: 10% off, sarees. Poster.'), '')
        self.assertEqual(plain_brief('Poster (Offer: 20% off) for sarees'), 'Poster for sarees')
        self.assertEqual(plain_brief('(Offer: 20% off, CTA: Shop) Poster'), 'Poster')
        self.assertEqual(plain_brief('Offer: 10% off'), '')

    def test_with_brief_fields_fills_only_empty_keys_and_tidies_the_instruction(self):
        brief = studio_brief(offer='Flat 40% off')
        updated, instruction, filled = with_brief_fields(brief, LIVE)

        self.assertEqual(filled, {
            'requested_headline': 'Woven For Celebrations', 'cta': 'Shop the collection',
        })
        self.assertEqual(updated['offer'], 'Flat 40% off')
        self.assertEqual(updated['requested_headline'], 'Woven For Celebrations')
        self.assertEqual(updated['cta'], 'Shop the collection')
        # Only the segments that were applied leave the text: the chip won
        # over the typed offer, so "Offer: ..." stays for the copy model to
        # read what the user typed.
        self.assertEqual(updated['instruction'], LIVE_KEPT_OFFER)
        self.assertEqual(instruction, LIVE_KEPT_OFFER)
        self.assertEqual(
            updated['creative_direction']['instructions'], [REQUEST_PREFIX + LIVE_KEPT_OFFER],
        )
        # The caller's brief is untouched; the campaign-name word of the
        # synchronous endpoint is not the typed text, so it stays as it was.
        self.assertEqual(brief['instruction'], LIVE)
        self.assertEqual(brief['creative_direction']['instructions'], [REQUEST_PREFIX + LIVE])
        _same, other_word, _filled = with_brief_fields(brief, 'Kanjivaram launch')
        self.assertEqual(other_word, 'Kanjivaram launch')

    def test_with_brief_fields_leaves_a_brief_without_fields_alone(self):
        brief = studio_brief(instruction='Just a poster about sarees.')
        updated, instruction, filled = with_brief_fields(brief, brief['instruction'])
        self.assertIs(updated, brief)
        self.assertEqual(instruction, 'Just a poster about sarees.')
        self.assertEqual(filled, {})
        self.assertNotIn(PARSED_MARKER, brief)

    def test_a_capitalised_label_after_a_space_counts_only_with_a_colon(self):
        # Already-collapsed text - a row queued before the endpoint kept
        # newlines, or "... sarees Headline: X" typed mid-line - parses too:
        # after a space a label counts when its first letter is uppercase in
        # the source and the separator is ':'. Prose never capitalises its
        # nouns that way, so "the price: unbeatable" stays prose.
        collapsed = 'Poster for sarees Headline: Woven Offer: 20% off CTA: Shop'
        self.assertEqual(extract_brief_fields(collapsed), {
            'requested_headline': 'Woven', 'offer': '20% off', 'cta': 'Shop',
        })
        self.assertEqual(plain_brief(collapsed), 'Poster for sarees')
        self.assertEqual(
            extract_brief_fields('Poster for sarees Headline: Woven'),
            {'requested_headline': 'Woven'},
        )
        for text in (
            'Poster for sarees headline: Woven',   # lowercase
            'Make the price: unbeatable',
            'Poster for sarees Tone = warm',       # not ':'
            'Poster for sarees Deal - buy 1 get 1',
            'MyHeadline: Woven',                   # not after a space
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_brief_fields(text), {})
                self.assertEqual(plain_brief(text), text)

    def test_the_endpoints_normalised_instruction_parses_one_field_per_line(self):
        # The endpoint keeps the typed lines - CRLF folded, runs of spaces
        # and tabs collapsed within a line, blank lines dropped - instead of
        # flattening the brief to one line, so a field typed on its own line
        # still opens a line here.
        from apps.gemini.views import GeminiGenerationViewSet

        typed = (
            'Poster for sarees\r\nHeadline:\tWoven   For Celebrations\r\n\r\n'
            'Offer: 20% off\nCTA: Shop  '
        )
        instruction = GeminiGenerationViewSet._generation_instruction({'instruction': typed})
        self.assertEqual(
            instruction,
            'Poster for sarees\nHeadline: Woven For Celebrations\nOffer: 20% off\nCTA: Shop',
        )
        # The creative direction quotes the request whitespace-collapsed.
        brief = studio_brief(instruction=instruction)
        brief['creative_direction']['instructions'] = [
            REQUEST_PREFIX + ' '.join(instruction.split()),
        ]
        updated, word, filled = with_brief_fields(brief, instruction)
        self.assertEqual(filled, {
            'requested_headline': 'Woven For Celebrations', 'offer': '20% off', 'cta': 'Shop',
        })
        self.assertEqual(updated['instruction'], 'Poster for sarees')
        self.assertEqual(word, 'Poster for sarees')
        self.assertEqual(
            updated['creative_direction']['instructions'],
            [REQUEST_PREFIX + 'Poster for sarees'],
        )

    def test_parity_separator_and_value_never_cross_a_newline(self):
        for text in (
            'Offer:\n10% off', 'Offer: \n10% off', 'Offer\n: 10% off',
            'Offer -\n10% off', 'Offer =\n10% off',
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_brief_fields(text), {})
        # The empty label is not a field and the next line's label is read.
        self.assertEqual(extract_brief_fields('Offer:\nHeadline: X'), {'requested_headline': 'X'})
        self.assertEqual(plain_brief('Offer:\nHeadline: X'), 'Offer:')

    def test_parity_equals_takes_optional_spaces_and_the_dash_needs_both(self):
        for text in ('Tone=warm', 'Tone =warm', 'Tone= warm', 'Tone = warm', 'Tone\t=\twarm'):
            with self.subTest(text=text):
                self.assertEqual(extract_brief_fields(text), {'brand_tone': 'warm'})
        self.assertEqual(extract_brief_fields('Deal - buy 1 get 1'), {'offer': 'buy 1 get 1'})
        self.assertEqual(extract_brief_fields('Deal\t-\tbuy 1'), {'offer': 'buy 1'})
        for text in ('Deal -buy 1', 'Deal- buy 1', 'Deal-buy 1'):
            with self.subTest(text=text):
                self.assertEqual(extract_brief_fields(text), {})

    def test_parity_multi_word_labels_take_one_space_or_one_hyphen(self):
        for text, expected in (
            ('Call to action: Shop', {'cta': 'Shop'}),
            ('Call-to-action: Shop', {'cta': 'Shop'}),
            ('Call to-action: Shop', {'cta': 'Shop'}),
            ('Button text: Shop', {'cta': 'Shop'}),
            ('Button-text: Shop', {'cta': 'Shop'}),
            ('Campaign-name: Diwali', {'campaign_name': 'Diwali'}),
            ('Target-audience: brides', {'target_audience': 'brides'}),
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_brief_fields(text), expected)
        for text in (
            'Call  to action: Shop', 'Call to  action: Shop', 'Call--to-action: Shop',
            'Button  text: Shop', 'Campaign  name: Diwali',
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_brief_fields(text), {})

    def test_parity_a_value_ends_at_an_unmatched_closing_bracket(self):
        self.assertEqual(
            extract_brief_fields('Offer: 20% off (this week) only'),
            {'offer': '20% off (this week) only'},
        )
        for text in ('[Offer: 20% off] sarees', '{Offer: 20% off} sarees', 'Offer: 20% off) sarees'):
            with self.subTest(text=text):
                self.assertEqual(extract_brief_fields(text), {'offer': '20% off'})

    def test_parity_only_a_matching_pair_of_quotes_is_stripped(self):
        for text, expected in (
            ('Headline: "Woven"', 'Woven'),
            ("Headline: 'Woven'", 'Woven'),
            ('Headline: “Woven”', 'Woven'),
            ('Headline: ‘Woven’', 'Woven'),
            ('Headline: "Woven\'', '"Woven\''),
            ('Headline: “Woven"', '“Woven"'),
            ('Headline: "Woven', '"Woven'),
            ('Headline: ”Woven“', '”Woven“'),
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_brief_fields(text), {'requested_headline': expected})

    def test_a_typed_cta_must_be_one_of_the_brands_approved_keywords(self):
        law = SimpleNamespace(guardrails={'approved_ctas': ['PROTECT', 'Get Sample']})
        # Unlisted: dropped from the brief, reported, and gone from the text.
        updated, word, filled = with_brief_fields(studio_brief(), LIVE, brand=law)
        self.assertNotIn('cta', updated)
        self.assertEqual(filled, {
            'requested_headline': 'Woven For Celebrations', 'offer': '20% off launch week',
            'cta_ignored': 'Shop the collection',
        })
        self.assertEqual(updated['instruction'], LIVE_PLAIN)
        self.assertEqual(word, LIVE_PLAIN)
        # Approved - case-insensitively, whitespace-collapsed - it is the
        # CTA, spelled as typed.
        for typed, cta in (
            ('protect', 'protect'), ('"Get  sample"', 'Get sample'), ('PROTECT.', 'PROTECT'),
        ):
            with self.subTest(typed=typed):
                brief = studio_brief(instruction=f'Poster for sarees. CTA: {typed}')
                updated, _word, filled = with_brief_fields(brief, brief['instruction'], brand=law)
                self.assertEqual(updated['cta'], cta)
                self.assertEqual(filled, {'cta': cta})
        # A brand without an approved list takes any typed CTA; so does no brand.
        for brand in (SimpleNamespace(guardrails={}), None):
            with self.subTest(brand=brand):
                updated, _word, filled = with_brief_fields(studio_brief(), LIVE, brand=brand)
                self.assertEqual(updated['cta'], 'Shop the collection')
                self.assertEqual(filled, LIVE_FIELDS)

    def test_with_brief_fields_marks_the_brief_and_never_reads_it_twice(self):
        updated, _word, _filled = with_brief_fields(studio_brief(offer='Flat 40% off'), LIVE)
        self.assertIs(updated[PARSED_MARKER], True)
        # The copy-only rewrite hands the same brief back with feedback on
        # it. The kept "Offer: ..." segment would read as a fresh field if
        # the chip were empty by then; the marker says it was decided.
        again, word, refilled = with_brief_fields(
            {**updated, 'offer': '', 'guardrail_feedback': ['x']}, updated['instruction'],
        )
        self.assertEqual(refilled, {})
        self.assertEqual(again['offer'], '')
        self.assertEqual(again['instruction'], LIVE_KEPT_OFFER)
        self.assertEqual(word, LIVE_KEPT_OFFER)

    def test_only_the_occurrence_a_key_was_read_from_leaves_the_text(self):
        # The first occurrence wins; a repeat, or a synonym label later on,
        # was never applied, so it is not scrubbed either - it stays prose.
        self.assertEqual(plain_brief('Offer: 10% off. Offer: 20% off'), 'Offer: 20% off')
        self.assertEqual(
            plain_brief('Offer: 10% off. Discount: 20% off'), 'Discount: 20% off',
        )
        brief = studio_brief(instruction='Poster for sarees. Offer: 10% off. Offer: 20% off')
        updated, word, filled = with_brief_fields(brief, brief['instruction'])
        self.assertEqual(filled, {'offer': '10% off'})
        self.assertEqual(updated['offer'], '10% off')
        self.assertEqual(updated['instruction'], 'Poster for sarees. Offer: 20% off')
        self.assertEqual(word, 'Poster for sarees. Offer: 20% off')

    def test_a_dismissed_field_stays_prose_and_never_fills_its_key(self):
        # The studio's user dismissed the offer auto-fill: the segment is
        # neither applied nor scrubbed, and the report says so.
        brief = studio_brief(brief_fields_dismissed=['offer'])
        updated, word, filled = with_brief_fields(brief, LIVE)
        self.assertEqual(filled, {
            'requested_headline': 'Woven For Celebrations', 'cta': 'Shop the collection',
            'dismissed': ['offer'],
        })
        self.assertEqual(updated['offer'], '')
        self.assertEqual(updated['instruction'], LIVE_KEPT_OFFER)
        self.assertEqual(word, LIVE_KEPT_OFFER)
        self.assertEqual(
            updated['creative_direction']['instructions'], [REQUEST_PREFIX + LIVE_KEPT_OFFER],
        )
        # Every typed field dismissed: nothing fills, the text is untouched,
        # and the brief is still marked as read.
        brief = studio_brief(
            instruction='Poster for sarees. Offer: 10% off.',
            brief_fields_dismissed=['offer', 'cta'],
        )
        updated, word, filled = with_brief_fields(brief, brief['instruction'])
        self.assertEqual(filled, {'dismissed': ['offer']})
        self.assertEqual(updated['offer'], '')
        self.assertEqual(updated['instruction'], 'Poster for sarees. Offer: 10% off.')
        self.assertEqual(word, 'Poster for sarees. Offer: 10% off.')
        self.assertIs(updated[PARSED_MARKER], True)
        # Junk under the key is ignored, never fatal.
        for junk in ('offer', {'offer': True}, [{'key': 'offer'}], None):
            with self.subTest(junk=junk):
                updated, _word, filled = with_brief_fields(
                    studio_brief(brief_fields_dismissed=junk), LIVE,
                )
                self.assertEqual(filled, LIVE_FIELDS)
                self.assertEqual(updated['offer'], '20% off launch week')

    def test_dismissed_keys_are_validated_against_the_vocabulary(self):
        self.assertEqual(
            dismissed_brief_fields({
                'briefFieldsDismissed': ['offer', 'Offer', 'nope', 7, 'cta', 'offer'],
            }),
            ['offer', 'cta'],
        )
        self.assertEqual(
            dismissed_brief_fields({'brief_fields_dismissed': ['occasion']}), ['occasion'],
        )
        # camelCase wins when both are sent; anything but a list reads as none.
        self.assertEqual(
            dismissed_brief_fields({
                'briefFieldsDismissed': ['cta'], 'brief_fields_dismissed': ['offer'],
            }),
            ['cta'],
        )
        for junk in ('offer', {'offer': True}, None, 7):
            with self.subTest(junk=junk):
                self.assertEqual(dismissed_brief_fields({'briefFieldsDismissed': junk}), [])
        self.assertEqual(dismissed_brief_fields({}), [])
        # Bounded: only the first MAX_DISMISSED entries are ever read.
        self.assertEqual(
            dismissed_brief_fields({
                'briefFieldsDismissed': ['nope'] * MAX_DISMISSED + ['offer'],
            }),
            [],
        )

    def test_stored_offer_reads_the_chip_first_then_the_trace(self):
        typed = {'brief_fields': {'offer': '20% off launch week'}}
        self.assertEqual(stored_offer({'offer': 'Flat 40% off'}, typed), 'Flat 40% off')
        self.assertEqual(stored_offer({'offer': ''}, typed), '20% off launch week')
        self.assertEqual(stored_offer({'offer': '  '}, typed), '20% off launch week')
        self.assertEqual(stored_offer({}, {'brief_fields': {'dismissed': ['offer']}}), '')
        self.assertEqual(stored_offer({}, None), '')
        self.assertEqual(stored_offer({}, {'brief_fields': 'junk'}), '')

    def test_an_only_fields_brief_leaves_no_request_line_behind(self):
        # Nothing but fields was typed: with nothing left to quote, the
        # creative direction's "User creation request" line goes - a refused
        # CTA must not survive there as prose. Other lines are untouched.
        law = SimpleNamespace(guardrails={'approved_ctas': ['PROTECT']})
        typed = 'Headline: Woven. Offer: 10% off. CTA: Shop'
        brief = studio_brief(instruction=typed)
        brief['creative_direction']['instructions'] = [
            'Use the selected Scaleezy composition layout: x.', REQUEST_PREFIX + typed,
        ]
        updated, word, filled = with_brief_fields(brief, typed, brand=law)
        self.assertEqual(
            filled, {'requested_headline': 'Woven', 'offer': '10% off', 'cta_ignored': 'Shop'},
        )
        self.assertEqual(updated['instruction'], '')
        self.assertEqual(word, '')
        self.assertEqual(
            updated['creative_direction']['instructions'],
            ['Use the selected Scaleezy composition layout: x.'],
        )
        self.assertNotIn('Shop', str(updated['creative_direction']))
        # The caller's brief is untouched.
        self.assertEqual(brief['creative_direction']['instructions'][1], REQUEST_PREFIX + typed)


class BriefFieldsGenerationTests(TenantFixtureMixin, TestCase):
    """The one parse point, seen from the provider side of the exchange."""

    def setUp(self):
        self.ws = self.make_workspace('Rajvi', 'rajvi-brief-fields')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Rajvi Silks', is_default=True,
            status=Brand.Status.ACTIVE, cta_keyword='MORE INFO',
        )

    def generate(self, router, brief, instruction=None):
        """The worker's shape unless told otherwise: instruction is the
        brief's own typed text."""
        with router.patched():
            return generate_marketing_payload(
                self.ws, brief,
                instruction=brief.get('instruction', '') if instruction is None else instruction,
            )

    def test_a_typed_offer_reaches_the_on_image_offer_line_and_the_trace(self):
        router = Router()
        result = self.generate(router, studio_brief())

        (image_brief,) = router.image_briefs()
        self.assertEqual(image_brief['offer'], '20% off launch week')
        self.assertTrue(
            lines_with(image_brief, 'the offer line "20% off launch week"'),
            image_brief.get('brand_context'),
        )
        self.assertEqual(result['trace']['brief_fields'], LIVE_FIELDS)

        # The copy model reads the brief without the field noise, in both
        # places it is quoted, and the fields as structured keys instead.
        (text_brief,) = router.text_briefs()
        self.assertEqual(text_brief['instruction'], LIVE_PLAIN)
        self.assertEqual(text_brief['offer'], '20% off launch week')
        self.assertEqual(
            text_brief['creative_direction']['instructions'], [REQUEST_PREFIX + LIVE_PLAIN],
        )

    def test_a_selected_chip_wins_over_a_typed_offer(self):
        router = Router()
        result = self.generate(router, studio_brief(
            instruction='Poster for sarees. Offer: 20% off launch week.',
            offer='Flat 40% off',
        ))

        (image_brief,) = router.image_briefs()
        self.assertTrue(lines_with(image_brief, 'the offer line "Flat 40% off"'))
        self.assertFalse(lines_with(image_brief, '20% off launch week'))
        self.assertEqual(image_brief['offer'], 'Flat 40% off')
        # Nothing was filled, so nothing is recorded - and the typed offer
        # stays in the text the copy model reads.
        self.assertNotIn('brief_fields', result['trace'])
        (text_brief,) = router.text_briefs()
        self.assertEqual(text_brief['instruction'], 'Poster for sarees. Offer: 20% off launch week.')
        self.assertEqual(text_brief['offer'], 'Flat 40% off')

    def test_a_dismissed_offer_stays_prose_all_the_way_to_the_providers(self):
        router = Router()
        result = self.generate(router, studio_brief(brief_fields_dismissed=['offer']))

        (image_brief,) = router.image_briefs()
        self.assertEqual(image_brief['offer'], '')
        self.assertFalse(lines_with(image_brief, 'the offer line'))
        (text_brief,) = router.text_briefs()
        self.assertEqual(text_brief['instruction'], LIVE_KEPT_OFFER)
        self.assertEqual(text_brief['offer'], '')
        self.assertEqual(result['trace']['brief_fields'], {
            'requested_headline': 'Woven For Celebrations', 'cta': 'Shop the collection',
            'dismissed': ['offer'],
        })

    def test_a_typed_cta_outside_the_brands_law_never_reaches_the_image(self):
        self.brand.guardrails = {'approved_ctas': ['PROTECT']}
        self.brand.save(update_fields=['guardrails'])

        # Unlisted: the brand keyword stays the pill, the refusal is in the
        # trace, and the caption still gets the law's own "DM PROTECT".
        router = Router()
        result = self.generate(router, studio_brief())
        (image_brief,) = router.image_briefs()
        self.assertFalse(lines_with(image_brief, 'Shop the collection'))
        self.assertTrue(
            lines_with(image_brief, 'a call-to-action pill/button reading "MORE INFO"'),
        )
        self.assertEqual(result['trace']['brief_fields'], {
            'requested_headline': 'Woven For Celebrations', 'offer': '20% off launch week',
            'cta_ignored': 'Shop the collection',
        })
        self.assertIn('DM PROTECT', result['payload']['postDescription'])

        # Approved: it is the pill, the caption gets no second CTA, and the
        # law stands down for it everywhere - the copy check does not burn
        # the one free rewrite on the missing keyword (exactly ONE TEXT
        # dispatch), nothing is left unresolved, and the prompt line the
        # generator and the judge read names the CTA instead of demanding a
        # keyword.
        router = Router()
        result = self.generate(router, studio_brief(instruction='Poster for sarees. CTA: Protect'))
        (image_brief,) = router.image_briefs()
        self.assertTrue(
            lines_with(image_brief, 'a call-to-action pill/button reading "Protect"'),
        )
        self.assertEqual(result['trace']['brief_fields'], {'cta': 'Protect'})
        self.assertEqual(result['payload']['postDescription'], COPY['caption'])
        self.assertEqual(result['trace'].get('guardrails', {}).get('unresolved', []), [])
        (text_brief,) = router.text_briefs()
        rules = text_brief['guardrail_rules']
        self.assertFalse([line for line in rules if 'MUST use exactly one of' in line], rules)
        self.assertTrue([line for line in rules if '"Protect"' in line], rules)
        (judged,) = router.judge_inputs()
        self.assertEqual(judged['brand_guardrails'], rules)

    def test_the_stand_down_needs_a_poster_that_paints_its_own_cta(self):
        # A catalogue-template poster (like a video or a carousel) paints no
        # words of its own, so an approved typed CTA sits on no media at
        # all: the caption still owes the brand's keyword, and the law's
        # demand stays in the prompt line the generator and the judge read.
        self.brand.guardrails = {'approved_ctas': ['PROTECT']}
        self.brand.save(update_fields=['guardrails'])
        router = Router()
        result = self.generate(router, studio_brief(
            instruction='Poster for sarees. CTA: Protect',
            creative_direction={
                'mode': 'CATALOG_TEMPLATE', 'layout': 'agency_column', 'selections': [],
            },
        ))
        self.assertEqual(result['trace']['brief_fields'], {'cta': 'Protect'})
        self.assertIn('DM PROTECT', result['payload']['postDescription'])
        first_text = router.text_briefs()[0]
        rules = first_text['guardrail_rules']
        self.assertTrue([line for line in rules if 'MUST use exactly one of' in line], rules)

    def test_a_typed_headline_is_a_must_line_for_the_copy_and_a_constraint_for_the_judge(self):
        # The judge fails the first draft once, so the copy-only rewrite
        # runs too: it must carry the same MUST line.
        router = Router(verdicts=[JUDGE_FAIL, JUDGE_PASS])
        result = self.generate(router, studio_brief())

        first, rewrite = router.text_briefs()
        self.assertTrue(rewrite.get('copy_only'))
        for brief in (first, rewrite):
            self.assertEqual(lines_with(brief, 'MUST: Use this exact headline'), [HEADLINE_MUST])
            self.assertNotIn('headline', brief)
        self.assertEqual(result['trace']['critique']['verdict'], 'regenerated')

        judged = router.judge_inputs()
        self.assertEqual(len(judged), 2)
        for structured in judged:
            self.assertEqual(structured['requested_headline'], 'Woven For Celebrations')
            # The MUST line is among the rules the judge grades against.
            self.assertIn(HEADLINE_MUST, structured['brand_rules'])

        # The picture is still painted with the FINAL copy's headline - here
        # equal to the request - never with a separate key.
        (image_brief,) = router.image_briefs()
        self.assertEqual(image_brief['headline'], 'Woven For Celebrations')
        self.assertTrue(lines_with(image_brief, 'correctly spelled: "Woven For Celebrations"'))
        self.assertEqual(result['payload']['postTitle'], 'Woven For Celebrations')

    def test_a_typed_cta_is_the_on_image_call_to_action(self):
        router = Router()
        self.generate(router, studio_brief())
        (image_brief,) = router.image_briefs()
        self.assertTrue(
            lines_with(image_brief, 'a call-to-action pill/button reading "Shop the collection"'),
        )
        self.assertFalse(lines_with(image_brief, 'MORE INFO'))

        # Without a typed CTA the brand's keyword is the pill, as before.
        router = Router()
        self.generate(router, studio_brief(instruction='Poster for sarees. Offer: 10% off.'))
        (image_brief,) = router.image_briefs()
        self.assertTrue(
            lines_with(image_brief, 'a call-to-action pill/button reading "MORE INFO"'),
        )

    def test_the_synchronous_shape_parses_the_typed_brief_too(self):
        # The synchronous endpoint passes the campaign name as its word and
        # the typed text only inside the brief.
        router = Router()
        result = self.generate(router, studio_brief(), instruction='Kanjivaram launch')
        self.assertEqual(result['trace']['brief_fields'], LIVE_FIELDS)
        (image_brief,) = router.image_briefs()
        self.assertTrue(lines_with(image_brief, 'the offer line "20% off launch week"'))

    def test_retry_image_on_a_stored_brief_carries_the_typed_fields(self):
        router = Router()
        trace = {}
        with router.patched():
            retry_image(
                self.ws, self.brand,
                {**studio_brief(), 'headline': 'Woven For Celebrations'},
                instruction=LIVE, trace=trace,
            )
        (image_brief,) = router.image_briefs()
        self.assertTrue(lines_with(image_brief, 'the offer line "20% off launch week"'))
        self.assertTrue(
            lines_with(image_brief, 'a call-to-action pill/button reading "Shop the collection"'),
        )
        self.assertEqual(trace['brief_fields'], LIVE_FIELDS)

    def test_a_reviewer_verdict_is_never_mined_for_fields(self):
        # Request-edits builds its own brief without `instruction` and passes
        # the reviewer's verdict as its word: labels in there are not fields.
        router = Router()
        brief = {
            'campaign_name': 'Woven For Celebrations', 'offer': '',
            'previous_headline': 'Woven For Celebrations', 'contentType': 'poster',
            'creative_direction': {'mode': 'AI_ORIGINAL', 'selections': []},
            'request_id': str(uuid.uuid4()),
        }
        result = self.generate(
            router, brief,
            instruction='Revise the previous version. Reviewer note: Headline: too generic. '
                        'Offer: not visible.',
        )
        self.assertNotIn('brief_fields', result['trace'])
        (text_brief,) = router.text_briefs()
        self.assertFalse(lines_with(text_brief, 'MUST: Use this exact headline'))
        (image_brief,) = router.image_briefs()
        self.assertFalse(lines_with(image_brief, 'the offer line'))


class BriefFieldsPersistenceTests(TenantFixtureMixin, TestCase):
    """A typed-only offer lands on the item (`ContentItem.cta` stores the
    offer text) on both persistence paths - the worker's and the synchronous
    endpoint's - although each persists the brief it passed in, not the
    parsed one; and both endpoints carry the studio's dismissed keys."""

    def setUp(self):
        self.ws = self.make_workspace('Rajvi', 'rajvi-brief-persist')
        self.user, self.api = self.authenticate_as(
            self.ws, WorkspaceMember.Role.MANAGER, 'rajvi-brief-manager',
        )
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Rajvi Silks', is_default=True,
            status=Brand.Status.ACTIVE, cta_keyword='MORE INFO',
        )

    def test_the_worker_persists_the_typed_offer_and_request_edits_carries_it(self):
        from apps.gemini.tasks import generate_content, regenerate_revision

        request = GeminiGenerationRequest.objects.create(
            workspace=self.ws, user=self.user,
            prompt_data=json.dumps(studio_brief()),
            status=GeminiGenerationRequest.Status.PENDING,
        )
        router = Router()
        with router.patched():
            generate_content.func(str(request.pk))
        request.refresh_from_db()
        self.assertEqual(
            request.status, GeminiGenerationRequest.Status.COMPLETED, request.error_message,
        )
        item = ContentItem.objects.get(workspace=self.ws)
        self.assertEqual(item.cta, '20% off launch week')
        self.assertEqual(item.layout_config['generation_trace']['brief_fields'], LIVE_FIELDS)

        # Sent back for edits: the revision inherits the offer, and the
        # regeneration's brief carries it as its own offer.
        item.status = ContentItem.Status.PENDING_REVIEW
        item.save(update_fields=['status'])
        with patch('apps.gemini.tasks.regenerate_revision'):
            res = self.api.post(
                f'/api/marketing/content/{item.id}/request-edits/',
                {'note': 'headline is flat', 'elements': ['headline', 'imagery_subject']},
                format='json', **workspace_header(self.ws),
            )
        self.assertEqual(res.status_code, 200, res.content[:300])
        revision = ContentItem.objects.get(parent=item)
        self.assertEqual(revision.cta, '20% off launch week')
        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value={
                'payload': {
                    'postTitle': 'Woven For Celebrations', 'postDescription': 'Revised.',
                    'postHashtags': '#silk', 'posterImageUrl': IMAGE['image_url'],
                },
                'provider': 'OPENAI', 'provider_name': 'OpenAI', 'brain_version': '',
                'trace': {},
            },
        ) as dispatched:
            regenerate_revision.func(str(revision.pk))
        dispatched.assert_called_once()
        self.assertEqual(dispatched.call_args.args[1]['offer'], '20% off launch week')

    def test_the_synchronous_endpoint_persists_the_typed_offer(self):
        router = Router()
        with router.patched():
            res = self.api.post(
                GENERATE_URL,
                {'creativeMode': 'AI_ORIGINAL', 'campaignName': 'Kanjivaram launch',
                 'offer': '', 'instruction': LIVE},
                format='json', **workspace_header(self.ws),
            )
        self.assertEqual(res.status_code, 201, res.content[:300])
        item = ContentItem.objects.get(id=res.json()['data']['contentItemId'])
        self.assertEqual(item.cta, '20% off launch week')
        self.assertEqual(item.layout_config['generation_trace']['brief_fields'], LIVE_FIELDS)

    def test_the_endpoints_carry_the_studios_dismissed_keys_validated(self):
        res = self.api.post(
            GENERATE_ASYNC_URL,
            {'campaignName': 'Kanjivaram launch', 'contentType': 'poster',
             'creativeMode': 'AI_ORIGINAL', 'instruction': LIVE,
             'briefFieldsDismissed': ['offer', 'bogus', 7, 'offer']},
            format='json', **workspace_header(self.ws),
        )
        self.assertEqual(res.status_code, 202, res.content[:300])
        queued = json.loads(GeminiGenerationRequest.objects.get().prompt_data)
        self.assertEqual(queued['brief_fields_dismissed'], ['offer'])

        # The synchronous endpoint takes the snake_case twin, and the parse
        # honours it: the offer chip stays empty, nothing is persisted as
        # the offer, and the trace says why.
        router = Router()
        with router.patched():
            res = self.api.post(
                GENERATE_URL,
                {'creativeMode': 'AI_ORIGINAL', 'campaignName': 'Kanjivaram launch',
                 'offer': '', 'instruction': LIVE, 'brief_fields_dismissed': ['offer']},
                format='json', **workspace_header(self.ws),
            )
        self.assertEqual(res.status_code, 201, res.content[:300])
        (image_brief,) = router.image_briefs()
        self.assertEqual(image_brief['offer'], '')
        self.assertFalse(lines_with(image_brief, 'the offer line'))
        item = ContentItem.objects.get(id=res.json()['data']['contentItemId'])
        self.assertEqual(item.cta, '')
        self.assertEqual(item.layout_config['generation_trace']['brief_fields'], {
            'requested_headline': 'Woven For Celebrations', 'cta': 'Shop the collection',
            'dismissed': ['offer'],
        })
