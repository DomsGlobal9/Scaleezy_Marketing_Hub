"""Ultra costs 2 units — the founder's pricing (2026-09-05).

The weight lands exactly once per poster: on the IMAGE dispatch, or on the
TEXT dispatch of a provider whose one call paints the poster too. Copy-only
retries, internal QA and non-4K quality stay at 1, and the quota counter
sums units instead of counting rows so the weight actually bills.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from apps.ai.models import AIProvider, AIUsageLog
from apps.ai.router import billable_units
from apps.billing.models import Plan, Subscription
from apps.billing.quota import capability_usage
from apps.workspaces.models import MarketingWorkspace

PAINTS = SimpleNamespace(yields_poster_with_text=True)
PLAIN = SimpleNamespace(yields_poster_with_text=False)


class BillableUnitsTests(SimpleTestCase):
    def test_a_4k_poster_image_call_is_two_units(self):
        brief = {'image_quality': '4K'}
        self.assertEqual(billable_units('IMAGE', PLAIN, brief), 2)

    def test_the_combined_text_call_that_paints_the_poster_is_two_units(self):
        brief = {'image_quality': '4K'}
        self.assertEqual(billable_units('TEXT', PAINTS, brief), 2)

    def test_everything_else_stays_one_unit(self):
        four_k = {'image_quality': '4K'}
        # Copy that does not buy the image, copy-only retries, internal QA,
        # lower tiers, video, and briefs with no quality at all.
        self.assertEqual(billable_units('TEXT', PLAIN, four_k), 1)
        self.assertEqual(billable_units('TEXT', PAINTS, {**four_k, 'copy_only': True}), 1)
        self.assertEqual(billable_units('IMAGE', PLAIN, four_k, internal=True), 1)
        self.assertEqual(billable_units('IMAGE', PLAIN, {'image_quality': '2K'}), 1)
        self.assertEqual(billable_units('IMAGE', PLAIN, {'image_quality': '1K'}), 1)
        self.assertEqual(billable_units('VIDEO', PLAIN, four_k), 1)
        self.assertEqual(billable_units('IMAGE', PLAIN, {}), 1)
        self.assertEqual(billable_units('IMAGE', PLAIN, None), 1)


class CapabilityUsageSumsUnitsTests(TestCase):
    def test_units_are_summed_not_counted(self):
        workspace = MarketingWorkspace.objects.create(
            customer_id='u1', workspace_name='Units'
        )
        Subscription.objects.create(workspace=workspace, plan=Plan.objects.get(key='free'))
        provider, _ = AIProvider.objects.get_or_create(
            key='gemini', defaults={'display_name': 'Gemini', 'capabilities': ['TEXT']}
        )
        for units in (2, 1):
            AIUsageLog.objects.create(
                workspace=workspace, provider=provider, capability='IMAGE',
                units=units, success=True, selected=True,
            )
        # A failed row and a BEST_OF loser stay out, whatever their weight.
        AIUsageLog.objects.create(
            workspace=workspace, provider=provider, capability='IMAGE',
            units=2, success=False, selected=False,
        )
        self.assertEqual(capability_usage(workspace).get('IMAGE'), 3)
