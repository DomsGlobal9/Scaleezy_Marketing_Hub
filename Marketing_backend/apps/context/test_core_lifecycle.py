"""
The whole product, once, through the API a customer actually calls.

Every layer of this already has its own unit tests, and all of them passed
while the product was unusable: a workspace created through the API had no AI
route, so the first generation 503'd. A defect that only appears where two
green suites meet is invisible to both of them.

So this walks one tenant through the whole core loop — sign up, create the
workspace, create the brand, describe the business, teach it, correct it,
compile, be approved, generate, save, return, edit, review, approve and queue
a publish — and then proves a member of a second workspace cannot see a single
record it produced.

Exactly one step needs an operator, and it is deliberate: a client that signed
up is PENDING and may not spend a penny of provider money until Scaleezy
approves it. The test asserts the refusal before it approves, because a gate
nobody proves is shut is a gate that quietly opens.

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
from apps.billing.models import Subscription
from apps.brands.models import Brand
from apps.brands.services.approval import SpendNotApproved, approve_brand
from apps.common.testing import workspace_header
from apps.content.models import ContentItem
from apps.inspirations.models import BrandInspiration
from apps.knowledge.models import BrandSource
from apps.learning.models import BrandRule
from apps.marketing.models import MarketingAsset
from apps.publishing.models import PublishingJob, PublishingJobItem
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

from .services.context_gateway import TaskType, build_generation_context, context_as_brief
from .services.generation import generate_with_context

User = get_user_model()

WORKSPACES_URL = '/api/marketing/workspaces/'
BRANDS_URL = '/api/marketing/brands/'
SOURCES_URL = '/api/marketing/knowledge/sources/'
INSPIRATIONS_URL = '/api/marketing/inspirations/'
RULES_URL = '/api/marketing/brand-rules/'
CONTENT_URL = '/api/marketing/content/'
PUBLISHING_URL = '/api/marketing/publishing/jobs/'

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
    """Signup through queued publishing, then every record refused to a stranger."""

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
        payload = response.json()
        workspace_data = payload.get('data', payload)
        return MarketingWorkspace.objects.get(pk=workspace_data['id'])

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

        # --- Add Client created the default brand atomically and only once ---
        self.assertEqual(Brand.objects.filter(workspace=workspace_a).count(), 1)
        default_brand = Brand.objects.get(workspace=workspace_a, is_default=True)
        brand_id = str(default_brand.id)
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

        # --- Approve: the one operator step, and it really does gate spend --
        # Everything above is free: describing the business, teaching it and
        # compiling the brain cost nothing, so a pending client can do all of
        # it. Generation is the first thing that would spend provider money,
        # and it must refuse until Scaleezy has approved the client.
        self.assertEqual(
            workspace_a.approval_status, MarketingWorkspace.Approval.PENDING,
            'a client that signed up itself must start out awaiting approval',
        )
        with self.assertRaises(SpendNotApproved) as refused:
            generate_with_context(workspace_a, brand, TaskType.COPY)
        self.assertEqual(refused.exception.code, 'CLIENT_NOT_APPROVED')

        operator = User.objects.create_user(username='scaleezy-operator', password='pw')
        approve_brand(default_brand, by=operator)
        workspace_a.refresh_from_db()
        brand.refresh_from_db()
        self.assertEqual(workspace_a.approval_status, MarketingWorkspace.Approval.APPROVED)
        self.assertEqual(brand.status, Brand.Status.ACTIVE)
        # Approval is where entitlement begins: without a subscription the
        # quota check treats the client as unlimited.
        self.assertTrue(
            Subscription.objects.filter(workspace=workspace_a).exists(),
            'approving a client must create the subscription that meters it',
        )

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

        # --- Persist: generated work becomes a durable, editable draft -------
        # Storage and OAuth are external boundaries, so their successfully
        # completed rows are fixtures. Every customer action from this point is
        # still made through the same APIs the product calls.
        asset = MarketingAsset.objects.create(
            workspace=workspace_a,
            asset_type=MarketingAsset.AssetType.POSTER,
            file_name='roasted-this-week.jpg',
            file_url='https://cdn.example.com/alice/roasted-this-week.jpg',
            source=MarketingAsset.Source.AI_GENERATED,
            created_by=self.alice,
        )
        connection = SocialConnection.objects.create(
            workspace=workspace_a,
            platform=SocialConnection.Platform.X,
            external_account_id='alice-coffee-x',
            account_name='Alice Coffee',
            username='alicecoffee',
            status=SocialConnection.Status.CONNECTED,
            publishing_enabled=True,
            connected_by=self.alice,
        )

        created_content = self.alice_client.post(
            CONTENT_URL,
            {
                'brand': brand_id,
                'asset': str(asset.id),
                'content_format': ContentItem.Format.POSTER,
                'headline': outcome['result']['headline'],
                'caption': outcome['result']['caption'],
                'hashtags': '#freshroast',
                'preview_url': asset.file_url,
                'ai_provider': outcome['result']['provider'],
            },
            format='json', **header_a,
        )
        self.assertEqual(
            created_content.status_code, status.HTTP_201_CREATED,
            created_content.content[:300],
        )
        content_id = created_content.json()['id']

        edited_content = self.alice_client.patch(
            f'{CONTENT_URL}{content_id}/',
            {
                'headline': 'Roasted this week, delivered fresh',
                'caption': 'Green on Monday. Roasted for you today.',
            },
            format='json', **header_a,
        )
        self.assertEqual(
            edited_content.status_code, status.HTTP_200_OK,
            edited_content.content[:300],
        )

        # Return in a fresh client session: the edited draft must come back
        # from the server rather than from the React state that created it.
        returning_client = APIClient()
        returning_client.force_authenticate(user=self.alice)
        returned = returning_client.get(f'{CONTENT_URL}{content_id}/', **header_a)
        self.assertEqual(returned.status_code, status.HTTP_200_OK, returned.content[:300])
        self.assertEqual(returned.json()['headline'], 'Roasted this week, delivered fresh')
        self.assertEqual(returned.json()['status'], ContentItem.Status.DRAFT)
        library = returning_client.get(CONTENT_URL, **header_a)
        self.assertEqual(library.status_code, status.HTTP_200_OK, library.content[:300])
        self.assertIn(content_id, [str(row['id']) for row in library.json()])

        submitted = returning_client.post(
            f'{CONTENT_URL}{content_id}/submit/', {}, format='json', **header_a
        )
        self.assertEqual(submitted.status_code, status.HTTP_200_OK, submitted.content[:300])
        self.assertEqual(submitted.json()['data']['status'], ContentItem.Status.PENDING_REVIEW)

        # A real MANAGER, not the creator's OWNER shortcut, performs the human
        # approval gate that makes this exact saved version publishable.
        manager = User.objects.create_user(username='alice-manager', password='pw')
        WorkspaceMember.objects.create(
            workspace=workspace_a,
            user=manager,
            role=WorkspaceMember.Role.MANAGER,
        )
        manager_client = APIClient()
        manager_client.force_authenticate(user=manager)
        approved = manager_client.post(
            f'{CONTENT_URL}{content_id}/approve/',
            {'note': 'Approved for the launch.'},
            format='json', **header_a,
        )
        self.assertEqual(approved.status_code, status.HTTP_200_OK, approved.content[:300])
        self.assertEqual(approved.json()['data']['status'], ContentItem.Status.APPROVED)

        # --- Publish: selected durable content becomes one queued job --------
        # The queue call is the external execution seam. The API must persist
        # the job and its selected account before enqueueing it.
        with patch('apps.publishing.views.publish_job') as publish_task:
            publishing = manager_client.post(
                PUBLISHING_URL,
                {
                    'workspace_id': str(workspace_a.id),
                    'asset_id': str(asset.id),
                    'content_item_id': content_id,
                    'publish_mode': PublishingJob.PublishMode.NOW,
                    # A hostile/stale client attempts to substitute copy after
                    # review. The API must derive the job caption from the
                    # approved ContentItem instead.
                    'caption': 'Unreviewed replacement copy',
                    'social_connection_ids': [str(connection.id)],
                },
                format='json', **header_a,
            )

        self.assertEqual(publishing.status_code, status.HTTP_201_CREATED, publishing.content[:300])
        job_data = publishing.json()['data']
        job_id = str(job_data['id'])
        publish_task.enqueue.assert_called_once_with(job_id)

        job = PublishingJob.objects.get(pk=job_id)
        self.assertEqual(job.status, PublishingJob.Status.QUEUED)
        self.assertEqual(str(job.content_item_id), content_id)
        self.assertEqual(job.asset, asset)
        self.assertEqual(job.created_by, manager)
        self.assertEqual(
            job.caption,
            'Roasted this week, delivered fresh\n\n'
            'Green on Monday. Roasted for you today.\n\n#freshroast',
        )
        item = PublishingJobItem.objects.get(publishing_job=job)
        self.assertEqual(item.social_connection, connection)
        self.assertEqual(item.status, PublishingJobItem.Status.QUEUED)

        # Returning to Publishing addresses the selected client and finds the
        # durable job; this is the history/library half of the customer loop.
        history = manager_client.get(PUBLISHING_URL, **header_a)
        self.assertEqual(history.status_code, status.HTTP_200_OK, history.content[:300])
        history_rows = history.json()
        history_rows = (
            history_rows.get('results', history_rows)
            if isinstance(history_rows, dict) else history_rows
        )
        self.assertEqual([str(row['id']) for row in history_rows], [job_id])
        self.assertEqual(str(history_rows[0]['content_item']), content_id)

        # --- The stranger: workspace B sees none of it -----------------------
        for label, list_url, record_id in (
            ('brand', BRANDS_URL, brand_id),
            ('knowledge source', SOURCES_URL, source_id),
            ('inspiration', INSPIRATIONS_URL, inspiration_id),
            ('rule', RULES_URL, rule_id),
            ('content item', CONTENT_URL, content_id),
            ('publishing job', PUBLISHING_URL, job_id),
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
