"""
PR5 rework — the real generation endpoint goes through the router.

`/api/marketing/gemini/generate/` used to call GeminiGeneratorService directly,
which hard-coded one vendor into the production path: a workspace that had
routed a different provider still got Gemini, and every ContentItem claimed
Gemini produced it however it was routed. These tests pin the chain that
replaced it — gateway, then router, then whichever adapter the workspace
configured — and the response contract the frontend already speaks.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework import status

from apps.ai.models import Capability
from apps.ai.router import NoProviderAvailable
from apps.brands.models import Brand
from apps.brands.services.brand_brain import rebuild_brand_brain
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.content.models import ContentItem
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import BrandRule
from apps.learning.services import create_explicit_rule
from apps.marketing.models import MarketingAsset
from apps.workspaces.models import WorkspaceMember

GENERATE_URL = '/api/marketing/gemini/generate/'

#: What a routed TEXT adapter hands back, in the provider-neutral shape the
#: router already defines. Deliberately not Gemini's.
FAKE_TEXT_RESULT = {
    'headline': 'Roasted this week',
    'caption': 'Beans that were green on Monday.',
    'hashtags': '#coffee #freshroast',
    'raw': {},
    'provider': 'OPENAI',
    'provider_name': 'OpenAI',
    'strategy': 'FAILOVER',
    'latency_ms': 12,
}
FAKE_IMAGE_RESULT = {
    'image_url': 'https://cdn.example.com/poster.png',
    'provider': 'OPENAI',
    'provider_name': 'OpenAI',
}


class GenerationRoutingTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace1 = self.make_workspace('Workspace 1', 'c1')
        self.user1, self.client1 = self.authenticate_as(
            self.workspace1, WorkspaceMember.Role.ADMIN, 'user1'
        )
        self.brand1 = Brand.objects.create(
            workspace=self.workspace1, name='Acme Coffee', industry='Coffee',
            brand_tone='Warm, unfussy', is_default=True,
        )
        source = BrandSource.objects.create(
            workspace=self.workspace1, brand=self.brand1, title='Deck',
            status=BrandSource.SourceStatus.READY,
        )
        BrandMemory.objects.create(
            workspace=self.workspace1, brand=self.brand1, source=source,
            memory_type=BrandMemory.MemoryType.PRODUCT_TRUTH,
            content='Roasted within 48 hours',
            status=BrandMemory.MemoryStatus.CONFIRMED,
        )
        create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1,
            text='Never show a competitor logo', hardness=BrandRule.Hardness.HARD,
        )
        rebuild_brand_brain(self.brand1)

        self.workspace2 = self.make_workspace('Workspace 2', 'c2')
        self.user2, self.client2 = self.authenticate_as(
            self.workspace2, WorkspaceMember.Role.ADMIN, 'user2'
        )
        self.brand2 = Brand.objects.create(
            workspace=self.workspace2, name='Rival', is_default=True,
        )
        create_explicit_rule(
            workspace=self.workspace2, brand=self.brand2,
            text='Rival secret rule', hardness=BrandRule.Hardness.HARD,
        )
        rebuild_brand_brain(self.brand2)

    def payload(self, **overrides):
        data = {
            'campaignName': 'Spring launch',
            'product': 'Single origin',
            'audience': 'Home brewers',
            'offer': '20% off',
        }
        data.update(overrides)
        return data

    def routed(self, calls):
        """A stand-in router that records what it was asked for."""

        def dispatch(self_router, capability, brief, content_item_id=None):
            calls.append({'capability': capability, 'brief': brief})
            if capability == Capability.TEXT:
                return dict(FAKE_TEXT_RESULT)
            if capability == Capability.IMAGE:
                return dict(FAKE_IMAGE_RESULT)
            raise NoProviderAvailable(f'no {capability}')

        return dispatch

    # -- 1, 2, 3 ---------------------------------------------------------

    def test_generate_invokes_the_router(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.routed(calls)):
            response = self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(calls, "the generation never reached the router")
        # Order-independent: copy and imagery now dispatch concurrently, so
        # which lands first in the call log is a race, not a contract.
        self.assertIn(
            Capability.TEXT, {c['capability'] for c in calls}
        )

    def test_gateway_brand_intelligence_reaches_the_router(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.routed(calls)):
            self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        brief = next(
            c['brief'] for c in calls if c['capability'] == Capability.TEXT
        )
        self.assertIn('MUST: Never show a competitor logo', brief['brand_context'])
        self.assertIn('Verified: Roasted within 48 hours', brief['brand_context'])
        self.assertEqual(brief['structured']['identity']['name'], 'Acme Coffee')
        self.assertEqual(
            brief['brain_version'], self.brand1.creative_brain['brain_version']
        )
        # The campaign fields still travel with it.
        self.assertEqual(brief['campaign_name'], 'Spring launch')

    def test_the_configured_provider_decides_not_a_hard_coded_one(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.routed(calls)):
            response = self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        data = response.json()['data']
        self.assertEqual(data['metadata']['provider'], 'OPENAI')
        self.assertEqual(
            ContentItem.objects.get(id=data['contentItemId']).ai_provider, 'OPENAI'
        )

    def test_the_gemini_service_is_not_called_on_the_primary_path(self):
        calls = []
        with (
            patch('apps.ai.router.AIRouter.dispatch', self.routed(calls)),
            patch(
                'apps.gemini.services.generator.GeminiGeneratorService'
                '.generate_marketing_content'
            ) as direct,
        ):
            self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )
        direct.assert_not_called()

    # -- 4 ---------------------------------------------------------------

    def test_no_provider_is_reported_honestly(self):
        def refuse(self_router, capability, brief, content_item_id=None):
            raise NoProviderAvailable('nothing routed')

        with patch('apps.ai.router.AIRouter.dispatch', refuse):
            response = self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        body = response.json()
        self.assertFalse(body['success'])
        self.assertEqual(body['error']['code'], 'NO_PROVIDER')
        # Nothing was persisted for a generation that did not happen.
        self.assertFalse(ContentItem.objects.exists())

    def test_a_missing_image_provider_does_not_fail_the_generation(self):
        def text_only(self_router, capability, brief, content_item_id=None):
            if capability == Capability.TEXT:
                return dict(FAKE_TEXT_RESULT)
            raise NoProviderAvailable('no image route')

        with patch('apps.ai.router.AIRouter.dispatch', text_only):
            response = self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()['data']
        self.assertEqual(data['posterImageUrl'], '')
        self.assertEqual(data['postTitle'], 'Roasted this week')

    # -- 5 ---------------------------------------------------------------

    def test_generation_carries_only_the_callers_own_brand(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.routed(calls)):
            self.client2.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace2),
            )

        brief = next(
            c['brief'] for c in calls if c['capability'] == Capability.TEXT
        )
        self.assertEqual(brief['structured']['identity']['name'], 'Rival')
        self.assertNotIn(
            'MUST: Never show a competitor logo', brief['brand_context'],
            "another workspace's rule reached this generation",
        )

    def test_a_foreign_workspace_header_is_refused(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.routed(calls)):
            response = self.client2.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
        self.assertFalse(calls, "a cross-tenant request still reached the router")

    # -- 6, 7 ------------------------------------------------------------

    def test_the_frontend_response_contract_is_unchanged(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.routed(calls)):
            response = self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        data = response.json()['data']
        for key in (
            'postTitle', 'postDescription', 'postHashtags', 'posterImageUrl',
            'contentItemId', 'assetId', 'metadata',
        ):
            with self.subTest(key=key):
                self.assertIn(key, data)
        self.assertEqual(data['postTitle'], 'Roasted this week')
        self.assertEqual(data['postDescription'], 'Beans that were green on Monday.')
        self.assertEqual(data['postHashtags'], '#coffee #freshroast')
        self.assertEqual(data['posterImageUrl'], 'https://cdn.example.com/poster.png')

    def test_the_generated_content_item_is_still_persisted(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.routed(calls)):
            response = self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        item = ContentItem.objects.get(id=response.json()['data']['contentItemId'])
        self.assertEqual(item.workspace_id, self.workspace1.id)
        self.assertEqual(item.brand_id, self.brand1.id)
        self.assertEqual(item.headline, 'Roasted this week')
        self.assertEqual(item.status, ContentItem.Status.DRAFT)

    @override_settings(STORAGE_TEST_MODE=True)
    def test_inline_provider_image_is_durable_before_content_is_returned(self):
        def inline_image(self_router, capability, brief, content_item_id=None):
            if capability == Capability.TEXT:
                return dict(FAKE_TEXT_RESULT)
            return {
                'image_url': 'data:image/png;base64,aW1hZ2UtYnl0ZXM=',
                'image_base64': 'aW1hZ2UtYnl0ZXM=',
                'mime_type': 'image/png',
                'provider': 'OPENAI',
                'provider_name': 'OpenAI',
            }

        with patch('apps.ai.router.AIRouter.dispatch', inline_image):
            response = self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content[:300])
        data = response.json()['data']
        self.assertTrue(data['posterImageUrl'].startswith('https://storage.test/generated/'))
        self.assertNotIn('base64', data['posterImageUrl'])
        self.assertTrue(data['assetId'])

        item = ContentItem.objects.select_related('asset').get(pk=data['contentItemId'])
        self.assertEqual(str(item.asset_id), data['assetId'])
        self.assertEqual(item.preview_url, data['posterImageUrl'])
        self.assertEqual(item.asset.source, MarketingAsset.Source.AI_GENERATED)
        self.assertEqual(item.asset.file_url, data['posterImageUrl'])


class ConcurrentGenerationTests(GenerationRoutingTests):
    """PR6 blocker: the accelerator must be genuinely user-visible on the
    primary /generate/ path — both capabilities dispatched together, partial
    success kept, and no duplicate call when one provider answers both."""

    def test_generate_dispatches_text_and_image_concurrently(self):
        import threading

        seen_threads = {}
        barrier = threading.Barrier(2, timeout=10)

        def concurrent_probe(self_router, capability, brief, content_item_id=None):
            seen_threads[capability] = threading.current_thread().name
            # Both dispatches must be in flight at once to pass the barrier;
            # a sequential implementation deadlocks here and times out.
            barrier.wait()
            if capability == Capability.TEXT:
                return dict(FAKE_TEXT_RESULT)
            return dict(FAKE_IMAGE_RESULT)

        with patch('apps.ai.router.AIRouter.dispatch', concurrent_probe):
            response = self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            set(seen_threads), {Capability.TEXT, Capability.IMAGE},
            "both capabilities must be dispatched",
        )
        data = response.json()['data']
        self.assertEqual(data['postTitle'], 'Roasted this week')
        self.assertEqual(data['posterImageUrl'], 'https://cdn.example.com/poster.png')

    def test_partial_image_failure_keeps_the_copy(self):
        def image_fails(self_router, capability, brief, content_item_id=None):
            if capability == Capability.TEXT:
                return dict(FAKE_TEXT_RESULT)
            raise RuntimeError('image provider exploded')

        with patch('apps.ai.router.AIRouter.dispatch', image_fails):
            response = self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()['data']
        self.assertEqual(data['postTitle'], 'Roasted this week')
        self.assertEqual(data['posterImageUrl'], '')
        # The copy that succeeded was persisted; the trace records the failure.
        item = ContentItem.objects.get(id=data['contentItemId'])
        trace = item.layout_config['generation_trace']['capabilities']
        self.assertEqual(trace[Capability.IMAGE]['status'], 'FAILED')
        self.assertEqual(trace[Capability.TEXT]['status'], 'OK')

    def test_a_poster_in_the_text_result_survives_an_image_failure(self):
        def image_fails_text_has_poster(self_router, capability, brief,
                                        content_item_id=None):
            if capability == Capability.TEXT:
                return {
                    **FAKE_TEXT_RESULT,
                    'raw': {'posterImageUrl': 'https://cdn.example.com/from-text.png'},
                }
            raise RuntimeError('image provider exploded')

        with patch('apps.ai.router.AIRouter.dispatch', image_fails_text_has_poster):
            response = self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        data = response.json()['data']
        self.assertEqual(
            data['posterImageUrl'], 'https://cdn.example.com/from-text.png'
        )

    def test_a_combined_provider_is_not_asked_twice(self):
        """When one provider serves both capabilities and its text result
        carries the poster, the second dispatch is pure duplicate spend."""

        class CombinedAdapter:
            key = 'combined'
            yields_poster_with_text = True

        calls = []

        def counting(self_router, capability, brief, content_item_id=None):
            calls.append(capability)
            return {
                **FAKE_TEXT_RESULT,
                'raw': {'posterImageUrl': 'https://cdn.example.com/one-call.png'},
            }

        with (
            patch('apps.ai.router.AIRouter.dispatch', counting),
            patch(
                'apps.ai.router.AIRouter.primary_adapter',
                lambda self_router, capability: CombinedAdapter(),
            ),
        ):
            response = self.client1.post(
                GENERATE_URL, self.payload(), format='json',
                **workspace_header(self.workspace1),
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(calls, [Capability.TEXT], "expected exactly one dispatch")
        data = response.json()['data']
        self.assertEqual(data['posterImageUrl'], 'https://cdn.example.com/one-call.png')
