"""Brand-template defaulting: an unstated creative choice follows the brand's
uploaded poster templates.

The founder removed the built-in catalogue; its replacement is BRAND_TEMPLATE
inspirations the brand uploads itself. When a generation arrives with no
creative mode, no selections, no layout and no uploaded reference:

* templates exist  -> REFERENCE mode against one template, rotated
  least-recently-used (deterministic tie-break), riding the exact
  create-from-inspiration analysis/eligibility/lock machinery;
* no templates     -> raw AI_ORIGINAL output;
* an explicit user choice always wins and never enters the default.
"""
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.content.models import ContentItem
from apps.context.services.creative_direction import (
    brand_template_rotation_queryset,
    default_creative_direction,
    next_brand_template,
)
from apps.gemini.models import GeminiGenerationRequest
from apps.inspirations.models import BrandInspiration, InspirationSignal
from apps.workspaces.models import WorkspaceMember

GENERATE_URL = '/api/marketing/gemini/generate/'
GENERATE_ASYNC_URL = '/api/marketing/gemini/generate-async/'


_UPLOAD_SEQUENCE = {'count': 0}


def make_template(workspace, brand, title, *, used_at=None, archived=False, user=None):
    row = BrandInspiration.objects.create(
        workspace=workspace,
        brand=brand,
        title=title,
        inspiration_type=BrandInspiration.InspirationType.BRAND_TEMPLATE,
        file_url=f'https://storage.test/inspirations/{workspace.pk}/{title}.png',
        storage_path=f'inspirations/{workspace.pk}/{title}.png',
        mime_type='image/png',
        file_name=f'{title}.png',
        created_by=user,
    )
    # Rapid same-microsecond creates would leave the created_at tie-break to
    # random UUID pks; give every fixture a strictly increasing upload time
    # so "upload order" in assertions means exactly that.
    _UPLOAD_SEQUENCE['count'] += 1
    BrandInspiration.objects.filter(pk=row.pk).update(
        created_at=timezone.now()
        - timedelta(hours=1)
        + timedelta(seconds=_UPLOAD_SEQUENCE['count']),
        template_last_used_at=used_at,
    )
    row.refresh_from_db(fields=['created_at', 'template_last_used_at'])
    if archived:
        row.lifecycle_status = BrandInspiration.LifecycleStatus.ARCHIVED
        row.save(update_fields=['lifecycle_status', 'updated_at'])
    return row


class TemplateRotationTests(TenantFixtureMixin, TestCase):
    """The rotation math: least-recently-used first, deterministic ties."""

    def setUp(self):
        self.workspace = self.make_workspace('Rotation client', 'rotation')
        self.user, self.client = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'rotation-admin'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Rotation Brand', is_default=True
        )

    def template(self, title, **kwargs):
        return make_template(self.workspace, self.brand, title, user=self.user, **kwargs)

    def test_never_used_templates_lead_then_oldest_clock_then_created_order(self):
        now = timezone.now()
        stale = self.template('used-long-ago', used_at=now - timedelta(days=7))
        fresh = self.template('used-today', used_at=now)
        first_upload = self.template('never-used-a')
        second_upload = self.template('never-used-b')

        ordered = list(brand_template_rotation_queryset(self.workspace, self.brand))
        self.assertEqual(
            [row.pk for row in ordered],
            # NULL clocks first in upload order, then oldest clock first.
            [first_upload.pk, second_upload.pk, stale.pk, fresh.pk],
        )

    def test_rotation_cycles_deterministically_and_stamps_the_clock(self):
        a = self.template('a')
        b = self.template('b')
        c = self.template('c')

        picks = [next_brand_template(self.workspace, self.brand).pk for _ in range(6)]
        self.assertEqual(picks, [a.pk, b.pk, c.pk, a.pk, b.pk, c.pk])
        a.refresh_from_db(fields=['template_last_used_at'])
        self.assertIsNotNone(a.template_last_used_at)

    def test_archived_templates_leave_the_rotation(self):
        self.template('gone', archived=True)
        live = self.template('live')
        self.assertEqual(next_brand_template(self.workspace, self.brand).pk, live.pk)
        self.assertEqual(next_brand_template(self.workspace, self.brand).pk, live.pk)

    def test_no_templates_or_no_brand_yields_none_and_ai_original_default(self):
        self.assertIsNone(next_brand_template(self.workspace, self.brand))
        self.assertIsNone(next_brand_template(self.workspace, None))
        direction, template_ids = default_creative_direction(
            self.workspace, self.brand
        )
        self.assertEqual(direction['mode'], 'AI_ORIGINAL')
        self.assertEqual(template_ids, [])

    def test_other_inspiration_types_never_enter_the_rotation(self):
        BrandInspiration.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            title='Ordinary reference',
            inspiration_type=BrandInspiration.InspirationType.IMAGE,
            reference_url='https://example.com/reference',
        )
        self.assertIsNone(next_brand_template(self.workspace, self.brand))

    def test_default_direction_with_template_is_reference_with_analysis_ids(self):
        template = self.template('brand-poster')
        direction, template_ids = default_creative_direction(
            self.workspace, self.brand
        )
        self.assertEqual(direction['mode'], 'REFERENCE')
        self.assertEqual(
            [row['id'] for row in direction['selections']], [str(template.pk)]
        )
        self.assertEqual(template_ids, [str(template.pk)])
        prompt = ' '.join(direction['instructions'])
        self.assertIn('BRAND TEMPLATE', prompt)
        self.assertIn('brand\'s own', prompt)

    def test_non_poster_default_never_uses_a_template(self):
        self.template('poster-design')
        direction, template_ids = default_creative_direction(
            self.workspace, self.brand, allow_template=False
        )
        self.assertEqual(direction['mode'], 'AI_ORIGINAL')
        self.assertEqual(template_ids, [])


