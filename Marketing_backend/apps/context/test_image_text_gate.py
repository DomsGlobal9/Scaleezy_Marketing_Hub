"""
The words on a finished poster are read back before the review card sees it.

Live, the image model rendered a longer headline than the saved copy plus a
strapline nobody wrote. These tests pin the gate in
`apps.context.services.generation`:

  * after a poster is bought and persisted, the finished picture is checked
    against the FINAL headline (the judged copy), the brand's CTA keyword and
    the campaign's offer;
  * a failing verdict buys the picture ONCE more on the very same brief (same
    headline, composition and scene) and ships whichever of the two reads
    better, the second on a tie - a re-draw that lost the headline never
    replaces a picture that only added a word, and a poster beats no poster;
  * every painted brief - the first buy, the re-buy, `retry_image`'s - carries
    the judged headline as `headline`, the contract with a provider whose
    image call re-runs its own copy step and would otherwise paint a fresh
    title;
  * a brand template's own text slots are words the judge cannot know, so
    `extra_text` is tolerated there (no re-buy); a missing or altered headline
    still re-buys;
  * the check can never cost the poster: a crashing or absent checker reads
    as skipped, a failed re-buy keeps the first picture and its record;
  * a poster that paints no words (the compose engine's, a carousel slide, a
    copy-less generation) is never checked;
  * the trace (`layout_config.generation_trace['image_text']`) says what was
    read, whether a re-buy happened, which picture was kept and the verdict
    of the picture that ships.

Black-box against the checker: `check_image_text` is patched at its own
module path with a scripted verdict per call. While that module is still
being built, a stand-in module is installed for the test's duration.
"""
import copy
import importlib
import sys
import types
import uuid
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps.ai.models import Capability
from apps.ai.router import NoProviderAvailable
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.context.services.generation import (
    OutputRejected,
    generate_copy_and_image,
    generate_marketing_payload,
    retry_image,
)

IMAGE_TEXT = 'apps.context.services.image_text'
DISPATCH = 'apps.ai.router.AIRouter.dispatch'
PRIMARY = 'apps.ai.router.AIRouter.primary_adapter'
PERSIST = 'apps.context.services.generation.persist_generated_image'

HEADLINE = 'Roasted this week'
FIRST_URL = 'https://cdn.example.com/first.png'
SECOND_URL = 'https://cdn.example.com/second.png'

#: Stable https URLs: persistence leaves them alone, so no storage is touched.
FIRST = {
    'image_url': FIRST_URL,
    'provider': 'STABILITY', 'provider_name': 'Stability', 'latency_ms': 20,
}
SECOND = {**FIRST, 'image_url': SECOND_URL, 'latency_ms': 21}
COPY = {
    'headline': HEADLINE, 'caption': 'Fresh beans.', 'hashtags': '#coffee',
    'raw': {}, 'provider': 'OPENAI', 'provider_name': 'OpenAI', 'latency_ms': 10,
}


def verdict(kind, found=(), reason=''):
    return {'verdict': kind, 'found': list(found), 'expected': HEADLINE, 'reason': reason}


OK = verdict('ok')
ALTERED = verdict(
    'headline_altered',
    found=['ROASTED THIS WEEK ONLY', 'Fresh from the roaster'],
    reason='the headline reads "ROASTED THIS WEEK ONLY"',
)
EXTRA = verdict(
    'extra_text', found=[HEADLINE, 'Limited edition'],
    reason='words the brief never asked for: "Limited edition"',
)
MISSING = verdict(
    'headline_missing', found=['Fresh from the roaster'],
    reason='the headline is not on the image',
)
SKIPPED = verdict('skipped', reason='disabled for this workspace')
CTA_DUP = verdict(
    'cta_duplicated',
    found=[HEADLINE, 'Book a styling session', 'SHOP THE COLLECTION'],
    reason='More than one call-to-action on the image.',
)


def poster_brief(**overrides):
    brief = {
        'contentType': 'poster', 'offer': '30% off',
        'creative_direction': {'mode': 'AI_ORIGINAL', 'selections': []},
        'request_id': str(uuid.uuid4()),
    }
    brief.update(overrides)
    return brief


