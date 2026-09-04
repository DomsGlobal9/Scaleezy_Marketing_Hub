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
