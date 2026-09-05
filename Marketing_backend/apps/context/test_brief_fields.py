"""
Fields typed into the studio's free-text brief count exactly like chips.

Live, "Instagram poster for the new Kanjivaram silk saree collection.
Headline: Woven For Celebrations. Offer: 20% off launch week. CTA: Shop the
collection." was typed with the offer chip left empty: the poster carried no
offer at all (the on-image offer line reads only `brief['offer']`) and the
copy judge rewrote the typed headline. These tests pin:

  * the parser (`apps.context.services.brief_fields`): the label vocabulary,
    the matching rule - a label counts only at the start of the text, after
    a newline, or after sentence punctuation or an opening bracket - the
    value rule (to the next label, a newline or the end; surrounding quotes
    and one trailing '.' stripped; 200 chars) and `plain_brief`;
  * the one parse point in `generate_marketing_payload`: a typed offer
    reaches the IMAGE brief's on-image offer line and the trace
    (`layout_config.generation_trace['brief_fields']`); a selected chip wins
    over a typed value; a typed headline is a MUST line in the TEXT brief
    (the judge's rewrite included) and reaches the critique judge as
    `requested_headline`; a typed CTA is the on-image call-to-action;
  * the worker's shape (instruction=brief['instruction']) and the
    synchronous endpoint's shape (instruction=campaign name) both parse;
    `retry_image` on a stored brief carries the typed fields; a reviewer's
    request-edits verdict is never mined for labels.

The router is a recording stand-in: no provider is ever called.
"""
import copy
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.ai.models import Capability
from apps.ai.router import NoProviderAvailable
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.context.services.brief_fields import (
    LABELS,
    MAX_VALUE_CHARS,
    extract_brief_fields,
    plain_brief,
    with_brief_fields,
)
from apps.context.services.generation import generate_marketing_payload, retry_image

DISPATCH = 'apps.ai.router.AIRouter.dispatch'
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
        self.assertEqual(updated['instruction'], LIVE_PLAIN)
        self.assertEqual(instruction, LIVE_PLAIN)
        self.assertEqual(
            updated['creative_direction']['instructions'], [REQUEST_PREFIX + LIVE_PLAIN],
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
        # Nothing was filled, so nothing is recorded.
        self.assertNotIn('brief_fields', result['trace'])

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
