"""
The LLM self-critique gate: judged copy, one copy-only retry, never a failure.

Every test patches the router the judge dispatches through — no provider is
ever called — and proves the two properties the gate exists for: a failing
verdict spends at most ONE copy-only regeneration, and no judge failure of
any shape (quota, routing, malformed JSON, the toggle) ever touches the paid
output or fails the generation.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps.ai.models import Capability
from apps.ai.router import NoProviderAvailable
from apps.billing.quota import QuotaExceeded
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.context.services.critique import standing_complaints
from apps.context.services.generation import generate_marketing_payload
from apps.learning.models import BrandRule
from apps.universal.models import ClientQualitySettings

ROUTE = 'apps.context.services.generation._route_marketing_payload'
RETRY = 'apps.context.services.generation.generate_copy_only'
JUDGE_ROUTER = 'apps.context.services.critique.AIRouter'

JUDGE_PASS = {'passes': True, 'violations': [], 'rewrite_instruction': ''}
JUDGE_FAIL = {
    'passes': False,
    'violations': [{
        'rule': 'MUST: never promise a delivery date',
        'element': 'caption',
        'severity': 'HARD',
        'fix': 'Remove the delivery promise.',
    }],
    'rewrite_instruction': 'Drop the delivery date claim.',
}

PAYLOAD = {
    'postTitle': 'Delivered by Friday',
    'postDescription': 'Order now, at your door by Friday.',
    'postHashtags': '#foam',
}
CLEAN = {
    'postTitle': 'Precision packaging',
    'postDescription': 'Made to fit, made to last.',
    'postHashtags': '#foam',
}


class CritiqueGateTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Rajvi', 'rajvi-critique')
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Rajvi Packaging', is_default=True,
            status=Brand.Status.ACTIVE,
        )

    def routed(self, payload):
        return {
            'provider': 'gemini', 'provider_name': 'Gemini',
            'brain_version': '', 'trace': {'capabilities': {}},
            'copy_brief_context': ['MUST: never promise a delivery date'],
            'payload': dict(payload),
        }

    def generate(self):
        return generate_marketing_payload(
            self.workspace, {'campaign_name': 'Launch', 'contentType': 'poster'}
        )

    def test_passing_copy_records_passed_and_buys_nothing_extra(self):
        with patch(ROUTE, return_value=self.routed(CLEAN)), \
                patch(RETRY) as retry, patch(JUDGE_ROUTER) as router:
            router.return_value.dispatch.return_value = {'raw': dict(JUDGE_PASS)}
            result = self.generate()

        retry.assert_not_called()
        router.return_value.dispatch.assert_called_once()
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'passed')
        self.assertEqual(critique['violations'], [])
        self.assertFalse(critique['retried'])
        self.assertIsNone(critique['skipped_reason'])
        self.assertEqual(result['payload'], CLEAN)
        # The one judge dispatch is a schema'd EXTRACT — the shape OpenAI's
        # EXTRACT branch hard-requires — citing what the generator saw.
        brief = router.return_value.dispatch.call_args.args[1]
        self.assertEqual(brief['task'], 'EXTRACT')
        self.assertIsInstance(brief['response_schema'], dict)
        self.assertIn(
            'MUST: never promise a delivery date',
            brief['structured']['brand_rules'],
        )
        self.assertNotIn('copy_brief_context', result)

    def test_a_hard_violation_gets_exactly_one_copy_retry(self):
        with patch(ROUTE, return_value=self.routed(PAYLOAD)), \
                patch(RETRY, return_value=dict(CLEAN)) as retry, \
                patch(JUDGE_ROUTER) as router:
            router.return_value.dispatch.side_effect = [
                {'raw': dict(JUDGE_FAIL)}, {'raw': dict(JUDGE_PASS)},
            ]
            result = self.generate()

        retry.assert_called_once()
        # The retry brief names each refusal the way guardrail_feedback does.
        feedback = retry.call_args.args[2]['guardrail_feedback']
        self.assertTrue(any('delivery date' in line for line in feedback))
        self.assertEqual(result['payload']['postTitle'], 'Precision packaging')
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'regenerated')
        self.assertTrue(critique['retried'])
        self.assertEqual(len(critique['violations']), 1)
        # Judge + in-memory re-judge: two dispatches, never a third.
        self.assertEqual(router.return_value.dispatch.call_count, 2)

    def test_quota_exhaustion_skips_and_keeps_the_paid_output(self):
        with patch(ROUTE, return_value=self.routed(PAYLOAD)), \
                patch(RETRY) as retry, patch(JUDGE_ROUTER) as router:
            router.return_value.dispatch.side_effect = QuotaExceeded(
                SimpleNamespace(message='TEXT allowance exhausted')
            )
            result = self.generate()

        retry.assert_not_called()
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'skipped')
        self.assertIn('QuotaExceeded', critique['skipped_reason'])
        self.assertEqual(result['payload'], PAYLOAD)

    def test_no_provider_skips_and_keeps_the_paid_output(self):
        with patch(ROUTE, return_value=self.routed(PAYLOAD)), \
                patch(RETRY) as retry, patch(JUDGE_ROUTER) as router:
            router.return_value.dispatch.side_effect = NoProviderAvailable(
                'No provider routed for TEXT.'
            )
            result = self.generate()

        retry.assert_not_called()
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'skipped')
        self.assertIn('NoProviderAvailable', critique['skipped_reason'])
        self.assertEqual(result['payload'], PAYLOAD)

    def test_the_toggle_off_means_zero_judge_dispatches(self):
        ClientQualitySettings.objects.create(
            workspace=self.workspace, critique_enabled=False,
        )
        with patch(ROUTE, return_value=self.routed(PAYLOAD)), \
                patch(RETRY) as retry, patch(JUDGE_ROUTER) as router:
            result = self.generate()

        retry.assert_not_called()
        router.assert_not_called()
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'skipped')
        self.assertEqual(critique['skipped_reason'], 'disabled')
        self.assertEqual(result['payload'], PAYLOAD)

    def test_a_crash_outside_the_judge_guard_skips_instead_of_failing(self):
        """The whole gate is fail-open: even the settings read crashing must
        record 'skipped' and ship the paid output, never fail the generation."""
        with patch(ROUTE, return_value=self.routed(PAYLOAD)), \
                patch(RETRY) as retry, patch(JUDGE_ROUTER) as router, \
                patch(
                    'apps.universal.services.quality_settings_for',
                    side_effect=RuntimeError('settings table unavailable'),
                ):
            result = self.generate()

        retry.assert_not_called()
        router.return_value.dispatch.assert_not_called()
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'skipped')
        self.assertEqual(critique['skipped_reason'], 'RuntimeError')
        self.assertEqual(result['payload'], PAYLOAD)

    def test_video_and_carousel_get_an_honest_format_skip(self):
        """Uncovered formats say so, instead of masquerading as an infra skip."""
        for content_type in ('video', 'carousel'):
            with self.subTest(content_type=content_type):
                routed = self.routed(PAYLOAD)
                routed.pop('copy_brief_context')
                with patch(ROUTE, return_value=routed), \
                        patch(RETRY) as retry, patch(JUDGE_ROUTER) as router:
                    result = generate_marketing_payload(
                        self.workspace,
                        {'campaign_name': 'Launch', 'contentType': content_type},
                    )
                retry.assert_not_called()
                router.return_value.dispatch.assert_not_called()
                critique = result['trace']['critique']
                self.assertEqual(critique['verdict'], 'skipped')
                self.assertEqual(critique['skipped_reason'], 'format_not_covered')
                self.assertEqual(result['payload'], PAYLOAD)

    def test_malformed_judge_json_skips_and_keeps_the_paid_output(self):
        with patch(ROUTE, return_value=self.routed(PAYLOAD)), \
                patch(RETRY) as retry, patch(JUDGE_ROUTER) as router:
            router.return_value.dispatch.return_value = {'raw': 'not json {'}
            result = self.generate()

        retry.assert_not_called()
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'skipped')
        self.assertEqual(critique['skipped_reason'], 'malformed_judge_output')
        self.assertEqual(result['payload'], PAYLOAD)


DISPATCH = 'apps.ai.router.AIRouter.dispatch'
PRIMARY = 'apps.ai.router.AIRouter.primary_adapter'

FIRST_TEXT = {
    'headline': PAYLOAD['postTitle'], 'caption': PAYLOAD['postDescription'],
    'hashtags': PAYLOAD['postHashtags'], 'raw': {}, 'provider': 'OPENAI',
    'provider_name': 'OpenAI', 'latency_ms': 10,
}
CLEAN_TEXT = {
    **FIRST_TEXT, 'headline': CLEAN['postTitle'],
    'caption': CLEAN['postDescription'], 'hashtags': CLEAN['postHashtags'],
}
FAKE_IMAGE = {
    'image_url': 'https://cdn.example.com/poster.png',
    'provider': 'STABILITY', 'provider_name': 'Stability', 'latency_ms': 20,
}
ONE_CALL_POSTER = 'https://cdn.example.com/one-call.png'


def kind_of(call):
    """What a dispatch was for: the copy, a judge verdict, the copy-only
    rewrite (guardrail or critique), or the image."""
    brief = call['brief']
    if str(brief.get('task') or '').upper() == 'EXTRACT':
        return 'JUDGE'
    if brief.get('copy_only'):
        return 'REWRITE'
    return call['capability']


def conversation_router(calls, verdicts, combined=False):
    """A stand-in router playing the whole exchange: the first copy, the
    judge's verdicts in order (an Exception instance is raised instead), the
    copy-only rewrite, and the image. With `combined`, the TEXT call behaves
    like a provider that paints the poster inside its own call: it invokes
    the brief's `pre_image_hook` between its text and image steps and paints
    whatever the hook returned."""

    def dispatch(self_router, capability, brief, content_item_id=None, *,
                 internal=False):
        call = {'capability': capability, 'brief': brief, 'internal': internal}
        calls.append(call)
        kind = kind_of(call)
        if kind == 'JUDGE':
            verdict = verdicts.pop(0)
            if isinstance(verdict, Exception):
                raise verdict
            return {'raw': dict(verdict)}
        if kind == 'REWRITE':
            return dict(CLEAN_TEXT)
        if capability == Capability.TEXT:
            if not combined:
                return dict(FIRST_TEXT)
            settled = brief['pre_image_hook'](dict(PAYLOAD))
            call['painted'] = settled['postTitle']
            return {
                **FIRST_TEXT, 'provider': 'gemini',
                'headline': settled['postTitle'],
                'caption': settled['postDescription'],
                'hashtags': settled['postHashtags'],
                'raw': {**settled, 'posterImageUrl': ONE_CALL_POSTER},
            }
        if capability == Capability.IMAGE:
            return dict(FAKE_IMAGE)
        raise NoProviderAvailable(f'no {capability}')

    return dispatch


class CombinedAdapter:
    key = 'combined'
    yields_poster_with_text = True


class CritiqueBeforeImageTests(TenantFixtureMixin, TestCase):
    """The copy is settled — guardrails, judge, their one rewrite — BEFORE
    the image is bought, so the headline the image model paints is the
    headline that ships.

    Production evidence (2026-09-04): a poster rendered the first headline
    while the item shipped with the judge's rewrite, because the image had
    already been bought on the first draft. Every dispatch is recorded so
    the order, the words the image call carries, and the at-most-one-image
    rule are all pinned."""

    def setUp(self):
        self.workspace = self.make_workspace('Rajvi', 'rajvi-order')
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Rajvi Packaging', is_default=True,
            status=Brand.Status.ACTIVE,
        )

    def generate(self):
        return generate_marketing_payload(self.workspace, {
            'campaign_name': 'Launch', 'contentType': 'poster', 'offer': '20% off',
            'creative_direction': {'mode': 'AI_ORIGINAL', 'selections': []},
        })

    @staticmethod
    def image_lines(calls):
        return [
            c['brief']['brand_context'] for c in calls
            if c['capability'] == Capability.IMAGE
        ]

    def test_the_rewritten_headline_is_what_the_image_is_asked_to_paint(self):
        calls = []
        with patch(DISPATCH, conversation_router(
            calls, [dict(JUDGE_FAIL), dict(JUDGE_PASS)],
        )):
            result = self.generate()

        # Judge, rewrite and re-judge all precede the one IMAGE dispatch.
        self.assertEqual(
            [kind_of(c) for c in calls],
            [Capability.TEXT, 'JUDGE', 'REWRITE', 'JUDGE', Capability.IMAGE],
        )
        (lines,) = self.image_lines(calls)
        self.assertTrue(any('"Precision packaging"' in line for line in lines), lines)
        self.assertFalse(any('Delivered by Friday' in line for line in lines), lines)
        self.assertEqual(result['payload']['postTitle'], 'Precision packaging')
        self.assertEqual(result['payload']['posterImageUrl'], FAKE_IMAGE['image_url'])
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'regenerated')
        self.assertTrue(critique['retried'])
        self.assertNotIn('copy_brief_context', result)
        # Judged against the very lines the copy generator saw, as internal
        # spend — the ordering moved, the semantics did not.
        judge = calls[1]
        self.assertTrue(judge['internal'])
        self.assertIn('Brand: Rajvi Packaging', calls[0]['brief']['brand_context'])
        self.assertIn(
            'Brand: Rajvi Packaging', judge['brief']['structured']['brand_rules'],
        )

    def test_the_guardrail_retry_also_precedes_the_image(self):
        """Guardrail check → critique → image: the written law's own rewrite
        is settled before the poster too, and the judge grades the result."""
        self.brand.guardrails = {'forbidden_words': ['friday']}
        self.brand.save(update_fields=['guardrails'])
        calls = []
        with patch(DISPATCH, conversation_router(calls, [dict(JUDGE_PASS)])):
            result = self.generate()

        self.assertEqual(
            [kind_of(c) for c in calls],
            [Capability.TEXT, 'REWRITE', 'JUDGE', Capability.IMAGE],
        )
        # The one rewrite was the guardrail's, naming the refusal.
        feedback = calls[1]['brief']['guardrail_feedback']
        self.assertTrue(any('friday' in line.lower() for line in feedback), feedback)
        (lines,) = self.image_lines(calls)
        self.assertTrue(any('"Precision packaging"' in line for line in lines), lines)
        self.assertEqual(result['payload']['postTitle'], 'Precision packaging')
        self.assertTrue(result['trace']['guardrails']['caught'])
        self.assertEqual(result['trace']['guardrails']['unresolved'], [])
        self.assertEqual(result['trace']['critique']['verdict'], 'passed')

    def test_a_judge_failure_still_buys_exactly_one_image_with_the_first_headline(self):
        """Fail-open holds ahead of the image spend: the judge's outage costs
        nothing and changes nothing — one image, first headline."""
        calls = []
        outage = QuotaExceeded(SimpleNamespace(message='TEXT allowance exhausted'))
        with patch(DISPATCH, conversation_router(calls, [outage])):
            result = self.generate()

        self.assertEqual(
            [kind_of(c) for c in calls],
            [Capability.TEXT, 'JUDGE', Capability.IMAGE],
        )
        (lines,) = self.image_lines(calls)
        self.assertTrue(any('"Delivered by Friday"' in line for line in lines), lines)
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'skipped')
        self.assertIn('QuotaExceeded', critique['skipped_reason'])
        self.assertEqual(result['payload']['postTitle'], 'Delivered by Friday')
        self.assertEqual(result['payload']['posterImageUrl'], FAKE_IMAGE['image_url'])

    def test_a_guardrail_gate_crash_costs_neither_the_image_nor_the_judge(self):
        """The gate now runs before the image and, on a combined provider,
        inside its call — so it must never raise: a crash ships the copy
        unchecked, the judge still runs, and one image is still bought."""
        calls = []
        with patch(DISPATCH, conversation_router(calls, [dict(JUDGE_PASS)])), \
                patch(
                    'apps.brands.services.guardrails.copy_violations',
                    side_effect=RuntimeError('law unavailable'),
                ):
            result = self.generate()

        self.assertEqual(
            [kind_of(c) for c in calls],
            [Capability.TEXT, 'JUDGE', Capability.IMAGE],
        )
        self.assertEqual(result['trace']['critique']['verdict'], 'passed')
        self.assertNotIn('guardrails', result['trace'])
        self.assertEqual(result['payload']['postTitle'], 'Delivered by Friday')

    def test_a_combined_provider_runs_the_gate_inside_its_call(self):
        """One provider paints the poster inside its TEXT call, so the gate
        rides in as `pre_image_hook`: judge, rewrite and re-judge happen
        between its text and image steps, the poster is painted with the
        final headline, and no IMAGE dispatch is ever made."""
        calls = []
        with patch(DISPATCH, conversation_router(
            calls, [dict(JUDGE_FAIL), dict(JUDGE_PASS)], combined=True,
        )), patch(PRIMARY, lambda self_router, capability: CombinedAdapter()):
            result = self.generate()

        # The TEXT call is recorded on entry; everything else happens inside it.
        self.assertEqual(
            [kind_of(c) for c in calls],
            [Capability.TEXT, 'JUDGE', 'REWRITE', 'JUDGE'],
        )
        self.assertEqual(calls[0]['painted'], 'Precision packaging')
        self.assertEqual(result['payload']['postTitle'], 'Precision packaging')
        self.assertEqual(result['payload']['posterImageUrl'], ONE_CALL_POSTER)
        critique = result['trace']['critique']
        self.assertEqual(critique['verdict'], 'regenerated')
        self.assertTrue(critique['retried'])
        self.assertTrue(
            result['trace']['capabilities'][Capability.IMAGE]['combined_with_text']
        )

    def test_a_combined_provider_that_ignores_the_hook_is_still_judged_once(self):
        """A provider pipeline that never invokes the hook leaves the copy
        unsettled; the gate then runs after the fact — as it always did —
        exactly once, never twice."""
        calls = []
        with patch(DISPATCH, conversation_router(calls, [dict(JUDGE_PASS)])), \
                patch(PRIMARY, lambda self_router, capability: CombinedAdapter()):
            result = self.generate()

        self.assertEqual([kind_of(c) for c in calls], [Capability.TEXT, 'JUDGE'])
        self.assertTrue(callable(calls[0]['brief'].get('pre_image_hook')))
        self.assertEqual(result['trace']['critique']['verdict'], 'passed')
        self.assertEqual(result['payload']['postTitle'], 'Delivered by Friday')


class StandingComplaintsTests(TenantFixtureMixin, TestCase):
    """The judge's reviewer-complaint feed is brand-scoped, sorted, capped."""

    def setUp(self):
        self.workspace = self.make_workspace('Rajvi', 'rajvi-complaints')
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Rajvi Packaging', is_default=True,
        )
        self.other = Brand.objects.create(
            workspace=self.workspace, name='Rajvi Retail',
        )

    def rule(self, brand, text, occurrences, **overrides):
        row = {
            'workspace': self.workspace, 'brand': brand, 'text': text,
            'origin': BrandRule.Origin.LEARNED, 'is_active': True,
            'structured': {'source': 'review_feedback', 'occurrences': occurrences},
        }
        row.update(overrides)
        return BrandRule.objects.create(**row)

    def test_only_this_brands_review_rules_ride_sorted_by_occurrences(self):
        self.rule(self.brand, 'Avoid discount-first headlines', 2)
        self.rule(self.brand, 'Keep captions under three lines', 5)
        # None of these may reach the judge: wrong brand, wrong origin,
        # deactivated, or learned from something other than review feedback.
        self.rule(self.other, 'A different brand entirely', 9)
        self.rule(self.brand, 'Stated, not learned', 9,
                  origin=BrandRule.Origin.EXPLICIT)
        self.rule(self.brand, 'No longer in force', 9, is_active=False)
        self.rule(self.brand, 'Learned elsewhere', 9,
                  structured={'source': 'calibration', 'occurrences': 9})

        rows = standing_complaints(self.brand)
        self.assertEqual(
            [row['rule'] for row in rows],
            ['Keep captions under three lines', 'Avoid discount-first headlines'],
        )
        self.assertEqual([row['occurrences'] for row in rows], [5, 2])

    def test_the_cap_holds(self):
        for index in range(12):
            self.rule(self.brand, f'Complaint {index}', index + 1)
        self.assertEqual(len(standing_complaints(self.brand)), 8)
