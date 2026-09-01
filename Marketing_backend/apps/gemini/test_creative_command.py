"""Creative Command: selected references reach generation without tenant leaks."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status

from apps.ai.models import Capability
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.content.models import ContentItem
from apps.gemini.models import GeminiGenerationRequest
from apps.inspirations.models import BrandInspiration
from apps.universal.models import LifecycleStatus, PlatformInspiration
from apps.workspaces.models import WorkspaceMember


GENERATE_URL = '/api/marketing/gemini/generate/'
GENERATE_ASYNC_URL = '/api/marketing/gemini/generate-async/'


class CreativeCommandTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Creative client', 'creative')
        self.user, self.client = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'creative-admin'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Creative Brand', is_default=True
        )
        self.other_workspace = self.make_workspace('Other client', 'other-creative')
        self.other_brand = Brand.objects.create(
            workspace=self.other_workspace, name='Other Brand', is_default=True
        )

    @staticmethod
    def dispatch(calls):
        def routed(_router, capability, brief, content_item_id=None):
            calls.append({'capability': capability, 'brief': brief})
            if capability == Capability.TEXT:
                return {
                    'headline': 'Directed launch',
                    'caption': 'Made from the chosen direction.',
                    'hashtags': '#directed',
                    'raw': {},
                    'provider': 'OPENAI',
                    'provider_name': 'OpenAI',
                }
            return {
                'image_url': 'https://cdn.example.com/directed.png',
                'provider': 'OPENAI',
                'provider_name': 'OpenAI',
            }
        return routed

    def platform_reference(self, title='Editorial reference', *, status_value=None):
        return PlatformInspiration.objects.create(
            title=title,
            kind='IMAGE',
            file_url='https://cdn.example.com/reference.png',
            annotation='Use the strong grid and restrained type.',
            tags=['editorial', 'minimal'],
            status=status_value or LifecycleStatus.PUBLISHED,
        )

    def brand_reference(self, title='Own campaign', *, brand=None, workspace=None):
        brand = brand or self.brand
        workspace = workspace or brand.workspace
        return BrandInspiration.objects.create(
            workspace=workspace,
            brand=brand,
            title=title,
            inspiration_type=BrandInspiration.InspirationType.IMAGE,
            reference_url='https://example.com/reference',
            annotation='Keep the product scale and energetic crop.',
        )

    def payload(self, selections, **extra):
        return {
            'campaignName': 'Creative launch',
            'product': 'New collection',
            'contentType': 'poster',
            'inspirationSelections': selections,
            **extra,
        }

    def test_selected_platform_and_brand_references_reach_router_and_lineage(self):
        platform = self.platform_reference()
        own = self.brand_reference()
        selections = [
            {
                'sourceType': 'PLATFORM', 'id': str(platform.pk),
                'role': 'PRIMARY', 'direction': 'USE',
                'focusAreas': ['LAYOUT', 'TYPOGRAPHY'],
            },
            {
                'sourceType': 'BRAND', 'id': str(own.pk),
                'role': 'SUPPORTING', 'direction': 'AVOID',
                'focusAreas': ['COLOR'],
            },
        ]
        calls = []
        brain_before = deepcopy(self.brand.creative_brain)
        with patch('apps.ai.router.AIRouter.dispatch', self.dispatch(calls)):
            response = self.client.post(
                GENERATE_URL,
                self.payload(selections, layout='ghost_word'),
                format='json',
                **workspace_header(self.workspace),
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        brief = next(call['brief'] for call in calls if call['capability'] == Capability.TEXT)
        direction = brief['creative_direction']
        self.assertEqual(direction['selection_count'], 2)
        self.assertEqual(direction['layout'], 'ghost_word')
        self.assertEqual(direction['selections'][0]['provenance'], 'SCALEEZY_LIBRARY')
        self.assertEqual(direction['selections'][1]['direction'], 'AVOID')
        self.assertTrue(any('AVOID' in line for line in direction['instructions']))

        item = ContentItem.objects.get(pk=response.json()['data']['contentItemId'])
        self.assertEqual(item.layout_plugin, 'ghost_word')
        self.assertEqual(item.layout_config['creative_direction']['selection_count'], 2)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.creative_brain, brain_before)

    def test_foreign_brand_reference_is_rejected_before_provider_spend(self):
        foreign = self.brand_reference(brand=self.other_brand)
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.dispatch(calls)):
            response = self.client.post(
                GENERATE_URL,
                self.payload([{
                    'sourceType': 'BRAND', 'id': str(foreign.pk),
                    'role': 'PRIMARY', 'direction': 'USE', 'focusAreas': [],
                }]),
                format='json',
                **workspace_header(self.workspace),
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['error']['code'], 'INVALID_CREATIVE_DIRECTION')
        self.assertFalse(calls)
        self.assertFalse(ContentItem.objects.exists())

    def test_unpublished_reference_and_unknown_layout_are_rejected(self):
        draft = self.platform_reference(status_value=LifecycleStatus.DRAFT)
        selection = [{
            'sourceType': 'PLATFORM', 'id': str(draft.pk),
            'role': 'PRIMARY', 'direction': 'USE', 'focusAreas': [],
        }]
        unavailable = self.client.post(
            GENERATE_URL, self.payload(selection), format='json',
            **workspace_header(self.workspace),
        )
        bad_layout = self.client.post(
            GENERATE_URL, self.payload([], layout='not-installed'), format='json',
            **workspace_header(self.workspace),
        )
        malformed = self.client.post(
            GENERATE_URL,
            self.payload([{
                'sourceType': 'BRAND', 'id': 'not-a-uuid',
                'role': 'PRIMARY', 'direction': 'USE', 'focusAreas': [],
            }]),
            format='json',
            **workspace_header(self.workspace),
        )

        self.assertEqual(unavailable.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bad_layout.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bad_layout.json()['error']['code'], 'INVALID_LAYOUT')
        self.assertEqual(malformed.status_code, status.HTTP_400_BAD_REQUEST)

    def test_selection_count_has_no_product_cap(self):
        references = [self.brand_reference(title=f'Reference {index}') for index in range(55)]
        selections = [
            {
                'sourceType': 'BRAND', 'id': str(row.pk),
                'role': 'SUPPORTING', 'direction': 'USE', 'focusAreas': [],
            }
            for row in references
        ]
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.dispatch(calls)):
            response = self.client.post(
                GENERATE_URL, self.payload(selections), format='json',
                **workspace_header(self.workspace),
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        brief = next(call['brief'] for call in calls if call['capability'] == Capability.TEXT)
        self.assertEqual(brief['creative_direction']['selection_count'], 55)

    def test_async_request_stores_resolved_direction_for_worker_revalidation(self):
        own = self.brand_reference()
        selection = [{
            'sourceType': 'BRAND', 'id': str(own.pk),
            'role': 'PRIMARY', 'direction': 'USE', 'focusAreas': ['COMPOSITION'],
        }]
        queued_task = SimpleNamespace(
            enqueue=lambda _request_id: SimpleNamespace(id='task-1')
        )
        with patch('apps.gemini.tasks.generate_content', new=queued_task):
            response = self.client.post(
                GENERATE_ASYNC_URL,
                self.payload(
                    selection,
                    contentType='carousel',
                    layout='data_hero',
                    slides=[{'position': 1, 'description': 'Opening slide'}],
                ),
                format='json',
                **workspace_header(self.workspace),
            )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.content)
        request = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )
        brief = json.loads(request.prompt_data)
        self.assertEqual(brief['creative_direction']['selection_count'], 1)
        self.assertEqual(brief['creative_direction']['selections'][0]['id'], str(own.pk))
        self.assertEqual(brief['layout'], 'data_hero')

        from apps.gemini.tasks import generate_content

        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.dispatch(calls)):
            generate_content.call(str(request.pk))
        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.COMPLETED)
        generated = ContentItem.objects.get(pk=request.result.metadata['contentItemId'])
        self.assertEqual(generated.layout_plugin, 'data_hero')
        self.assertEqual(
            generated.layout_config['creative_direction']['selections'][0]['id'],
            str(own.pk),
        )

    def test_platform_library_can_be_browsed_without_a_fifty_item_dead_end(self):
        for index in range(52):
            self.platform_reference(title=f'Platform reference {index}')

        first = self.client.get(
            '/api/marketing/universal/library/?limit=50&offset=0',
            **workspace_header(self.workspace),
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(len(first.json()['data']['inspirations']), 50)
        self.assertEqual(first.json()['data']['next_offset'], 50)

        second = self.client.get(
            '/api/marketing/universal/library/?limit=50&offset=50',
            **workspace_header(self.workspace),
        )
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(len(second.json()['data']['inspirations']), 2)
        self.assertIsNone(second.json()['data']['next_offset'])
