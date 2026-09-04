"""
Independent verification: the copy self-critique settles the words BEFORE
the image is bought, on every poster route.

Black-box, through the public entry points only — the poster path of
`generate_marketing_payload` with two providers (one TEXT, one IMAGE), and
the combined Gemini route where `GeminiAdapter` drives the real
`GeminiGeneratorService.generate_marketing_content` with only the genai
client faked. Everything is mocked at the router/provider boundary
(`AIRouter.dispatch`, `AIRouter.primary_adapter`, the genai client, storage),
never inside the modules under test, so these tests describe the contract
and not one implementation of it.

The contract:

  * the self-critique — judge, at most one copy-only rewrite, in-memory
    re-judge — completes BEFORE the image is generated;
  * the image brief / image call carries the FINAL headline (post-rewrite),
    never the first draft;
  * exactly one image is bought per generation;
  * fail-open holds: a judge failure before the image never blocks the image.

Every test fails against the old ordering (critique after the image) and
passes once the words are settled ahead of the image spend.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.ai.adapters.gemini import GeminiAdapter
from apps.ai.models import Capability
from apps.ai.router import NoProviderAvailable
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.context.services.generation import generate_marketing_payload
from apps.gemini.services.generator import GeminiGeneratorService

DISPATCH = 'apps.ai.router.AIRouter.dispatch'
PRIMARY = 'apps.ai.router.AIRouter.primary_adapter'
STORAGE = 'apps.marketing.services.storage.SupabaseStorageService.upload_and_describe'

ORIGINAL = 'Opening Draft Headline'
FINAL = 'FINAL HEADLINE'

VERDICT_PASS = {'passes': True, 'violations': [], 'rewrite_instruction': ''}
VERDICT_HARD = {
    'passes': False,
    'violations': [{
        'rule': 'MUST: never shout in the headline',
        'element': 'headline',
        'severity': 'HARD',
        'fix': 'Rewrite the headline calmly.',
    }],
    'rewrite_instruction': 'Rewrite the headline calmly.',
}

#: The TEXT provider's first copy and its copy-only rewrite, in the
#: provider-neutral shape every adapter returns.
FIRST_COPY = {
    'headline': ORIGINAL, 'caption': 'The first caption.', 'hashtags': '#first',
    'raw': {}, 'provider': 'openai', 'provider_name': 'OpenAI', 'latency_ms': 5,
}
REWRITTEN_COPY = {
    **FIRST_COPY, 'headline': FINAL, 'caption': 'The final caption.',
    'hashtags': '#final',
}
#: A stable https URL: persistence leaves it alone, so no storage is touched.
IMAGE_RESULT = {
    'image_url': 'https://cdn.example.com/bought-once.png',
    'provider': 'stability', 'provider_name': 'Stability', 'latency_ms': 7,
}
STORED_POSTER = 'https://cdn.example.com/stored-poster.png'

#: A delegated poster: its headline is typography the image model paints, so
#: the image brief must quote it verbatim.
BRIEF = {
    'campaign_name': 'Launch', 'contentType': 'poster', 'offer': '20% off',
    'creative_direction': {'mode': 'AI_ORIGINAL', 'selections': []},
}


def kind_of(capability, brief):
    """What a dispatch was for. The judge is the TEXT EXTRACT dispatch the
    critique module documents; the rewrite is the copy-only TEXT call."""
    if capability == Capability.IMAGE:
        return 'image'
    if capability != Capability.TEXT:
        return str(capability)
    if str(brief.get('task') or '').upper() == 'EXTRACT':
        return 'judge'
    if brief.get('copy_only'):
        return 'rewrite'
    return 'copy'


class RouterStandIn:
    """Plays the provider side of the whole exchange and records every
    dispatch, in order.

    `verdicts` is the judge's script, consumed one per judge dispatch; an
    Exception instance is raised in the judge's place. `copy`, when given,
    answers the first copy AND the copy-only rewrite (the combined route
    sends both to the same provider); otherwise the canned copies answer.
    `timeline`, when shared with a `FakeGenAIClient`, interleaves router
    dispatches with the provider's own steps — the only way to see whether
    a poster painted INSIDE a TEXT call came before or after the judge.
    """

    def __init__(self, verdicts, *, copy=None, timeline=None):
        self.verdicts = list(verdicts)
        self.copy = copy
        self.calls = []
        self.timeline = timeline if timeline is not None else []

    def dispatch(self, capability, brief, content_item_id=None, *, internal=False):
        kind = kind_of(capability, brief)
        self.calls.append({
            'kind': kind, 'capability': capability, 'brief': brief,
            'internal': internal,
        })
        self.timeline.append(kind)
        if kind == 'judge':
            verdict = self.verdicts.pop(0)
            if isinstance(verdict, Exception):
                raise verdict
            return {'raw': dict(verdict)}
        if kind == 'copy':
            return self.copy(brief) if self.copy else dict(FIRST_COPY)
        if kind == 'rewrite':
            return self.copy(brief) if self.copy else dict(REWRITTEN_COPY)
        if kind == 'image':
            return dict(IMAGE_RESULT)
        raise NoProviderAvailable(f'No provider routed for {capability}.')

    def kinds(self):
        return [call['kind'] for call in self.calls]

    def briefs(self, kind):
        return [call['brief'] for call in self.calls if call['kind'] == kind]

    def patched(self):
        stand_in = self

        def dispatch(_router, capability, brief, content_item_id=None, *,
                     internal=False):
            return stand_in.dispatch(
                capability, brief, content_item_id, internal=internal,
            )

        return patch(DISPATCH, dispatch)


def flattened(brief):
    """Everything a brief carries, as one string, so a headline is found
    wherever the implementation chose to put it."""
    return json.dumps(brief, default=str, sort_keys=True)


def paints(brief, headline):
    """Whether the IMAGE brief's brand-context lines quote `headline` as the
    words to render on the poster."""
    return any(
        f'"{headline}"' in str(line) for line in brief.get('brand_context') or []
    )


class TwoProviderCritiqueOrderingTests(TenantFixtureMixin, TestCase):
    """One TEXT provider, a different IMAGE provider: two dispatches, and the
    whole critique must sit between them."""

    def setUp(self):
        self.workspace = self.make_workspace('Rajvi', 'rajvi-ordering')
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Rajvi Packaging', is_default=True,
            status=Brand.Status.ACTIVE,
        )

    def generate(self):
        return generate_marketing_payload(self.workspace, dict(BRIEF))

    def test_the_image_brief_carries_the_final_headline_never_the_first_draft(self):
        """A HARD verdict earns one rewrite; the one IMAGE dispatch is then
        asked to paint the rewritten headline and never sees the draft."""
        router = RouterStandIn([dict(VERDICT_HARD), dict(VERDICT_PASS)])
        with router.patched():
            result = self.generate()

        image_briefs = router.briefs('image')
        self.assertEqual(len(image_briefs), 1, router.kinds())
        (brief,) = image_briefs
        self.assertIn(FINAL, flattened(brief))
        self.assertTrue(paints(brief, FINAL), brief.get('brand_context'))
        self.assertNotIn(ORIGINAL, flattened(brief))

        # Spend: the copy, one rewrite, the judge and its in-memory re-judge,
        # one image — nothing else.
        self.assertEqual(
            sorted(router.kinds()),
            sorted(['copy', 'rewrite', 'judge', 'judge', 'image']),
        )
        self.assertEqual(result['payload']['postTitle'], FINAL)
        self.assertEqual(result['payload']['posterImageUrl'], IMAGE_RESULT['image_url'])
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'regenerated')
        self.assertTrue(critique['retried'])

    def test_every_critique_dispatch_precedes_the_one_image_dispatch(self):
        """Copy, judge, rewrite, re-judge, image: the image is last, and the
        re-judge graded the rewrite (in memory), not the draft."""
        router = RouterStandIn([dict(VERDICT_HARD), dict(VERDICT_PASS)])
        with router.patched():
            self.generate()

        self.assertEqual(
            router.kinds(), ['copy', 'judge', 'rewrite', 'judge', 'image'],
        )
        first_judge, second_judge = router.briefs('judge')
        self.assertEqual(first_judge['structured']['copy']['headline'], ORIGINAL)
        self.assertEqual(second_judge['structured']['copy']['headline'], FINAL)
        # Judging is internal QA spend; the copy, the rewrite and the image
        # remain customer units. The ordering moved, the metering did not.
        self.assertEqual(
            [call['internal'] for call in router.calls],
            [False, True, False, True, False],
        )

    def test_a_judge_outage_before_the_image_still_buys_the_image_with_the_first_headline(self):
        """Fail-open ahead of the spend: no provider for the judge costs
        nothing and blocks nothing — one image, the draft headline, and a
        trace that says the verdict was skipped."""
        router = RouterStandIn([NoProviderAvailable('No provider routed for TEXT.')])
        with router.patched():
            result = self.generate()

        self.assertEqual(router.kinds(), ['copy', 'judge', 'image'])
        (brief,) = router.briefs('image')
        self.assertTrue(paints(brief, ORIGINAL), brief.get('brand_context'))
        self.assertEqual(
            result['trace']['capabilities'][Capability.IMAGE]['status'], 'OK',
        )
        self.assertEqual(result['payload']['posterImageUrl'], IMAGE_RESULT['image_url'])
        self.assertEqual(result['payload']['postTitle'], ORIGINAL)
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'skipped')
        self.assertIn('NoProviderAvailable', critique['skipped_reason'])

    def test_a_passing_verdict_precedes_the_image_and_buys_no_rewrite(self):
        router = RouterStandIn([dict(VERDICT_PASS)])
        with router.patched():
            result = self.generate()

        self.assertEqual(router.kinds(), ['copy', 'judge', 'image'])
        self.assertNotIn('rewrite', router.kinds())
        (brief,) = router.briefs('image')
        self.assertTrue(paints(brief, ORIGINAL), brief.get('brand_context'))
        self.assertEqual(result['payload']['postTitle'], ORIGINAL)
        self.assertEqual(result['payload']['posterImageUrl'], IMAGE_RESULT['image_url'])
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'passed')
        self.assertFalse(critique['retried'])


class FakeGenAIClient:
    """The google.genai client, faked at the boundary. Step 1 (the text
    model) answers from a script of copies; Step 2 (the image model) records
    the exact contents it was asked to paint and returns one inline PNG."""

    def __init__(self, copies):
        self.copies = list(copies)
        self.step_one_contents = []
        self.step_two_contents = []
        self.models = self

    def generate_content(self, model, contents, config=None):
        if model == GeminiGeneratorService.IMAGE_MODEL:
            self.step_two_contents.append(contents[0])
            part = SimpleNamespace(inline_data=SimpleNamespace(
                mime_type='image/png', data=b'poster-bytes',
            ))
            return SimpleNamespace(candidates=[
                SimpleNamespace(content=SimpleNamespace(parts=[part])),
            ])
        self.step_one_contents.append(contents[0])
        copy = self.copies.pop(0)
        return SimpleNamespace(text=json.dumps({
            'postTitle': copy['headline'],
            'postDescription': copy['caption'],
            'postHashtags': copy['hashtags'],
            'imagePrompt': 'A calm studio scene.',
        }))


class CombinedGeminiCritiqueOrderingTests(TenantFixtureMixin, TestCase):
    """Gemini serves TEXT and IMAGE from one pipeline: Step 1 writes the copy,
    Step 2 paints the poster inside the same provider call. The real adapter
    and the real service run; only the genai client, the router's routing
    and storage are faked."""

    def setUp(self):
        self.workspace = self.make_workspace('Rajvi', 'rajvi-combined')
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Rajvi Packaging', is_default=True,
            status=Brand.Status.ACTIVE,
        )
        self.adapter = GeminiAdapter()

    def generate(self, router, client):
        with router.patched(), \
                patch(PRIMARY, lambda _router, capability: self.adapter), \
                patch.object(GeminiGeneratorService, '_get_client', return_value=client), \
                patch(STORAGE, return_value={
                    'url': STORED_POSTER, 'path': 'generated/stored-poster.png',
                }) as stored, \
                override_settings(GEMINI_API_KEY='key', GEMINI_MOCK_MODE=False):
            result = generate_marketing_payload(self.workspace, dict(BRIEF))
        return result, stored

    def test_step_two_paints_the_post_critique_headline_and_runs_once(self):
        """The judge rewrites between Step 1 and Step 2: the one poster call
        carries the final headline, the copy-only rewrite never buys a second
        poster, and no separate IMAGE dispatch is made."""
        client = FakeGenAIClient([FIRST_COPY, REWRITTEN_COPY])
        router = RouterStandIn(
            [dict(VERDICT_HARD), dict(VERDICT_PASS)],
            copy=lambda brief: self.adapter.run(Capability.TEXT, brief),
        )
        result, stored = self.generate(router, client)

        self.assertEqual(len(client.step_two_contents), 1, client.step_two_contents)
        (sent,) = client.step_two_contents
        self.assertIn(f'"{FINAL}"', sent)
        self.assertNotIn(ORIGINAL, sent)
        # Step 1 ran twice — the copy, then the copy-only rewrite — and the
        # judge twice; the poster was bought inside the TEXT call, once.
        self.assertEqual(len(client.step_one_contents), 2)
        self.assertEqual(router.kinds(), ['copy', 'judge', 'rewrite', 'judge'])
        self.assertEqual(stored.call_count, 1)
        self.assertEqual(result['payload']['postTitle'], FINAL)
        self.assertEqual(result['payload']['posterImageUrl'], STORED_POSTER)
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'regenerated')
        self.assertTrue(critique['retried'])
        self.assertEqual(
            result['trace']['capabilities'][Capability.IMAGE]['status'], 'OK',
        )

    def test_a_judge_outage_inside_the_call_still_paints_the_first_headline_once(self):
        """Fail-open on the riskiest route: a judge failure between the two
        steps must not read as a provider failure (which would fail over
        into a second paid generation). One Step 2 call, the draft headline,
        verdict skipped."""
        client = FakeGenAIClient([FIRST_COPY])
        router = RouterStandIn(
            [NoProviderAvailable('No provider routed for TEXT.')],
            copy=lambda brief: self.adapter.run(Capability.TEXT, brief),
        )
        result, stored = self.generate(router, client)

        self.assertEqual(len(client.step_two_contents), 1, client.step_two_contents)
        (sent,) = client.step_two_contents
        self.assertIn(f'"{ORIGINAL}"', sent)
        self.assertEqual(len(client.step_one_contents), 1)
        self.assertEqual(router.kinds(), ['copy', 'judge'])
        self.assertEqual(stored.call_count, 1)
        self.assertEqual(result['payload']['postTitle'], ORIGINAL)
        self.assertEqual(result['payload']['posterImageUrl'], STORED_POSTER)
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'skipped')
        self.assertIn('NoProviderAvailable', critique['skipped_reason'])
