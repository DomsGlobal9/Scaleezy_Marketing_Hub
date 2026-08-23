from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.models import PlatformAuditLog
from apps.audit.services import grant_platform_admin
from apps.brands.models import Brand
from apps.brands.services.brand_brain import (
    RANK_HARD_EXPLICIT_RULE,
    RANK_INSPIRATION_SIGNAL,
    rebuild_brand_brain,
)
from apps.common.testing import TenantFixtureMixin
from apps.context.services.context_gateway import TaskType, build_generation_context, context_as_brief
from apps.learning.models import BrandPreference, LearningEvent, LearningScope
from apps.universal.aggregation import compile_learned_patterns
from apps.universal.models import (
    RANK_LEARNED_PATTERN,
    RANK_UNIVERSAL_STANDARD,
    LearnedPattern,
    LifecycleStatus,
)
from apps.universal.services import publish_pattern, retire_pattern
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember


class PR7Base(TenantFixtureMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.workspace = self.make_workspace('Acme', 'acme')
        self.user, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner@acme.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace,
            name='Acme Coffee',
            industry='Coffee',
            tagline='ACME PRIVATE SIGNATURE',
            status=Brand.Status.ACTIVE,
            is_default=True,
        )
        rebuild_brand_brain(self.brand)

    def preference(self, workspace, brand, *, attribute='length', value='short', confidence=.8):
        return BrandPreference.objects.create(
            workspace=workspace,
            brand=brand,
            category='COPY_STYLE',
            attribute=attribute,
            value=value,
            confidence=confidence,
            weight=.7,
            evidence_count=1,
            state=BrandPreference.State.EMERGING,
            scope=LearningScope.BRAND,
        )


class AggregationTests(PR7Base):
    def test_single_client_is_emitted_and_legacy_consent_flag_is_ignored(self):
        self.preference(self.workspace, self.brand)
        LearningEvent.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            event_type=LearningEvent.EventType.APPROVED,
            outcome=LearningEvent.Outcome.POSITIVE,
            eligibility_for_aggregate_learning=False,
        )
        result = compile_learned_patterns()
        pattern = LearnedPattern.objects.get(attribute='length')
        self.assertEqual(result['pattern_count'], 1)
        self.assertEqual(pattern.contributor_count, 1)
        self.assertEqual(pattern.supporting_brand_count, 1)
        self.assertEqual(pattern.contributing_workspace_ids, [str(self.workspace.pk)])

    def test_internal_workspaces_are_excluded_and_counts_are_real(self):
        second = self.make_workspace('Beta', 'beta')
        second_brand = Brand.objects.create(
            workspace=second, name='Beta Coffee', industry='Coffee', status=Brand.Status.ACTIVE
        )
        internal = self.make_workspace('Demo', 'demo')
        internal.kind = MarketingWorkspace.Kind.INTERNAL
        internal.save(update_fields=['kind'])
        internal_brand = Brand.objects.create(
            workspace=internal, name='Demo Coffee', industry='Coffee', status=Brand.Status.ACTIVE
        )
        for workspace, brand in (
            (self.workspace, self.brand), (second, second_brand), (internal, internal_brand)
        ):
            self.preference(workspace, brand)

        compile_learned_patterns()
        pattern = LearnedPattern.objects.get(attribute='length')
        self.assertEqual(pattern.contributor_count, 2)
        self.assertEqual(pattern.supporting_brand_count, 2)
        self.assertNotIn(str(internal.pk), pattern.contributing_workspace_ids)

    def test_compile_and_delete_recompile_are_deterministic(self):
        self.preference(self.workspace, self.brand)
        first = compile_learned_patterns()
        first_row = LearnedPattern.objects.values(
            'category', 'attribute', 'value', 'contributor_count',
            'supporting_brand_count', 'confidence', 'pattern_version',
            'contributing_workspace_ids',
        ).get()
        second = compile_learned_patterns()
        self.assertEqual(first['pattern_version'], second['pattern_version'])
        self.assertEqual(first_row['pattern_version'], LearnedPattern.objects.get().pattern_version)

        LearnedPattern.objects.all().delete()
        rebuilt = compile_learned_patterns()
        rebuilt_row = LearnedPattern.objects.values(*first_row.keys()).get()
        self.assertEqual(first['pattern_version'], rebuilt['pattern_version'])
        self.assertEqual(first_row, rebuilt_row)

    def test_brand_specific_literal_is_not_compiled(self):
        self.preference(
            self.workspace,
            self.brand,
            attribute='tagline_style',
            value='Repeat ACME PRIVATE SIGNATURE verbatim',
        )
        compile_learned_patterns()
        self.assertFalse(LearnedPattern.objects.exists())


