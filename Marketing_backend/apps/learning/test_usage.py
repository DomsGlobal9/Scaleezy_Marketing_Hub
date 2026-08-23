"""
Learning visibility: is what a brand learned actually reaching its work?

What is proved here is that the report tells the truth about "in force":
it reads the compiled Brand Brain rather than the rule table, so a rule that
exists but never reached the brain is reported as not in force instead of
being quietly counted — and that usage counts say plainly how far back they
can see, so a zero is never mistaken for "never used".
"""
from django.test import TestCase
from rest_framework import status

from apps.brands.models import Brand
from apps.brands.services.brand_brain import rebuild_brand_brain
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.content.models import ContentItem
from apps.learning.models import BrandRule, LearningScope
from apps.learning.services import create_explicit_rule
from apps.learning.usage import learning_usage_report
from apps.workspaces.models import WorkspaceMember

USAGE_URL = '/api/marketing/learning/usage/'


class LearningUsageTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.user, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'owner@acme.test'
        )
        self.viewer, self.viewer_api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.VIEWER, 'viewer@acme.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', is_default=True,
            status=Brand.Status.ACTIVE,
        )
        self.headers = workspace_header(self.workspace)

        self.other_workspace = self.make_workspace('Rival', 'c2')
        _, self.other_api = self.authenticate_as(
            self.other_workspace, WorkspaceMember.Role.ADMIN, 'owner@rival.test'
        )

    def a_rule(self, text='Never call the coffee cheap.', hardness=BrandRule.Hardness.HARD):
        return create_explicit_rule(
            workspace=self.workspace, brand=self.brand, text=text,
            hardness=hardness, scope=LearningScope.BRAND, created_by=self.user,
        )

    def generated_item(self, *, rule_ids=(), trace=True):
        """A content item carrying (or deliberately lacking) a generation trace."""
        layout_config = {}
        if trace:
            layout_config = {'generation_trace': {
                'brain_version': self.brand.brain_version or 'v',
                'rule_ids': [str(r) for r in rule_ids],
                'preference_ids': [],
            }}
        return ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand, headline='A post',
            layout_config=layout_config,
        )

    # ───────────────────────────────────── in force means "in the brain"

    def test_a_rule_is_only_in_force_once_it_reaches_the_compiled_brain(self):
        rule = self.a_rule()
        # Written but never compiled: the generator has not seen it, and the
        # report must not imply otherwise just because the row is active.
        report = learning_usage_report(self.workspace, self.brand)
        row = next(r for r in report['rows'] if r['id'] == str(rule.pk))
        self.assertTrue(row['is_active'])
        self.assertFalse(row['in_force'])
        self.assertEqual(row['not_in_force_reason'], 'NOT_IN_COMPILED_BRAIN')

        rebuild_brand_brain(self.brand)
        self.brand.refresh_from_db()
        report = learning_usage_report(self.workspace, self.brand)
        row = next(r for r in report['rows'] if r['id'] == str(rule.pk))
        self.assertTrue(row['in_force'])
        self.assertEqual(row['not_in_force_reason'], '')
        self.assertEqual(report['brain_version'], self.brand.brain_version)

        # Deactivated and recompiled: out of the brain, and reported as
        # deactivated rather than as a compile gap.
        rule.is_active = False
        rule.save(update_fields=['is_active'])
        rebuild_brand_brain(self.brand)
        self.brand.refresh_from_db()
        report = learning_usage_report(self.workspace, self.brand)
        row = next(r for r in report['rows'] if r['id'] == str(rule.pk))
        self.assertFalse(row['in_force'])
        self.assertEqual(row['not_in_force_reason'], 'DEACTIVATED')

    def test_usage_is_counted_from_traces_and_says_what_it_cannot_see(self):
        rule = self.a_rule()
        other = self.a_rule(text='Prefer short headlines.', hardness=BrandRule.Hardness.SOFT)
        rebuild_brand_brain(self.brand)
        self.brand.refresh_from_db()

        self.generated_item(rule_ids=[rule.pk])
        self.generated_item(rule_ids=[rule.pk, other.pk])
        # An item from before tracing existed: it must not be attributed to
        # anything, but it must still count as scanned.
        self.generated_item(trace=False)

        report = learning_usage_report(self.workspace, self.brand)
        by_id = {r['id']: r for r in report['rows']}
        self.assertEqual(by_id[str(rule.pk)]['generations_used'], 2)
        self.assertEqual(by_id[str(other.pk)]['generations_used'], 1)
        self.assertIsNotNone(by_id[str(rule.pk)]['last_used_at'])

        self.assertEqual(report['attribution']['generations_scanned'], 3)
        self.assertIn('never "never used"', report['attribution']['note'])
        self.assertEqual(report['totals']['in_force'], 2)
        self.assertEqual(report['totals']['never_used'], 0)

        # A rule in force that nothing has used yet is called out — that is
        # the whole question the report exists to answer.
        idle = self.a_rule(text='Always mention the roast date.', hardness=BrandRule.Hardness.SOFT)
        rebuild_brand_brain(self.brand)
        self.brand.refresh_from_db()
        report = learning_usage_report(self.workspace, self.brand)
        self.assertEqual(report['totals']['never_used'], 1)
        self.assertEqual(
            next(r for r in report['rows'] if r['id'] == str(idle.pk))['generations_used'], 0
        )

    # ───────────────────────────────────────────────────── the endpoint

    def test_the_endpoint_is_readable_by_a_viewer_and_scoped_to_the_tenant(self):
        rule = self.a_rule()
        rebuild_brand_brain(self.brand)

        response = self.viewer_api.get(USAGE_URL, **self.headers)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual(data['brand_id'], str(self.brand.pk))
        self.assertIn(str(rule.pk), [r['id'] for r in data['rows']])

        # Another tenant asking for this brand gets nothing — the brand is
        # resolved inside the caller's own workspace.
        response = self.other_api.get(
            USAGE_URL, {'brand_id': str(self.brand.pk)},
            **workspace_header(self.other_workspace),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # A brand id from another workspace is not found for us either.
        stranger = Brand.objects.create(workspace=self.other_workspace, name='Rival Tea')
        response = self.api.get(
            USAGE_URL, {'brand_id': str(stranger.pk)}, **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
