"""
The whole product, once, through the API a customer actually calls.

Every layer of this already has its own unit tests, and all of them passed
while the product was unusable: a workspace created through the API had no AI
route, so the first generation 503'd. A defect that only appears where two
green suites meet is invisible to both of them.

So this walks one tenant from signup to a generated result without an operator
anywhere in it — sign up, create the workspace, create the brand, describe the
business, teach it, correct it, compile, generate — and then proves a member of
a second workspace cannot see a single record it produced.

Deliberately ONE test. Split into eight it would still pass with the chain
broken between any two of them, which is the exact failure it exists to catch.
No provider is ever called: `AIRouter.dispatch` is patched, so what is proved
is that routing resolves and the brief is well formed, not that Gemini replies.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.ai.models import Capability, WorkspaceAIProvider, WorkspaceAIRoute
from apps.ai.router import AIRouter
from apps.brands.models import Brand
from apps.common.testing import workspace_header
from apps.inspirations.models import BrandInspiration
from apps.knowledge.models import BrandSource
from apps.learning.models import BrandRule
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

from .services.context_gateway import TaskType, build_generation_context, context_as_brief
from .services.generation import generate_with_context

User = get_user_model()

WORKSPACES_URL = '/api/marketing/workspaces/'
BRANDS_URL = '/api/marketing/brands/'
SOURCES_URL = '/api/marketing/knowledge/sources/'
INSPIRATIONS_URL = '/api/marketing/inspirations/'
RULES_URL = '/api/marketing/brand-rules/'

DESCRIPTION = 'A micro-roastery selling single-origin beans roasted to order.'
AUDIENCE = 'Home brewers in their thirties who already own a grinder.'

FAKE_TEXT = {
    'headline': 'Roasted this week',
    'caption': 'Beans that were green on Monday.',
    'provider': 'FAKE',
    'provider_name': 'Fake',
    'latency_ms': 3,
}


class CoreProductLifecycleTests(TestCase):
    """Signup to generation, then the same records refused to a stranger."""

    def setUp(self):
        self.alice = User.objects.create_user(username='alice', password='pw')
        self.bob = User.objects.create_user(username='bob', password='pw')
        self.alice_client = APIClient()
        self.alice_client.force_authenticate(user=self.alice)
        self.bob_client = APIClient()
        self.bob_client.force_authenticate(user=self.bob)

    def _create_workspace(self, client, name):
        response = client.post(WORKSPACES_URL, {'workspace_name': name}, format='json')
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED,
            f'creating {name} failed: {response.content[:300]}',
        )
        return MarketingWorkspace.objects.get(pk=response.json()['id'])

    def test_a_new_tenant_goes_from_signup_to_a_generated_result_unaided(self):
        # --- the two tenants -------------------------------------------------
        workspace_a = self._create_workspace(self.alice_client, 'Alice Coffee')
        workspace_b = self._create_workspace(self.bob_client, 'Bob Tea')
        header_a = workspace_header(workspace_a)
        header_b = workspace_header(workspace_b)

        self.assertEqual(
            WorkspaceMember.objects.get(workspace=workspace_a, user=self.alice).role,
            WorkspaceMember.Role.OWNER,
            'the creator must own the workspace or the scoping filter locks them out',
        )

        # --- AI routing arrived with the workspace, not with an operator ------
        routed = set(
            WorkspaceAIRoute.objects.filter(
                workspace=workspace_a, enabled=True
            ).values_list('capability', flat=True)
        )
        self.assertEqual(
            routed, {Capability.TEXT, Capability.IMAGE},
            'a workspace created through the API must be routable on arrival',
        )
        self.assertTrue(
            WorkspaceAIProvider.objects.filter(
                workspace=workspace_a, enabled=True
            ).exists()
        )
        # A route the router cannot resolve looks configured and behaves like a
        # 503, so the assertion is on the router, not on the rows.
        for capability in (Capability.TEXT, Capability.IMAGE):
            with self.subTest(capability=capability):
                self.assertTrue(AIRouter(workspace_a)._candidates(capability))
        # Per tenant, not once for the installation: B was provisioned by its
        # own creation and holds its own rows.
        self.assertEqual(
            WorkspaceAIRoute.objects.filter(workspace=workspace_b, enabled=True).count(), 2
        )

        # --- the brand, created explicitly and only once ---------------------
        created = self.alice_client.post(
            BRANDS_URL, {'name': 'Acme Coffee', 'is_default': True},
            format='json', **header_a,
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.content[:300])
        brand_id = created.json()['id']
        self.assertEqual(Brand.objects.filter(workspace=workspace_a).count(), 1)
        brand_url = f'{BRANDS_URL}{brand_id}/'

        # --- Configure: the business profile the operator types in -----------
        patched = self.alice_client.patch(
            brand_url,
            {
                'website': 'https://acme.example.com',
                'location': 'Lisbon, Portugal',
                'description': DESCRIPTION,
                'audience': AUDIENCE,
                'products_services': [
                    {'name': 'Subscription', 'description': 'A bag a fortnight.'},
                    {'name': 'Single bags'},
                ],
                'social_links': {'instagram': 'https://instagram.com/acme'},
                'brand_tone': 'Warm, unfussy',
            },
            format='json', **header_a,
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK, patched.content[:300])
        saved = patched.json()
        self.assertEqual(saved['description'], DESCRIPTION)
        self.assertEqual(saved['audience'], AUDIENCE)
        self.assertEqual(saved['website'], 'https://acme.example.com')
        self.assertEqual(saved['location'], 'Lisbon, Portugal')
        self.assertEqual(saved['social_links'], {'instagram': 'https://instagram.com/acme'})
        # The server rebuilds the list, so an omitted description reads back as ''.
        self.assertEqual(
            saved['products_services'],
            [
                {'name': 'Subscription', 'description': 'A bag a fortnight.'},
                {'name': 'Single bags', 'description': ''},
            ],
        )

        # --- Teach: knowledge, an inspiration, and an explicit correction ----
        source = self.alice_client.post(
            SOURCES_URL,
            {
                'brand': brand_id,
                'title': 'Founder interview',
                'source_type': BrandSource.SourceType.TRANSCRIPT,
                'raw_text': 'We roast to order and ship within 48 hours.',
            },
            format='json', **header_a,
        )
        self.assertEqual(source.status_code, status.HTTP_201_CREATED, source.content[:300])
        source_id = source.json()['id']

        inspiration = self.alice_client.post(
            INSPIRATIONS_URL,
            {
                'brand': brand_id,
                'title': 'Reference poster',
                'inspiration_type': BrandInspiration.InspirationType.URL,
                'reference_url': 'https://example.com/poster',
                'annotation': 'The type is doing the work, not the photo.',
            },
            format='json', **header_a,
        )
        self.assertEqual(
            inspiration.status_code, status.HTTP_201_CREATED, inspiration.content[:300]
        )
        inspiration_id = inspiration.json()['id']

        rule = self.alice_client.post(
            RULES_URL,
            {
                'brand': brand_id,
                'text': 'Never describe the coffee as cheap.',
                'hardness': BrandRule.Hardness.HARD,
                'priority': 10,
            },
            format='json', **header_a,
        )
        self.assertEqual(rule.status_code, status.HTTP_201_CREATED, rule.content[:300])
        rule_id = rule.json()['data']['id']
        self.assertEqual(
            BrandRule.objects.get(pk=rule_id).origin, BrandRule.Origin.EXPLICIT,
            'a rule stated through the API is a human instruction, never a learned one',
        )

        # --- Compile the brain -----------------------------------------------
        rebuilt = self.alice_client.post(
            f'{brand_url}rebuild-brain/', format='json', **header_a
        )
        self.assertEqual(rebuilt.status_code, status.HTTP_200_OK, rebuilt.content[:300])
        brain_version = rebuilt.json()['data']['brain_version']
        self.assertTrue(brain_version)

        brand = Brand.objects.get(pk=brand_id)
        self.assertEqual(brand.creative_brain['identity']['description'], DESCRIPTION)
        self.assertEqual(brand.creative_brain['audiences']['stated'], AUDIENCE)

        # --- Use: the two new fields reach the generation context ------------
        context = build_generation_context(workspace_a, brand, TaskType.COPY)
        self.assertEqual(context['brand_identity']['description'], DESCRIPTION)
        self.assertEqual(context['audience']['stated'], AUDIENCE)
        self.assertIn(
            'Never describe the coffee as cheap.',
            [hard.get('text') for hard in context['hard_rules']],
        )

        brief_lines = context_as_brief(context)['brand_context']
        self.assertIn(f'About: {DESCRIPTION}', brief_lines)
        self.assertIn(f'Audience: {AUDIENCE}', brief_lines)

        # --- ...and survive the whole chain into what the provider is sent ---
        dispatched = {}

        def fake_dispatch(router, capability, brief, content_item_id=None):
            dispatched['capability'] = capability
            dispatched['brief'] = brief
            return dict(FAKE_TEXT)

        with patch(
            'apps.ai.router.AIRouter.dispatch', autospec=True, side_effect=fake_dispatch
        ):
            outcome = generate_with_context(workspace_a, brand, TaskType.COPY)

        self.assertEqual(outcome['result']['headline'], FAKE_TEXT['headline'])
        self.assertEqual(outcome['brain_version'], brain_version)
        self.assertEqual(dispatched['capability'], Capability.TEXT)
        self.assertIn(f'About: {DESCRIPTION}', dispatched['brief']['brand_context'])
        self.assertIn(f'Audience: {AUDIENCE}', dispatched['brief']['brand_context'])
        self.assertEqual(
            dispatched['brief']['structured']['identity']['description'], DESCRIPTION
        )

        # --- Correct: an edit moves the brain rather than being swallowed ----
        corrected = self.alice_client.patch(
            brand_url, {'audience': f'{AUDIENCE} And their gift recipients.'},
            format='json', **header_a,
        )
        self.assertEqual(corrected.status_code, status.HTTP_200_OK, corrected.content[:300])
        brand.refresh_from_db()
        self.assertNotEqual(
            brand.creative_brain['brain_version'], brain_version,
            'editing a compiled field must move the brain a generation reads',
        )
        self.assertEqual(
            build_generation_context(workspace_a, brand, TaskType.COPY)['audience']['stated'],
            f'{AUDIENCE} And their gift recipients.',
        )

        # --- The stranger: workspace B sees none of it -----------------------
        for label, list_url, record_id in (
            ('brand', BRANDS_URL, brand_id),
            ('knowledge source', SOURCES_URL, source_id),
            ('inspiration', INSPIRATIONS_URL, inspiration_id),
            ('rule', RULES_URL, rule_id),
        ):
            with self.subTest(record=label):
                detail = self.bob_client.get(f'{list_url}{record_id}/', **header_b)
                self.assertEqual(
                    detail.status_code, status.HTTP_404_NOT_FOUND,
                    f"{label} leaked to another tenant ({detail.status_code})",
                )
                listing = self.bob_client.get(list_url, **header_b)
                self.assertEqual(listing.status_code, status.HTTP_200_OK)
                rows = listing.json()
                rows = rows.get('results', rows) if isinstance(rows, dict) else rows
                self.assertNotIn(
                    str(record_id), [str(row.get('id')) for row in rows],
                    f"{list_url} listed a {label} from another tenant",
                )

        # Naming A's id in the header is not a grant either: membership is
        # re-checked per request, so the header cannot be used to address a
        # tenant the caller has never joined.
        forged = self.bob_client.get(brand_url, **header_a)
        self.assertEqual(forged.status_code, status.HTTP_403_FORBIDDEN, forged.content[:300])

        # And A's brand is untouched by any of it.
        brand.refresh_from_db()
        self.assertEqual(brand.description, DESCRIPTION)