def template_brief(**overrides):
    """A poster that recreates one of the brand's own template designs. The
    template row points nowhere, so no pixels are fetched - the directive
    and the gate read the selection, not the file."""
    return poster_brief(
        creative_direction={
            'mode': 'AI_ORIGINAL',
            'selections': [{'kind': 'BRAND_TEMPLATE', 'id': str(uuid.uuid4())}],
        },
        **overrides,
    )


def paints(brief, headline):
    """Whether an IMAGE brief's brand-context lines quote `headline` as the
    words to render on the poster."""
    return any(
        f'"{headline}"' in str(line) for line in brief.get('brand_context') or []
    )


def _checker_importable():
    try:
        importlib.import_module(IMAGE_TEXT)
    except Exception:
        return False
    return True


class Checker:
    """`check_image_text`, scripted: one answer per call, an Exception
    instance raised in its place. Records every call's arguments."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, workspace, image, *, headline, cta='', offer='', brand_name=''):
        self.calls.append({
            'workspace': workspace, 'image': image, 'headline': headline,
            'cta': cta, 'offer': offer, 'brand_name': brand_name,
        })
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return dict(answer)

    @contextmanager
    def patched(self):
        with ExitStack() as stack:
            if not _checker_importable():
                stack.enter_context(patch.dict(
                    sys.modules, {IMAGE_TEXT: types.ModuleType(IMAGE_TEXT)},
                ))
            stack.enter_context(patch(f'{IMAGE_TEXT}.check_image_text', self, create=True))
            yield


class Router:
    """The provider side of the exchange. TEXT answers with `copy` (the
    judge, a TEXT EXTRACT dispatch, passes); IMAGE answers from `images` in
    order, an Exception instance raised in its place. Records every
    dispatch."""

    def __init__(self, images, *, copy_result=None, text_error=None):
        self.images = list(images)
        self.copy_result = copy_result if copy_result is not None else COPY
        self.text_error = text_error
        self.calls = []

    def dispatch(self, capability, brief, content_item_id=None, *, internal=False):
        self.calls.append({'capability': capability, 'brief': brief, 'internal': internal})
        if capability == Capability.IMAGE:
            answer = self.images.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return dict(answer)
        if capability == Capability.TEXT:
            if str(brief.get('task') or '').upper() == 'EXTRACT':
                return {'raw': {'passes': True, 'violations': [], 'rewrite_instruction': ''}}
            if self.text_error is not None:
                raise self.text_error
            return copy.deepcopy(self.copy_result)
        raise NoProviderAvailable(f'No provider routed for {capability}.')

    def image_briefs(self):
        return [call['brief'] for call in self.calls if call['capability'] == Capability.IMAGE]

    def patched(self):
        stand_in = self

        def dispatch(_router, capability, brief, content_item_id=None, *, internal=False):
            return stand_in.dispatch(capability, brief, content_item_id, internal=internal)

        return patch(DISPATCH, dispatch)


class ImageTextGateTests(TenantFixtureMixin, TestCase):
    """Two providers, two dispatches: the check sits after the persisted
    picture, and its re-buy is the only second image."""

    def setUp(self):
        self.ws = self.make_workspace('Acme', 'c1')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Acme Co', is_default=True,
            status=Brand.Status.ACTIVE, cta_keyword='MORE INFO',
        )

    def generate(self, router, checker, brief=None):
        with router.patched(), checker.patched():
            return generate_copy_and_image(
                self.ws, self.brand, brief or poster_brief(), instruction='Launch',
            )

    def test_a_passing_verdict_ships_the_one_picture_and_records_it(self):
        router, checker = Router([FIRST]), Checker([OK])
        outcome = self.generate(router, checker)

        self.assertEqual(len(router.image_briefs()), 1)
        self.assertEqual(outcome['image']['image_url'], FIRST_URL)
        self.assertEqual(outcome['trace']['image_text'], {
            'verdict': 'ok', 'found': [], 'expected': HEADLINE,
            'retried': False, 'final_verdict': 'ok', 'reason': '',
        })
        # Checked once, against the final headline, the brand's CTA keyword,
        # the campaign's offer and the brand's name, on the persisted picture.
        (call,) = checker.calls
        self.assertEqual(call['image']['image_url'], FIRST_URL)
        self.assertEqual(call['headline'], HEADLINE)
        self.assertEqual(call['cta'], 'MORE INFO')
        self.assertEqual(call['offer'], '30% off')
        self.assertEqual(call['brand_name'], 'Acme Co')
        self.assertIs(call['workspace'], self.ws)

    def test_an_altered_headline_buys_once_more_and_the_second_picture_ships(self):
        router, checker = Router([FIRST, SECOND]), Checker([ALTERED, OK])
        with router.patched(), checker.patched():
            result = generate_marketing_payload(self.ws, poster_brief())

        first_brief, second_brief = router.image_briefs()
        # The re-buy is the same brief: the same headline painted, the same
        # composition and scene, so the second poster is the first one
        # re-drawn and not a new design.
        self.assertTrue(paints(first_brief, HEADLINE), first_brief.get('brand_context'))
        self.assertTrue(paints(second_brief, HEADLINE), second_brief.get('brand_context'))
        for key in ('composition_archetype', 'scene_variant'):
            self.assertEqual(first_brief.get(key), second_brief.get(key), key)
            self.assertTrue(first_brief.get(key), key)

        self.assertEqual(result['payload']['posterImageUrl'], SECOND_URL)
        self.assertEqual(
            result['payload']['metadata']['generated_image']['image_url'], SECOND_URL,
        )
        self.assertEqual(result['trace']['capabilities'][Capability.IMAGE]['status'], 'OK')
        record = result['trace']['image_text']
        self.assertEqual(record['verdict'], 'headline_altered')
        self.assertEqual(record['found'], ALTERED['found'])
        self.assertEqual(record['expected'], HEADLINE)
        self.assertEqual(record['reason'], ALTERED['reason'])
        self.assertTrue(record['retried'])
        self.assertEqual(record['kept'], 'second')
        self.assertEqual(record['final_verdict'], 'ok')
        self.assertNotIn('rebuy_error', record)
        # The second check read the second picture.
        self.assertEqual(
            [call['image']['image_url'] for call in checker.calls], [FIRST_URL, SECOND_URL],
        )

    def test_a_second_picture_that_reads_no_worse_ships(self):
        # Altered headline, then a stray word: the re-draw failed too, but
        # less badly, so it is the poster that ships.
        router, checker = Router([FIRST, SECOND]), Checker([ALTERED, EXTRA])
        outcome = self.generate(router, checker)

        self.assertEqual(len(router.image_briefs()), 2)
        self.assertEqual(outcome['image']['image_url'], SECOND_URL)
        record = outcome['trace']['image_text']
        self.assertEqual(record['verdict'], 'headline_altered')
        self.assertTrue(record['retried'])
        self.assertEqual(record['kept'], 'second')
        self.assertEqual(record['final_verdict'], 'extra_text')
        self.assertEqual(record['final_found'], EXTRA['found'])
        self.assertEqual(record['final_reason'], EXTRA['reason'])
        self.assertEqual(len(checker.calls), 2)

        # A tie ships the second: the re-draw was the point.
        router, checker = Router([FIRST, SECOND]), Checker([ALTERED, ALTERED])
        outcome = self.generate(router, checker)
        self.assertEqual(outcome['image']['image_url'], SECOND_URL)
        self.assertEqual(outcome['trace']['image_text']['kept'], 'second')
        self.assertEqual(outcome['trace']['image_text']['final_verdict'], 'headline_altered')

    def test_the_better_of_the_two_pictures_ships(self):
        """A re-draw is judged against the picture it would replace: one
        that lost the headline never replaces one that only added a word.
        Both were bought and read; the first ships with its own record."""
        router, checker = Router([FIRST, SECOND]), Checker([EXTRA, MISSING])
        outcome = self.generate(router, checker)

        self.assertEqual(len(router.image_briefs()), 2)
        self.assertEqual(
            [call['image']['image_url'] for call in checker.calls], [FIRST_URL, SECOND_URL],
        )
        self.assertEqual(outcome['image']['image_url'], FIRST_URL)
        # The re-buy's dispatch wrote its own capability record; the first
        # picture's is restored with it.
        self.assertEqual(outcome['trace']['capabilities'][Capability.IMAGE], {
            'status': 'OK', 'provider': 'STABILITY', 'latency_ms': 20,
        })
        record = outcome['trace']['image_text']
        self.assertEqual(record['verdict'], 'extra_text')
        self.assertEqual(record['reason'], EXTRA['reason'])
        self.assertTrue(record['retried'])
        self.assertEqual(record['kept'], 'first')
        self.assertEqual(record['final_verdict'], 'extra_text')
        self.assertEqual(record['rebuy_verdict'], 'headline_missing')
        self.assertEqual(record['rebuy_reason'], MISSING['reason'])
        self.assertNotIn('final_found', record)
        self.assertNotIn('rebuy_error', record)

        # The same ranking through `retry_image`.
        router, checker, trace = Router([FIRST, SECOND]), Checker([EXTRA, MISSING]), {}
        with router.patched(), checker.patched():
            image = retry_image(
                self.ws, self.brand, poster_brief(headline=HEADLINE), trace=trace,
            )
        self.assertEqual(image['image_url'], FIRST_URL)
        self.assertEqual(len(router.image_briefs()), 2)
        self.assertEqual(trace['image_text']['kept'], 'first')
        self.assertEqual(trace['image_text']['final_verdict'], 'extra_text')

    def test_a_caller_supplied_headline_never_reaches_the_text_brief(self):
        # A combined provider paints whatever `headline` its brief carries,
        # so a stray one on the TEXT brief would pin Step 1's title to words
        # nobody judged. The IMAGE brief still ends up with the judged one.
        router, checker = Router([FIRST]), Checker([OK])
        outcome = self.generate(router, checker, poster_brief(headline='User typed line'))

        text_briefs = [
            c['brief'] for c in router.calls
            if c['capability'] == Capability.TEXT
            and str(c['brief'].get('task') or '').upper() != 'EXTRACT'
        ]
        self.assertTrue(text_briefs)
        for brief in text_briefs:
            self.assertNotIn('headline', brief)
        (image_brief,) = router.image_briefs()
        self.assertEqual(image_brief['headline'], HEADLINE)
        self.assertEqual(outcome['text']['headline'], HEADLINE)

    def test_every_painted_brief_carries_the_headline_it_paints(self):
        """The contract with a provider whose image call re-runs its own
        copy step (Gemini's `generate_image` runs Step 1 again and would
        paint its fresh title): the first buy, the gate's re-buy and
        `retry_image`'s buy all fix the judged headline as `headline`."""
        router, checker = Router([FIRST, SECOND]), Checker([ALTERED, OK])
        with router.patched(), checker.patched():
            result = generate_marketing_payload(self.ws, poster_brief())

        self.assertEqual(result['payload']['postTitle'], HEADLINE)
        first_brief, second_brief = router.image_briefs()
        self.assertEqual(first_brief['headline'], HEADLINE)
        self.assertEqual(second_brief['headline'], HEADLINE)
        self.assertTrue(paints(second_brief, HEADLINE))

        # Whitespace-collapsed, on both of the retry's buys.
        router, checker = Router([FIRST, SECOND]), Checker([ALTERED, OK])
        with router.patched(), checker.patched():
            retry_image(
                self.ws, self.brand, poster_brief(headline=f'  Roasted\n this  week '),
                trace={},
            )
        self.assertEqual([b['headline'] for b in router.image_briefs()], [HEADLINE, HEADLINE])

        # Nothing to paint, nothing to fix: a copy-less picture and the
        # compose engine's poster carry the no-text line and no key.
        router = Router([FIRST], text_error=RuntimeError('copy provider down'))
        outcome = self.generate(router, Checker([OK]))
        self.assertIsNone(outcome['text'])
        (brief,) = router.image_briefs()
        self.assertNotIn('headline', brief)
        router = Router([FIRST])
        self.generate(
            router, Checker([OK]),
            poster_brief(creative_direction={'mode': 'CATALOG_TEMPLATE', 'layout': 'x'}),
        )
        (brief,) = router.image_briefs()
        self.assertNotIn('headline', brief)

    def test_a_template_poster_tolerates_its_own_text_slots(self):
        """A brand template's own slots ("Free shipping across India") are
        words the judge cannot know: `extra_text` ships as ok with no re-buy.
        A missing or altered headline still buys once more, and a second
        picture that only filled the slots ships as ok too. INSPIRED
        fidelity attaches no template, so its extra words are extra words."""
        router, checker = Router([FIRST]), Checker([EXTRA])
        outcome = self.generate(router, checker, template_brief())

        self.assertEqual(len(router.image_briefs()), 1)
        self.assertEqual(outcome['image']['image_url'], FIRST_URL)
        self.assertEqual(outcome['trace']['image_text'], {
            'verdict': 'extra_text', 'found': EXTRA['found'], 'expected': HEADLINE,
            'retried': False, 'final_verdict': 'ok', 'reason': 'template slots tolerated',
        })

        router, checker = Router([FIRST, SECOND]), Checker([ALTERED, EXTRA])
        outcome = self.generate(router, checker, template_brief())
        self.assertEqual(len(router.image_briefs()), 2)
        self.assertEqual(outcome['image']['image_url'], SECOND_URL)
        record = outcome['trace']['image_text']
        self.assertEqual(record['verdict'], 'headline_altered')
        self.assertEqual(record['reason'], ALTERED['reason'])
        self.assertTrue(record['retried'])
        self.assertEqual(record['kept'], 'second')
        self.assertEqual(record['final_verdict'], 'ok')
        self.assertEqual(record['final_reason'], 'template slots tolerated')

        router, checker = Router([FIRST, SECOND]), Checker([MISSING, OK])
        outcome = self.generate(router, checker, template_brief())
        self.assertEqual(len(router.image_briefs()), 2)
        self.assertEqual(outcome['image']['image_url'], SECOND_URL)

        router, checker = Router([FIRST, SECOND]), Checker([EXTRA, OK])
        outcome = self.generate(router, checker, template_brief(template_fidelity='INSPIRED'))
        self.assertEqual(len(router.image_briefs()), 2)
        self.assertEqual(outcome['image']['image_url'], SECOND_URL)
        self.assertEqual(outcome['trace']['image_text']['reason'], EXTRA['reason'])

    def test_a_template_never_tolerates_a_duplicated_cta(self):
        """The live failure the tolerance hid: the Sumaya template carries a
        booking line and a shopping link, both were painted, and extra_text
        was forgiven as slots. cta_duplicated is not a slot — it re-buys
        even in template mode, and a clean second picture ships."""
        router, checker = Router([FIRST, SECOND]), Checker([CTA_DUP, OK])
        outcome = self.generate(router, checker, template_brief())

        self.assertEqual(len(router.image_briefs()), 2)
        self.assertEqual(outcome['image']['image_url'], SECOND_URL)
        record = outcome['trace']['image_text']
        self.assertEqual(record['verdict'], 'cta_duplicated')
        self.assertTrue(record['retried'])
        self.assertEqual(record['kept'], 'second')
        self.assertEqual(record['final_verdict'], 'ok')

        # A re-buy that still doubles the CTA ties and ships as the second
        # picture, recorded honestly.
        router, checker = Router([FIRST, SECOND]), Checker([CTA_DUP, CTA_DUP])
        outcome = self.generate(router, checker, template_brief())
        self.assertEqual(len(router.image_briefs()), 2)
        self.assertEqual(
            outcome['trace']['image_text']['final_verdict'], 'cta_duplicated'
        )

    def test_a_skipped_check_buys_nothing_more(self):
        router, checker = Router([FIRST]), Checker([SKIPPED])
        outcome = self.generate(router, checker)

        self.assertEqual(len(router.image_briefs()), 1)
        self.assertEqual(outcome['image']['image_url'], FIRST_URL)
        self.assertEqual(outcome['trace']['image_text'], {
            'verdict': 'skipped', 'found': [], 'expected': HEADLINE,
            'retried': False, 'final_verdict': 'skipped',
            'reason': SKIPPED['reason'],
        })

    def test_a_crashing_check_never_costs_the_poster(self):
        router, checker = Router([FIRST]), Checker([RuntimeError('vision down')])
        outcome = self.generate(router, checker)

        self.assertEqual(len(router.image_briefs()), 1)
        self.assertEqual(outcome['image']['image_url'], FIRST_URL)
        self.assertEqual(outcome['trace']['capabilities'][Capability.IMAGE]['status'], 'OK')
        record = outcome['trace']['image_text']
        self.assertEqual(record['verdict'], 'skipped')
        self.assertEqual(record['final_verdict'], 'skipped')
        self.assertFalse(record['retried'])
        self.assertIn('RuntimeError', record['reason'])
        self.assertIn('vision down', record['reason'])

    def test_an_absent_checker_module_reads_as_skipped(self):
        # `sys.modules[name] = None` makes the lazy import raise ImportError:
        # a build without the checker generates exactly as before.
        router = Router([FIRST])
        with router.patched(), patch.dict(sys.modules, {IMAGE_TEXT: None}):
            outcome = generate_copy_and_image(
                self.ws, self.brand, poster_brief(), instruction='Launch',
            )

        self.assertEqual(len(router.image_briefs()), 1)
        self.assertEqual(outcome['image']['image_url'], FIRST_URL)
        record = outcome['trace']['image_text']
        self.assertEqual(record['verdict'], 'skipped')
        self.assertFalse(record['retried'])
        self.assertEqual(record['reason'], 'image text check unavailable')

    def test_a_poster_that_paints_no_words_is_never_checked(self):
        # The compose engine owns the words: the picture was told no text.
        router, checker = Router([FIRST]), Checker([OK])
        outcome = self.generate(
            router, checker,
            poster_brief(creative_direction={'mode': 'CATALOG_TEMPLATE', 'layout': 'x'}),
        )
        self.assertEqual(len(router.image_briefs()), 1)
        self.assertEqual(outcome['image']['image_url'], FIRST_URL)
        self.assertEqual(checker.calls, [])
        self.assertNotIn('image_text', outcome['trace'])

        # Copy-less: the TEXT call failed, so the image carries the no-text
        # line and there is no headline to look for.
        router = Router([FIRST], text_error=RuntimeError('copy provider down'))
        checker = Checker([OK])
        outcome = self.generate(router, checker)
        self.assertIsNone(outcome['text'])
        self.assertEqual(outcome['image']['image_url'], FIRST_URL)
        self.assertEqual(checker.calls, [])
        self.assertNotIn('image_text', outcome['trace'])

        # A carousel slide re-bought on its own: deliberately unchanged.
        router, checker, trace = Router([FIRST]), Checker([OK]), {}
        with router.patched(), checker.patched():
            image = retry_image(
                self.ws, self.brand,
                {'contentType': 'carousel_slide', 'headline': HEADLINE},
                trace=trace,
            )
        self.assertEqual(image['image_url'], FIRST_URL)
        self.assertEqual(len(router.image_briefs()), 1)
        self.assertEqual(checker.calls, [])
        self.assertNotIn('image_text', trace)

    def test_a_failed_rebuy_keeps_the_first_picture_and_its_record(self):
        router = Router([FIRST, RuntimeError('image provider down')])
        checker = Checker([ALTERED])
        outcome = self.generate(router, checker)

        # Two dispatches were attempted; the second failed; the first stands.
        self.assertEqual(len(router.image_briefs()), 2)
        self.assertEqual(outcome['image']['image_url'], FIRST_URL)
        self.assertEqual(outcome['trace']['capabilities'][Capability.IMAGE], {
            'status': 'OK', 'provider': 'STABILITY', 'latency_ms': 20,
        })
        record = outcome['trace']['image_text']
        self.assertEqual(record['verdict'], 'headline_altered')
        self.assertTrue(record['retried'])
        self.assertEqual(record['kept'], 'first')
        self.assertEqual(record['final_verdict'], 'headline_altered')
        self.assertIn('image provider down', record['rebuy_error'])
        self.assertEqual(len(checker.calls), 1)

    def test_a_rebuy_that_persists_badly_keeps_the_first_picture(self):
        router, checker = Router([FIRST, SECOND]), Checker([ALTERED])
        persisted = []

        def persist(workspace, result):
            persisted.append(result)
            if len(persisted) > 1:
                raise OutputRejected('Provider image could not be copied to durable storage.')
            return dict(result)

        with router.patched(), checker.patched(), patch(PERSIST, persist):
            outcome = generate_copy_and_image(
                self.ws, self.brand, poster_brief(), instruction='Launch',
            )

        self.assertEqual(len(router.image_briefs()), 2)
        self.assertEqual(len(persisted), 2)
        self.assertEqual(outcome['image']['image_url'], FIRST_URL)
        self.assertEqual(outcome['trace']['capabilities'][Capability.IMAGE]['status'], 'OK')
        record = outcome['trace']['image_text']
        self.assertTrue(record['retried'])
        self.assertEqual(record['kept'], 'first')
        self.assertEqual(record['final_verdict'], 'headline_altered')
        self.assertIn('OutputRejected', record['rebuy_error'])

    def test_retry_image_checks_and_rebuys_once(self):
        router, checker, trace = Router([FIRST, SECOND]), Checker([ALTERED, OK]), {}
        with router.patched(), checker.patched():
            image = retry_image(
                self.ws, self.brand,
                poster_brief(headline=HEADLINE), instruction='Launch', trace=trace,
            )

        first_brief, second_brief = router.image_briefs()
        self.assertTrue(paints(first_brief, HEADLINE))
        self.assertTrue(paints(second_brief, HEADLINE))
        self.assertEqual(
            first_brief['composition_archetype'], second_brief['composition_archetype'],
        )
        self.assertEqual(image['image_url'], SECOND_URL)
        # The trace the caller passed carries the check next to the variety
        # picks it already reported.
        self.assertIn('composition_archetype', trace)
        record = trace['image_text']
        self.assertEqual(record['verdict'], 'headline_altered')
        self.assertTrue(record['retried'])
        self.assertEqual(record['final_verdict'], 'ok')
        self.assertEqual(record['expected'], HEADLINE)
        (first_call, second_call) = checker.calls
        self.assertEqual(first_call['image']['image_url'], FIRST_URL)
        self.assertEqual(second_call['image']['image_url'], SECOND_URL)
        self.assertEqual(first_call['cta'], 'MORE INFO')
        self.assertEqual(first_call['offer'], '30% off')

        # Without a trace dict the retry still checks, and still returns.
        router, checker = Router([FIRST]), Checker([OK])
        with router.patched(), checker.patched():
            image = retry_image(self.ws, self.brand, poster_brief(headline=HEADLINE))
        self.assertEqual(image['image_url'], FIRST_URL)
        self.assertEqual(len(checker.calls), 1)

    def test_a_combined_provider_rebuys_through_the_router(self):
        """One provider serves TEXT and IMAGE and paints the poster inside its
        TEXT call (`raw.posterImageUrl`): no IMAGE dispatch is made for the
        first picture, and a failing verdict buys the re-draw as the ONE
        IMAGE dispatch of the generation."""
        adapter = SimpleNamespace(key='gemini', yields_poster_with_text=True)
        painted = {**COPY, 'raw': {'postTitle': HEADLINE, 'posterImageUrl': FIRST_URL}}
        router = Router([SECOND], copy_result=painted)
        checker = Checker([ALTERED, OK])
        with router.patched(), checker.patched(), \
                patch(PRIMARY, lambda _router, capability: adapter):
            result = generate_marketing_payload(self.ws, poster_brief())

        (rebuy_brief,) = router.image_briefs()
        self.assertTrue(paints(rebuy_brief, HEADLINE), rebuy_brief.get('brand_context'))
        self.assertEqual(result['payload']['posterImageUrl'], SECOND_URL)
        self.assertEqual(result['payload']['postTitle'], HEADLINE)
        self.assertEqual(result['trace']['capabilities'][Capability.IMAGE]['status'], 'OK')
        record = result['trace']['image_text']
        self.assertEqual(record['verdict'], 'headline_altered')
        self.assertTrue(record['retried'])
        self.assertEqual(record['final_verdict'], 'ok')
        # The first check read the poster the TEXT call painted.
        self.assertEqual(
            [call['image']['image_url'] for call in checker.calls], [FIRST_URL, SECOND_URL],
        )

    def test_found_words_are_trimmed_in_the_trace(self):
        long_line = 'x' * 500
        noisy = verdict(
            'extra_text', found=[long_line] + [f'line {n}' for n in range(20)],
            reason='r' * 500,
        )
        router, checker = Router([FIRST, SECOND]), Checker([noisy, OK])
        outcome = self.generate(router, checker)

        record = outcome['trace']['image_text']
        self.assertEqual(len(record['found']), 12)
        self.assertEqual(len(record['found'][0]), 120)
        self.assertEqual(len(record['reason']), 300)