class GatewayPatternTests(PR7Base):
    def setUp(self):
        super().setUp()
        source = self.make_workspace('Beta', 'beta')
        source_brand = Brand.objects.create(
            workspace=source, name='Beta Coffee', industry='Coffee', status=Brand.Status.ACTIVE
        )
        self.preference(source, source_brand, value='short')
        compile_learned_patterns()
        self.pattern = publish_pattern(LearnedPattern.objects.get())

    def test_rank_is_weaker_than_standard_and_every_brand_rank(self):
        self.assertGreater(RANK_LEARNED_PATTERN, RANK_UNIVERSAL_STANDARD)
        self.assertGreater(RANK_LEARNED_PATTERN, RANK_INSPIRATION_SIGNAL)
        self.assertGreater(RANK_LEARNED_PATTERN, RANK_HARD_EXPLICIT_RULE)

    def test_published_pattern_reaches_brief_attributed_without_contributor_ids(self):
        context = build_generation_context(self.workspace, self.brand, TaskType.COPY)
        entry = context['learned_patterns'][0]
        self.assertEqual(entry['rank'], RANK_LEARNED_PATTERN)
        self.assertEqual(entry['source'], 'Learned across Scaleezy clients')
        self.assertNotIn('contributing_workspace_ids', entry)
        brief = context_as_brief(context)
        self.assertTrue(any(line.startswith('Scaleezy learned pattern:') for line in brief['brand_context']))

    def test_brand_position_structurally_drops_pattern(self):
        self.brand.creative_brain = {
            **self.brand.creative_brain,
            'preferences': [
                {'category': 'COPY_STYLE', 'attribute': 'length', 'value': 'long'}
            ],
        }
        self.brand.save(update_fields=['creative_brain'])
        context = build_generation_context(self.workspace, self.brand, TaskType.COPY)
        self.assertEqual(context['learned_patterns'], [])

    def test_retiring_pattern_invalidates_cached_context_immediately(self):
        first = build_generation_context(self.workspace, self.brand, TaskType.COPY)
        self.assertEqual(len(first['learned_patterns']), 1)
        retire_pattern(self.pattern)
        second = build_generation_context(self.workspace, self.brand, TaskType.COPY)
        self.assertEqual(second['learned_patterns'], [])
        self.assertNotEqual(
            first['learned_pattern_version'], second['learned_pattern_version']
        )


class PatternConsoleTests(PR7Base):
    def setUp(self):
        super().setUp()
        self.preference(self.workspace, self.brand)
        compile_learned_patterns()
        self.pattern = LearnedPattern.objects.get()
        self.admin = self.user.__class__.objects.create_user(
            username='platform@scaleezy.test', password='pw'
        )
        grant_platform_admin(self.admin, note='PR7 test')
        self.admin_api = APIClient()
        self.admin_api.force_authenticate(user=self.admin)

    def test_only_platform_admin_can_list_publish_and_read_contributors(self):
        base = '/api/platform/patterns/'
        self.assertEqual(self.api.get(base).status_code, 403)
        listing = self.admin_api.get(base)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()['data']['patterns'][0]['contributor_count'], 1)

        published = self.admin_api.post(f'{base}{self.pattern.pk}/publish/', {}, format='json')
        self.assertEqual(published.status_code, 200)
        contributors = self.admin_api.get(f'{base}{self.pattern.pk}/contributors/')
        self.assertEqual(contributors.status_code, 200)
        self.assertEqual(
            contributors.json()['data']['contributors'][0]['client_code'],
            self.workspace.client_code,
        )
        actions = set(PlatformAuditLog.objects.values_list('action', flat=True))
        self.assertIn('LEARNED_PATTERNS_VIEWED', actions)
        self.assertIn('LEARNED_PATTERN_PUBLISHED', actions)
        self.assertIn('LEARNED_PATTERN_CONTRIBUTORS_VIEWED', actions)

    def test_retire_is_audited(self):
        publish_pattern(self.pattern, by=self.admin)
        response = self.admin_api.post(
            f'/api/platform/patterns/{self.pattern.pk}/retire/',
            {'reason': 'thin evidence'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.pattern.refresh_from_db()
        self.assertEqual(self.pattern.status, LifecycleStatus.RETIRED)
        self.assertTrue(
            PlatformAuditLog.objects.filter(action='LEARNED_PATTERN_RETIRED').exists()
        )
