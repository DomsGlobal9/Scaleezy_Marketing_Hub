"""
PR5 — Context Gateway, readiness, and Brand Master.

The gateway is the only door to brand intelligence, so most of what matters
here is what it refuses: another tenant's brand, a sibling brand's records, a
raw inference dressed up as resolved truth, and a hard rule quietly dropped
because the task did not seem to need it.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status

from apps.brands.models import Brand
from apps.brands.services.brand_brain import rebuild_brand_brain
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.inspirations.models import BrandInspiration, InspirationSignal
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import BrandRule
from apps.learning.services import create_explicit_rule, record_event, reinforce_preference
from apps.workspaces.models import WorkspaceMember

from .services.context_gateway import (
    ContextError,
    TaskType,
    build_generation_context,
    context_as_brief,
)
from .services.generation import NoProviderConfigured, generate_with_context
from .services.readiness import brand_readiness

User = get_user_model()
MASTER_URL = '/api/marketing/brand-master/'


class ContextTestBase(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace1 = self.make_workspace('Workspace 1', 'c1')
        self.user1, self.client1 = self.authenticate_as(
            self.workspace1, WorkspaceMember.Role.ADMIN, 'user1'
        )
        self.viewer, self.viewer_client = self.authenticate_as(
            self.workspace1, WorkspaceMember.Role.VIEWER, 'viewer'
        )
        self.brand1 = Brand.objects.create(
            workspace=self.workspace1, name='Acme Coffee', industry='Coffee',
            tagline='Roasted this week', brand_tone='Warm, unfussy',
            logo_url='https://example.com/logo.png',
        )
        self.sibling = Brand.objects.create(workspace=self.workspace1, name='Acme Tea')

        self.workspace2 = self.make_workspace('Workspace 2', 'c2')
        self.user2, self.client2 = self.authenticate_as(
            self.workspace2, WorkspaceMember.Role.ADMIN, 'user2'
        )
        self.brand2 = Brand.objects.create(workspace=self.workspace2, name='Rival')

    def ws1(self):
        return workspace_header(self.workspace1)

    def furnish(self, brand=None):
        """A brand with something in every layer."""
        brand = brand or self.brand1
        source = BrandSource.objects.create(
            workspace=brand.workspace, brand=brand, title='Deck',
            status=BrandSource.SourceStatus.READY,
        )
        BrandMemory.objects.create(
            workspace=brand.workspace, brand=brand, source=source,
            memory_type=BrandMemory.MemoryType.PRODUCT_TRUTH,
            content='Roasted within 48 hours', normalized_key='FACT/roast_freshness',
            status=BrandMemory.MemoryStatus.CONFIRMED,
        )
        BrandMemory.objects.create(
            workspace=brand.workspace, brand=brand, source=source,
            memory_type=BrandMemory.MemoryType.BUYER_PAIN,
            content='Beginners find grinding intimidating',
            status=BrandMemory.MemoryStatus.CONFIRMED,
        )
        create_explicit_rule(
            workspace=brand.workspace, brand=brand,
            text='Never show a competitor logo', hardness=BrandRule.Hardness.HARD,
        )
        inspiration = BrandInspiration.objects.create(
            workspace=brand.workspace, brand=brand, title='Reference',
            reference_url='https://example.com/x',
        )
        InspirationSignal.objects.create(
            inspiration=inspiration, category='TYPOGRAPHY', attribute='headline_face',
            value='Condensed grotesque', sentiment=InspirationSignal.Sentiment.LIKED,
            origin=InspirationSignal.Origin.USER,
            user_confirmation=InspirationSignal.UserConfirmation.CONFIRMED,
        )
        for index in range(2):
            event = record_event(
                workspace=brand.workspace, brand=brand, event_type='REJECTED',
                dedupe_key=f'ev{index}-{brand.pk}',
            )
            reinforce_preference(
                workspace=brand.workspace, brand=brand, event=event,
                category='TONE', attribute='register', value='plain',
            )
        rebuild_brand_brain(brand)
        return brand


class GatewayTests(ContextTestBase):
    def test_context_is_built_from_the_compiled_brain(self):
        self.furnish()
        context = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
        self.assertEqual(context['brand_id'], str(self.brand1.pk))
        self.assertEqual(
            context['brain_version'], self.brand1.creative_brain['brain_version']
        )
        self.assertIn('Roasted within 48 hours', context['verified_truth'])

    def test_hard_rules_survive_every_task(self):
        """A constraint that only applies to some jobs is not a constraint."""
        self.furnish()
        for task in TaskType.ALL:
            with self.subTest(task=task):
                context = build_generation_context(self.workspace1, self.brand1, task)
                self.assertEqual(
                    [r['text'] for r in context['hard_rules']],
                    ['Never show a competitor logo'],
                )

    def test_copy_and_image_context_differ_appropriately(self):
        self.furnish()
        copy = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
        image = build_generation_context(self.workspace1, self.brand1, TaskType.IMAGE)

        self.assertTrue(copy['audience']['pains'])
        self.assertEqual(image['audience']['pains'], [])
        self.assertTrue(image['visual_language']['palette'])
        self.assertEqual(copy['visual_language']['palette'], {})
        self.assertEqual(copy['inspiration_signals'], [])
        self.assertTrue(image['inspiration_signals'])

    def test_the_brands_own_description_and_audience_reach_the_context(self):
        """Fields collected in the settings form are orphan UI until they are
        in the payload a provider actually receives."""
        self.brand1.description = 'A single-origin roastery on the Malabar coast.'
        self.brand1.audience = 'Office managers buying coffee for a team of twenty.'
        self.brand1.save(update_fields=['description', 'audience'])
        rebuild_brand_brain(self.brand1)

        copy = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
        self.assertEqual(copy['brand_identity']['description'], self.brand1.description)
        self.assertEqual(copy['audience']['stated'], self.brand1.audience)

        # And in the prose brief, not only the structured block - an adapter
        # that reads the paragraph would otherwise never see them.
        brief = context_as_brief(copy)
        self.assertIn(f'About: {self.brand1.description}', brief['brand_context'])
        self.assertIn(f'Audience: {self.brand1.audience}', brief['brand_context'])

    def test_the_description_travels_with_every_task_but_the_audience_does_not(self):
        self.brand1.description = 'A single-origin roastery on the Malabar coast.'
        self.brand1.audience = 'Office managers buying coffee for a team of twenty.'
        self.brand1.save(update_fields=['description', 'audience'])
        rebuild_brand_brain(self.brand1)

        for task in TaskType.ALL:
            with self.subTest(task=task):
                context = build_generation_context(self.workspace1, self.brand1, task)
                self.assertEqual(
                    context['brand_identity']['description'], self.brand1.description
                )
        image = build_generation_context(self.workspace1, self.brand1, TaskType.IMAGE)
        self.assertEqual(image['audience']['stated'], '')

    def test_context_is_deterministic_for_a_brain_and_task(self):
        self.furnish()
        first = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
        second = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
        self.assertEqual(first, second)

    def test_a_verified_fact_outranks_a_lower_contradiction_in_context(self):
        self.furnish()
        BrandRule.objects.create(
            workspace=self.workspace1, brand=self.brand1,
            text='Roasted within 7 days', hardness=BrandRule.Hardness.SOFT,
            origin=BrandRule.Origin.LEARNED,
            structured={'category': 'FACT', 'attribute': 'roast_freshness',
                        'value': 'Roasted within 7 days'},
        )
        rebuild_brand_brain(self.brand1)

        context = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
        roast = [c for c in context['preferences'] if c['attribute'] == 'roast_freshness']
        self.assertEqual(roast[0]['authority'], 'verified_fact')
        self.assertEqual(roast[0]['value'], 'Roasted within 48 hours')

    def test_a_raw_inference_cannot_override_the_resolved_brain(self):
        """Inference is carried for reference, never as the answer."""
        self.furnish()
        other = BrandInspiration.objects.create(
            workspace=self.workspace1, brand=self.brand1, title='Other',
            reference_url='https://example.com/other',
        )
        InspirationSignal.objects.create(
            inspiration=other, category='TYPOGRAPHY', attribute='headline_face',
            value='Serif display', sentiment=InspirationSignal.Sentiment.LIKED,
            origin=InspirationSignal.Origin.AI,
        )
        rebuild_brand_brain(self.brand1)

        context = build_generation_context(self.workspace1, self.brand1, TaskType.IMAGE)
        face = [c for c in context['preferences'] if c['attribute'] == 'headline_face']
        self.assertEqual(face[0]['value'], 'Condensed grotesque')
        self.assertEqual(face[0]['authority'], 'explicit_preference')

    def test_context_never_crosses_a_tenant(self):
        self.furnish(self.brand2)
        with self.assertRaises(ContextError):
            build_generation_context(self.workspace1, self.brand2, TaskType.COPY)

    def test_context_never_carries_a_sibling_brands_records(self):
        self.furnish(self.sibling)
        rebuild_brand_brain(self.brand1)
        context = build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
        self.assertEqual(context['verified_truth'], [])
        self.assertEqual(context['hard_rules'], [])

    def test_unresolved_conflicts_are_surfaced_not_resolved(self):
        self.furnish()
        for value in ('wordmark', 'icon'):
            create_explicit_rule(
                workspace=self.workspace1, brand=self.brand1,
                text=f'Use the {value}', hardness=BrandRule.Hardness.HARD,
                structured={'category': 'BRANDING', 'attribute': 'logo', 'value': value},
            )
        rebuild_brand_brain(self.brand1)

        context = build_generation_context(self.workspace1, self.brand1, TaskType.IMAGE)
        self.assertEqual(context['unresolved_conflict_count'], 1)
        self.assertEqual(
            [c for c in context['preferences'] if c['attribute'] == 'logo'], []
        )

    def test_the_brief_is_provider_neutral(self):
        import json

        self.furnish()
        brief = context_as_brief(
            build_generation_context(self.workspace1, self.brand1, TaskType.COPY)
        )
        blob = json.dumps(brief).lower()
        for token in ('gemini', 'openai', 'gpt', 'anthropic', 'api_key', 'temperature'):
            with self.subTest(token=token):
                self.assertNotIn(token, blob)
        self.assertIn('MUST: Never show a competitor logo', brief['brand_context'])

    def test_a_never_compiled_brand_gets_a_real_but_empty_context(self):
        """The column is a cache, so compiling on demand is not faking - the
        records are the truth and a brand with none has an honestly empty
        context rather than an error or an invented one."""
        empty = Brand.objects.create(workspace=self.workspace1, name='Empty')
        context = build_generation_context(self.workspace1, empty, TaskType.COPY)
        self.assertEqual(context['brand_identity']['name'], 'Empty')
        self.assertEqual(context['hard_rules'], [])
        self.assertEqual(context['verified_truth'], [])
        self.assertEqual(context['preferences'], [])
        self.assertTrue(context['brain_version'])

    def test_an_unknown_task_is_refused(self):
        self.furnish()
        with self.assertRaises(ContextError):
            build_generation_context(self.workspace1, self.brand1, 'TELEPATHY')


class GenerationChainTests(ContextTestBase):
    def test_generation_runs_gateway_then_router_then_provider(self):
        """The whole chain, with a fake provider standing in for the API."""
        self.furnish()
        seen = {}

        def fake_dispatch(self_router, capability, brief, content_item_id=None):
            seen['capability'] = capability
            seen['brief'] = brief
            # The adapter contract for TEXT: a headline at minimum. The
            # validator rejects anything less, deliberately.
            return {'headline': 'generated', 'caption': '', 'provider': 'fake'}

        with patch('apps.ai.router.AIRouter.dispatch', fake_dispatch):
            outcome = generate_with_context(
                self.workspace1, self.brand1, TaskType.COPY, instruction='Launch post',
            )

        self.assertEqual(outcome['result']['headline'], 'generated')
        self.assertEqual(
            outcome['brain_version'], self.brand1.creative_brain['brain_version']
        )
        # The provider was handed real brand intelligence, not an empty brief.
        self.assertIn('MUST: Never show a competitor logo', seen['brief']['brand_context'])
        self.assertEqual(seen['brief']['instruction'], 'Launch post')
        self.assertEqual(outcome['context_summary']['hard_rules'], 1)

    def test_no_routed_provider_is_reported_as_unavailable(self):
        self.furnish()
        with self.assertRaises(NoProviderConfigured):
            generate_with_context(self.workspace1, self.brand1, TaskType.COPY)

    def test_the_existing_generation_path_now_uses_the_gateway(self):
        """apps.gemini used to read learned rules straight from the training
        engine; it goes through the gateway now."""
        from apps.gemini.views import GeminiGenerationViewSet

        self.furnish()
        request = type('R', (), {
            'data': {'campaignName': 'Spring'},
            'headers': {'X-Workspace-Id': str(self.workspace1.id)},
            'user': self.user1,
            'query_params': {},
        })()
        rules = GeminiGenerationViewSet()._brand_rules(request)
        self.assertIn('MUST: Never show a competitor logo', rules)


class ReadinessTests(ContextTestBase):
    def test_a_bare_brand_is_not_ready(self):
        bare = Brand.objects.create(workspace=self.workspace1, name='Bare')
        readiness = brand_readiness(bare)
        self.assertLess(readiness['readiness_score'], 30)
        self.assertEqual(readiness['readiness_level'], 'STARTING')
        self.assertIn('knowledge', readiness['missing_dimensions'])

    def test_readiness_is_deterministic(self):
        self.furnish()
        self.assertEqual(
            brand_readiness(self.brand1), brand_readiness(self.brand1)
        )

    def test_readiness_falls_when_knowledge_is_revoked(self):
        self.furnish()
        before = brand_readiness(self.brand1)['readiness_score']

        BrandSource.objects.filter(brand=self.brand1).update(
            status=BrandSource.SourceStatus.ARCHIVED
        )
        rebuild_brand_brain(self.brand1)
        after = brand_readiness(self.brand1)['readiness_score']

        self.assertLess(after, before)

    def test_a_conflict_becomes_the_recommended_next_action(self):
        self.furnish()
        for value in ('wordmark', 'icon'):
            create_explicit_rule(
                workspace=self.workspace1, brand=self.brand1,
                text=f'Use the {value}', hardness=BrandRule.Hardness.HARD,
                structured={'category': 'BRANDING', 'attribute': 'logo', 'value': value},
            )
        rebuild_brand_brain(self.brand1)
        readiness = brand_readiness(self.brand1)
        self.assertEqual(readiness['recommended_next_action']['key'], 'resolve_conflicts')


class BrandMasterApiTests(ContextTestBase):
    def test_overview_returns_real_backend_data(self):
        self.furnish()
        body = self.client1.get(f'{MASTER_URL}{self.brand1.id}/', **self.ws1()).json()['data']
        self.assertEqual(body['brand']['name'], 'Acme Coffee')
        self.assertEqual(
            body['brain']['brain_version'], self.brand1.creative_brain['brain_version']
        )
        self.assertEqual(body['readiness']['counts']['memories'], 2)
        self.assertEqual(body['readiness']['counts']['rules'], 1)
        self.assertIn(body['readiness']['readiness_level'],
                      ('STARTING', 'LEARNING', 'STRONG', 'READY'))

    def test_a_new_brand_gets_honest_empty_state(self):
        bare = Brand.objects.create(workspace=self.workspace1, name='Bare')
        body = self.client1.get(f'{MASTER_URL}{bare.id}/', **self.ws1()).json()['data']
        self.assertFalse(body['brain']['compiled'])
        self.assertEqual(body['conflicts'], [])
        self.assertEqual(body['readiness']['counts']['memories'], 0)
        self.assertTrue(body['readiness']['recommended_next_action']['label'])

    def test_conflict_count_matches_the_compiled_brain(self):
        self.furnish()
        for value in ('wordmark', 'icon'):
            create_explicit_rule(
                workspace=self.workspace1, brand=self.brand1,
                text=f'Use the {value}', hardness=BrandRule.Hardness.HARD,
                structured={'category': 'BRANDING', 'attribute': 'logo', 'value': value},
            )
        rebuild_brand_brain(self.brand1)
        body = self.client1.get(f'{MASTER_URL}{self.brand1.id}/', **self.ws1()).json()['data']
        self.assertEqual(body['brain']['unresolved_conflict_count'], 1)
        self.assertEqual(len(body['conflicts']), 1)

    def test_context_preview_is_workspace_scoped(self):
        self.furnish()
        ok = self.client1.get(
            f'{MASTER_URL}{self.brand1.id}/context/?task=COPY', **self.ws1()
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK)

        leak = self.client2.get(
            f'{MASTER_URL}{self.brand1.id}/context/?task=COPY',
            **workspace_header(self.workspace2),
        )
        self.assertEqual(leak.status_code, status.HTTP_404_NOT_FOUND)

    def test_another_tenant_cannot_read_readiness(self):
        self.furnish()
        response = self.client2.get(
            f'{MASTER_URL}{self.brand1.id}/readiness/',
            **workspace_header(self.workspace2),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_viewer_cannot_rebuild_the_brain(self):
        self.furnish()
        before = self.brand1.creative_brain['brain_version']
        response = self.viewer_client.post(
            f'{MASTER_URL}{self.brand1.id}/rebuild-brain/', format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.brand1.refresh_from_db()
        self.assertEqual(self.brand1.creative_brain['brain_version'], before)

    def test_another_tenant_cannot_rebuild(self):
        self.furnish()
        response = self.client2.post(
            f'{MASTER_URL}{self.brand1.id}/rebuild-brain/', format='json',
            **workspace_header(self.workspace2),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_rebuild_uses_the_pr4_compiler(self):
        self.furnish()
        self.brand1.creative_brain = {}
        self.brand1.save(update_fields=['creative_brain'])

        response = self.client1.post(
            f'{MASTER_URL}{self.brand1.id}/rebuild-brain/', format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.brand1.refresh_from_db()
        self.assertEqual(
            self.brand1.creative_brain['brain_version'],
            response.json()['data']['brain_version'],
        )

    def test_preview_generation_reports_a_missing_provider_honestly(self):
        self.furnish()
        response = self.client1.post(
            f'{MASTER_URL}{self.brand1.id}/preview-generation/',
            {'task': 'COPY'}, format='json', **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()['error']['code'], 'NO_PROVIDER')