class TemplateDefaultingViewTests(TenantFixtureMixin, TestCase):
    """The generation endpoints apply the default; explicit choices win."""

    def setUp(self):
        self.workspace = self.make_workspace('Template client', 'template-client')
        self.user, self.client = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'template-admin'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Template Brand', is_default=True
        )

    @staticmethod
    def dispatch(calls):
        """Same router double the creative-command tests use."""
        from apps.ai.models import Capability

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

    def payload(self, selections, **extra):
        return {
            'creativeMode': 'REFERENCE' if selections else 'AI_ORIGINAL',
            'campaignName': 'Creative launch',
            'product': 'New collection',
            'contentType': 'poster',
            'inspirationSelections': selections,
            **extra,
        }

    def brand_reference(self, title='Own campaign'):
        return BrandInspiration.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            title=title,
            inspiration_type=BrandInspiration.InspirationType.IMAGE,
            reference_url='https://example.com/reference',
            annotation='Keep the product scale and energetic crop.',
        )

    def template(self, title='House style', **kwargs):
        return make_template(self.workspace, self.brand, title, user=self.user, **kwargs)

    def test_sync_no_choice_with_templates_generates_reference_against_lru(self):
        now = timezone.now()
        self.template('recently used', used_at=now)
        overdue = self.template('overdue')

        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.dispatch(calls)):
            response = self.client.post(
                GENERATE_URL,
                {'campaignName': 'Creative launch', 'contentType': 'poster'},
                format='json',
                **workspace_header(self.workspace),
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        item = ContentItem.objects.get()
        direction = item.layout_config['creative_direction']
        self.assertEqual(direction['mode'], 'REFERENCE')
        self.assertEqual(
            [row['id'] for row in direction['selections']], [str(overdue.pk)]
        )
        overdue.refresh_from_db(fields=['template_last_used_at'])
        self.assertIsNotNone(overdue.template_last_used_at)
        # The raw AI poster ships undressed for REFERENCE generations.
        self.assertEqual(item.layout_plugin, '')

    def test_explicit_ai_original_wins_over_existing_templates(self):
        template = self.template()
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.dispatch(calls)):
            response = self.client.post(
                GENERATE_URL,
                self.payload([]),  # creativeMode AI_ORIGINAL, no selections
                format='json',
                **workspace_header(self.workspace),
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        item = ContentItem.objects.get()
        self.assertEqual(item.layout_config['creative_direction']['mode'], 'AI_ORIGINAL')
        template.refresh_from_db(fields=['template_last_used_at'])
        self.assertIsNone(template.template_last_used_at)

    def test_explicit_reference_selection_wins_over_template_rotation(self):
        self.template()
        own = self.brand_reference()
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', self.dispatch(calls)):
            response = self.client.post(
                GENERATE_URL,
                self.payload([{
                    'sourceType': 'BRAND', 'id': str(own.pk),
                    'role': 'PRIMARY', 'direction': 'USE', 'focusAreas': [],
                }]),
                format='json',
                **workspace_header(self.workspace),
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        item = ContentItem.objects.get()
        self.assertEqual(
            [row['id'] for row in item.layout_config['creative_direction']['selections']],
            [str(own.pk)],
        )

    def test_async_no_choice_with_templates_queues_the_full_inspiration_brief(self):
        template = self.template()
        from types import SimpleNamespace

        task = SimpleNamespace(enqueue=lambda _id: SimpleNamespace(id='task-1'))
        with patch('apps.gemini.tasks.generate_content', new=task):
            response = self.client.post(
                GENERATE_ASYNC_URL,
                {'campaignName': 'Creative launch', 'contentType': 'poster'},
                format='json',
                **workspace_header(self.workspace),
            )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.content)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )
        brief = json.loads(generation.prompt_data)
        self.assertEqual(brief['analyze_before_generation_ids'], [str(template.pk)])
        self.assertEqual(brief['creative_direction']['mode'], 'REFERENCE')
        self.assertEqual(
            [row['id'] for row in brief['creative_direction']['selections']],
            [str(template.pk)],
        )
        # ID-only provenance, exactly like a queued create-from-inspiration
        # brief: no resolved URLs or annotations in durable state.
        self.assertNotIn('file_url', generation.prompt_data)
        self.assertEqual(brief['reference_image_base64'], '')
        self.assertEqual(brief['brand_rules'], [])

    def test_async_no_choice_for_video_stays_ai_original_despite_templates(self):
        self.template()
        from types import SimpleNamespace

        task = SimpleNamespace(enqueue=lambda _id: SimpleNamespace(id='task-1'))
        with patch('apps.gemini.tasks.generate_content', new=task):
            response = self.client.post(
                GENERATE_ASYNC_URL,
                {'campaignName': 'Creative launch', 'contentType': 'video'},
                format='json',
                **workspace_header(self.workspace),
            )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.content)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )
        brief = json.loads(generation.prompt_data)
        self.assertEqual(brief['creative_direction']['mode'], 'AI_ORIGINAL')
        self.assertEqual(brief['analyze_before_generation_ids'], [])

    def test_defaulted_template_faces_the_same_locks_as_a_selected_inspiration(self):
        """Archive the template after queueing: the worker must refuse."""
        template = self.template()
        from types import SimpleNamespace

        task = SimpleNamespace(enqueue=lambda _id: SimpleNamespace(id='task-1'))
        with patch('apps.gemini.tasks.generate_content', new=task):
            response = self.client.post(
                GENERATE_ASYNC_URL,
                {'campaignName': 'Creative launch', 'contentType': 'poster'},
                format='json',
                **workspace_header(self.workspace),
            )
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )
        template.lifecycle_status = BrandInspiration.LifecycleStatus.ARCHIVED
        template.save(update_fields=['lifecycle_status', 'updated_at'])

        from apps.gemini.tasks import generate_content

        with patch('apps.inspirations.analysis.analyze_inspiration') as analyzed, patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as generated, self.assertRaisesRegex(ValueError, 'unavailable'):
            generate_content.call(str(generation.pk))
        analyzed.assert_not_called()
        generated.assert_not_called()
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.FAILED)
        self.assertFalse(ContentItem.objects.exists())

    def test_defaulted_template_is_analysed_then_signals_reach_the_brief(self):
        """The worker analyses the template and its observations steer the
        provider brief — the create-from-inspiration pipeline end to end."""
        template = self.template()
        from types import SimpleNamespace

        task = SimpleNamespace(enqueue=lambda _id: SimpleNamespace(id='task-1'))
        with patch('apps.gemini.tasks.generate_content', new=task):
            response = self.client.post(
                GENERATE_ASYNC_URL,
                {'campaignName': 'Creative launch', 'contentType': 'poster'},
                format='json',
                **workspace_header(self.workspace),
            )
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

        def analyze(reference_id):
            inspiration = BrandInspiration.objects.get(pk=reference_id)
            InspirationSignal.objects.create(
                inspiration=inspiration,
                category='LAYOUT',
                attribute='composition',
                value='Full-bleed photo, headline band across the lower third',
                sentiment=InspirationSignal.Sentiment.LIKED,
                origin=InspirationSignal.Origin.AI,
                user_confirmation=InspirationSignal.UserConfirmation.PENDING,
                extracted_by_provider='vision-ai',
            )
            inspiration.analysis_status = BrandInspiration.AnalysisStatus.NEEDS_REVIEW
            inspiration.save(update_fields=['analysis_status', 'updated_at'])
            return {'inspiration': str(inspiration.pk), 'signals': 1}

        routed = {
            'payload': {
                'postTitle': 'Matched to the house template',
                'postDescription': 'Copy in the template look.',
                'postHashtags': '#template',
                'posterImageUrl': 'https://storage.test/generated/poster.png',
                'metadata': {
                    'generated_image': {
                        'image_url': 'https://storage.test/generated/poster.png',
                        'storage_path': 'generated/poster.png',
                        'mime_type': 'image/png',
                        'file_name': 'poster.png',
                    },
                },
            },
            'provider': 'image-ai',
            'provider_name': 'Image AI',
            'brain_version': 'brain-v1',
            'trace': {},
        }

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.inspirations.analysis.analyze_inspiration', side_effect=analyze
        ) as analyzed, patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=routed,
        ) as generated:
            generate_content.call(str(generation.pk))

        analyzed.assert_called_once_with(str(template.pk))
        direction = generated.call_args.args[1]['creative_direction']
        prompt = ' '.join(direction['instructions'])
        self.assertIn('BRAND TEMPLATE', prompt)
        self.assertIn('headline band across the lower third', prompt)
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.COMPLETED)
        item = ContentItem.objects.get(pk=generation.result.metadata['contentItemId'])
        saved = item.layout_config['creative_direction']
        self.assertEqual(saved['mode'], 'REFERENCE')
        self.assertEqual(saved['selections'][0]['id'], str(template.pk))
        # Raw AI poster: no built-in dress on a REFERENCE generation.
        self.assertEqual(item.layout_plugin, '')
