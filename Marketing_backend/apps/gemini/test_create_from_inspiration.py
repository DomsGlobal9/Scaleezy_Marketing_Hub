"""Focused lifecycle and attack tests for Content -> Create from inspiration."""
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.content.models import ContentItem
from apps.gemini.models import GeminiGenerationRequest, GeminiGenerationResult
from apps.inspirations.models import BrandInspiration, InspirationSignal
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember


ASYNC_URL = '/api/marketing/gemini/generate-async/'
SYNC_URLS = (
    '/api/marketing/ai-generation/generate/',
    '/api/marketing/gemini/generate/',
)


class CreateFromInspirationTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Inspired client', 'inspired-client')
        self.user, self.client = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'inspired-admin'
        )
        self.viewer, self.viewer_client = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.VIEWER, 'inspired-viewer'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Inspired Brand', is_default=True
        )
        self.other_brand = Brand.objects.create(
            workspace=self.workspace, name='Other Brand'
        )
        self.other_workspace = self.make_workspace('Foreign client', 'foreign-client')
        self.foreign_brand = Brand.objects.create(
            workspace=self.other_workspace, name='Foreign Brand', is_default=True
        )

    def reference(self, *, workspace=None, brand=None, **overrides):
        workspace = workspace or self.workspace
        brand = brand or self.brand
        values = {
            'workspace': workspace,
            'brand': brand,
            'title': 'Editorial crop',
            'inspiration_type': BrandInspiration.InspirationType.IMAGE,
            'file_url': f'https://storage.test/inspirations/{workspace.pk}/reference.png',
            'storage_path': f'inspirations/{workspace.pk}/reference.png',
            'mime_type': 'image/png',
            'file_name': 'reference.png',
            'created_by': self.user,
        }
        values.update(overrides)
        return BrandInspiration.objects.create(**values)

    @staticmethod
    def selection(reference):
        return {
            'sourceType': 'BRAND',
            'id': str(reference.pk),
            'role': 'PRIMARY',
            'direction': 'USE',
            'focusAreas': ['LAYOUT', 'COMPOSITION'],
        }

    def payload(self, reference, **overrides):
        values = {
            'campaignName': 'New season',
            'contentType': 'poster',
            'instruction': 'Create a similar poster using our brand identity.',
            'inspirationSelections': [self.selection(reference)],
            'analyzeBeforeGenerationIds': [str(reference.pk)],
            'referenceImageBase64': 'SECRET-BROWSER-BASE64',
        }
        values.update(overrides)
        return values

    def queue(self, reference, *, client=None, payload=None):
        task = SimpleNamespace(
            enqueue=lambda _request_id: SimpleNamespace(id='task-1')
        )
        with patch('apps.gemini.tasks.generate_content', new=task):
            response = (client or self.client).post(
                ASYNC_URL,
                payload or self.payload(reference),
                format='json',
                **workspace_header(self.workspace),
            )
        return response

    @staticmethod
    def routed_payload():
        return {
            'payload': {
                'postTitle': 'A fresh point of view',
                'postDescription': 'Original, on-brand campaign copy.',
                'postHashtags': '#original',
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
            'trace': {'capabilities': {'IMAGE': {'status': 'OK'}}},
        }

    def test_reference_is_preprocessed_then_saved_as_draft_with_id_only_provenance(self):
        reference = self.reference(annotation='PRIVATE QUEUE ANNOTATION')
        response = self.queue(reference)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.content)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )
        stored = json.loads(generation.prompt_data)
        self.assertEqual(stored['analyze_before_generation_ids'], [str(reference.pk)])
        self.assertEqual(stored['reference_image_base64'], '')
        self.assertNotIn('SECRET-BROWSER-BASE64', generation.prompt_data)
        self.assertNotIn('storage.test', generation.prompt_data)
        self.assertNotIn('PRIVATE QUEUE ANNOTATION', generation.prompt_data)
        self.assertNotIn('file_url', generation.prompt_data)
        self.assertNotIn('reference_url', generation.prompt_data)
        self.assertNotIn('signals', generation.prompt_data)
        self.assertEqual(stored['brand_rules'], [])

        def analyze(reference_id):
            inspiration = BrandInspiration.objects.get(pk=reference_id)
            InspirationSignal.objects.create(
                inspiration=inspiration,
                category='LAYOUT',
                attribute='composition',
                value='Asymmetric editorial grid',
                sentiment=InspirationSignal.Sentiment.LIKED,
                origin=InspirationSignal.Origin.AI,
                user_confirmation=InspirationSignal.UserConfirmation.PENDING,
                extracted_by_provider='vision-ai',
            )
            inspiration.analysis_status = BrandInspiration.AnalysisStatus.NEEDS_REVIEW
            inspiration.save(update_fields=['analysis_status', 'updated_at'])
            return {'inspiration': str(inspiration.pk), 'signals': 1}

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.inspirations.analysis.analyze_inspiration', side_effect=analyze
        ) as analyzed, patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=self.routed_payload(),
        ) as generated:
            generate_content.call(str(generation.pk))

        analyzed.assert_called_once_with(str(reference.pk))
        self.assertEqual(
            generated.call_args.kwargs['instruction'],
            'Create a similar poster using our brand identity.',
        )
        direction = generated.call_args.args[1]['creative_direction']
        prompt = ' '.join(direction['instructions'])
        self.assertIn('new, original composition', prompt)
        self.assertIn('campaign-only; not Brand Brain facts', prompt)

        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.COMPLETED)
        item = ContentItem.objects.get(pk=generation.result.metadata['contentItemId'])
        self.assertEqual(item.status, ContentItem.Status.DRAFT)
        saved_direction = item.layout_config['creative_direction']
        self.assertEqual(saved_direction['selections'][0]['id'], str(reference.pk))
        self.assertEqual(
            saved_direction['selections'][0]['provenance'], 'BRAND_INSPIRATION'
        )

    def test_wrong_tenant_and_wrong_brand_references_are_rejected_before_queue(self):
        wrong_rows = [
            self.reference(brand=self.other_brand),
            self.reference(workspace=self.other_workspace, brand=self.foreign_brand),
        ]
        for reference in wrong_rows:
            response = self.queue(reference)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(GeminiGenerationRequest.objects.exists())

    def test_preprocessing_id_must_be_a_selected_brand_reference(self):
        selected = self.reference()
        hidden = self.reference(title='Not selected')
        response = self.queue(
            selected,
            payload=self.payload(
                selected, analyzeBeforeGenerationIds=[str(hidden.pk)]
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()['error']['code'], 'INVALID_INSPIRATION_PREPROCESSING'
        )
        self.assertFalse(GeminiGenerationRequest.objects.exists())

    def test_archived_after_queue_fails_before_analysis_or_generation(self):
        reference = self.reference()
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )
        reference.lifecycle_status = BrandInspiration.LifecycleStatus.ARCHIVED
        reference.save(update_fields=['lifecycle_status', 'updated_at'])

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

    def test_zero_analysis_observations_fails_instead_of_claiming_similarity(self):
        reference = self.reference()
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.inspirations.analysis.analyze_inspiration',
            return_value={'inspiration': str(reference.pk), 'signals': 0},
        ), patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as generated, self.assertRaisesRegex(ValueError, 'no usable creative observations'):
            generate_content.call(str(generation.pk))
        generated.assert_not_called()
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.FAILED)

    def test_legacy_ready_reference_without_observations_is_reanalysed(self):
        reference = self.reference(
            analysis_status=BrandInspiration.AnalysisStatus.READY
        )
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

        def analyze(reference_id):
            InspirationSignal.objects.create(
                inspiration=reference,
                category='LAYOUT',
                attribute='hierarchy',
                value='One dominant headline above a compact body',
                sentiment=InspirationSignal.Sentiment.LIKED,
                origin=InspirationSignal.Origin.AI,
                user_confirmation=InspirationSignal.UserConfirmation.PENDING,
            )
            return {'inspiration': reference_id, 'signals': 1}

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.inspirations.analysis.analyze_inspiration', side_effect=analyze
        ) as analyzed, patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=self.routed_payload(),
        ):
            generate_content.call(str(generation.pk))

        analyzed.assert_called_once_with(str(reference.pk))
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.COMPLETED)

    def test_stale_processing_inspiration_is_recovered_on_worker_rescue(self):
        reference = self.reference(
            analysis_status=BrandInspiration.AnalysisStatus.PROCESSING,
            metadata={
                'analysis': {
                    'started_at': (timezone.now() - timedelta(minutes=11)).isoformat()
                }
            },
        )
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

        def analyze(reference_id):
            InspirationSignal.objects.create(
                inspiration=reference,
                category='LAYOUT',
                attribute='grid',
                value='Editorial grid',
                sentiment=InspirationSignal.Sentiment.LIKED,
                origin=InspirationSignal.Origin.AI,
                user_confirmation=InspirationSignal.UserConfirmation.PENDING,
            )
            return {'inspiration': reference_id, 'signals': 1}

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.inspirations.analysis.analyze_inspiration', side_effect=analyze
        ) as analyzed, patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=self.routed_payload(),
        ):
            generate_content.call(str(generation.pk))
        analyzed.assert_called_once_with(str(reference.pk))
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.COMPLETED)

    def test_fresh_processing_inspiration_is_not_reanalysed(self):
        reference = self.reference(
            analysis_status=BrandInspiration.AnalysisStatus.PROCESSING,
            metadata={'analysis': {'started_at': timezone.now().isoformat()}},
        )
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

        from apps.gemini.tasks import generate_content

        with patch('apps.inspirations.analysis.analyze_inspiration') as analyzed, patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as generated, self.assertRaisesRegex(ValueError, 'already being analysed'):
            generate_content.call(str(generation.pk))
        analyzed.assert_not_called()
        generated.assert_not_called()

    def test_viewer_cannot_spend_through_preprocessing(self):
        reference = self.reference()
        response = self.queue(reference, client=self.viewer_client)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(GeminiGenerationRequest.objects.exists())

    def test_viewer_cannot_spend_with_ready_brand_reference_either(self):
        reference = self.reference(
            analysis_status=BrandInspiration.AnalysisStatus.READY
        )
        InspirationSignal.objects.create(
            inspiration=reference,
            category='LAYOUT',
            attribute='grid',
            value='Editorial grid',
            sentiment=InspirationSignal.Sentiment.LIKED,
            origin=InspirationSignal.Origin.AI,
            user_confirmation=InspirationSignal.UserConfirmation.PENDING,
        )
        payload = self.payload(reference, analyzeBeforeGenerationIds=[])
        response = self.queue(reference, client=self.viewer_client, payload=payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(GeminiGenerationRequest.objects.exists())

    def test_viewer_cannot_use_brand_reference_on_either_sync_alias(self):
        reference = self.reference(
            analysis_status=BrandInspiration.AnalysisStatus.READY
        )
        payload = self.payload(reference, analyzeBeforeGenerationIds=[])
        for url in SYNC_URLS:
            response = self.viewer_client.post(
                url,
                payload,
                format='json',
                **workspace_header(self.workspace),
            )
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(ContentItem.objects.exists())

    def test_sync_aliases_reject_inspiration_preprocessing(self):
        reference = self.reference()
        payload = self.payload(reference)
        for url in SYNC_URLS:
            response = self.client.post(
                url,
                payload,
                format='json',
                **workspace_header(self.workspace),
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()['error']['code'], 'ASYNC_REQUIRED')
        self.assertFalse(ContentItem.objects.exists())

    def test_viewer_cannot_bypass_brand_gate_with_whitespace_or_case(self):
        reference = self.reference(
            analysis_status=BrandInspiration.AnalysisStatus.READY
        )
        payload = self.payload(reference, analyzeBeforeGenerationIds=[])
        payload['inspirationSelections'][0]['sourceType'] = ' bRaNd '

        async_response = self.queue(
            reference, client=self.viewer_client, payload=payload
        )
        self.assertEqual(async_response.status_code, status.HTTP_403_FORBIDDEN)
        for url in SYNC_URLS:
            response = self.viewer_client.post(
                url,
                payload,
                format='json',
                **workspace_header(self.workspace),
            )
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(GeminiGenerationRequest.objects.exists())
        self.assertFalse(ContentItem.objects.exists())

    def test_queue_failure_is_failed_and_does_not_expose_infrastructure_error(self):
        reference = self.reference()
        def fail_queue(_request_id):
            raise RuntimeError('secret queue connection string')

        with patch(
            'apps.gemini.tasks.generate_content',
            new=SimpleNamespace(enqueue=fail_queue),
        ):
            response = self.client.post(
                ASYNC_URL,
                self.payload(reference),
                format='json',
                **workspace_header(self.workspace),
            )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        body = response.json()
        self.assertEqual(body['error']['code'], 'QUEUE_FAILED')
        self.assertNotIn('secret queue', str(body))
        generation = GeminiGenerationRequest.objects.get()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.FAILED)

    def test_suspended_after_queue_fails_before_analysis_or_provider(self):
        reference = self.reference()
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )
        self.workspace.status = MarketingWorkspace.Status.SUSPENDED
        self.workspace.save(update_fields=['status', 'updated_at'])

        from apps.gemini.tasks import generate_content

        with patch('apps.inspirations.analysis.analyze_inspiration') as analyzed, patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as generated:
            result = generate_content.call(str(generation.pk))
        self.assertEqual(result['status'], 'FAILED')
        analyzed.assert_not_called()
        generated.assert_not_called()
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.FAILED)

    def test_redelivered_task_cannot_run_alongside_active_worker(self):
        reference = self.reference()
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )
        generation.status = GeminiGenerationRequest.Status.GENERATING
        generation.save(update_fields=['status', 'updated_at'])

        from apps.gemini.tasks import generate_content

        with patch('apps.inspirations.analysis.analyze_inspiration') as analyzed, patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as generated:
            result = generate_content.call(str(generation.pk))
        self.assertEqual(result['status'], 'ALREADY_RUNNING')
        analyzed.assert_not_called()
        generated.assert_not_called()
        self.assertFalse(ContentItem.objects.exists())

    def test_archived_brand_after_queue_fails_before_analysis_or_provider(self):
        reference = self.reference()
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )
        self.brand.status = Brand.Status.ARCHIVED
        self.brand.save(update_fields=['status', 'updated_at'])

        from apps.gemini.tasks import generate_content

        with patch('apps.inspirations.analysis.analyze_inspiration') as analyzed, patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as generated, self.assertRaisesRegex(ValueError, 'brand is inactive'):
            generate_content.call(str(generation.pk))
        analyzed.assert_not_called()
        generated.assert_not_called()
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.FAILED)
        self.assertFalse(ContentItem.objects.exists())

    def test_brand_archived_during_analysis_fails_before_provider(self):
        reference = self.reference()
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

        def analyze(reference_id):
            inspiration = BrandInspiration.objects.get(pk=reference_id)
            InspirationSignal.objects.create(
                inspiration=inspiration,
                category='LAYOUT',
                attribute='grid',
                value='Editorial grid',
                sentiment=InspirationSignal.Sentiment.LIKED,
                origin=InspirationSignal.Origin.AI,
                user_confirmation=InspirationSignal.UserConfirmation.PENDING,
            )
            self.brand.status = Brand.Status.ARCHIVED
            self.brand.save(update_fields=['status', 'updated_at'])
            return {'inspiration': reference_id, 'signals': 1}

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.inspirations.analysis.analyze_inspiration', side_effect=analyze
        ), patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as generated, self.assertRaisesRegex(ValueError, 'brand is inactive'):
            generate_content.call(str(generation.pk))
        generated.assert_not_called()
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.FAILED)
        self.assertFalse(ContentItem.objects.exists())

    def test_preprocessing_rejects_non_poster_content(self):
        reference = self.reference()
        for content_type in ('video', 'carousel'):
            response = self.queue(
                reference,
                payload=self.payload(reference, contentType=content_type),
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json()['error']['code'],
                'INVALID_INSPIRATION_PREPROCESSING',
            )
        self.assertFalse(GeminiGenerationRequest.objects.exists())

    def test_image_failure_cannot_persist_copy_only_similarity_claim(self):
        reference = self.reference(
            analysis_status=BrandInspiration.AnalysisStatus.READY
        )
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

        InspirationSignal.objects.create(
            inspiration=reference,
            category='LAYOUT',
            attribute='grid',
            value='Editorial grid',
            sentiment=InspirationSignal.Sentiment.LIKED,
            origin=InspirationSignal.Origin.AI,
            user_confirmation=InspirationSignal.UserConfirmation.PENDING,
        )
        failed_image = self.routed_payload()
        failed_image['payload']['posterImageUrl'] = ''
        failed_image['payload']['metadata'] = {}
        failed_image['trace']['capabilities']['IMAGE'] = {
            'status': 'FAILED',
            'error': 'image provider unavailable',
        }

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=failed_image,
        ), self.assertRaisesRegex(RuntimeError, 'did not produce an image'):
            generate_content.call(str(generation.pk))
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.FAILED)
        self.assertFalse(ContentItem.objects.exists())

    def test_compose_failure_keeps_one_completed_draft(self):
        reference = self.reference(
            analysis_status=BrandInspiration.AnalysisStatus.READY
        )
        InspirationSignal.objects.create(
            inspiration=reference,
            category='LAYOUT',
            attribute='grid',
            value='Editorial grid',
            sentiment=InspirationSignal.Sentiment.LIKED,
            origin=InspirationSignal.Origin.AI,
            user_confirmation=InspirationSignal.UserConfirmation.PENDING,
        )
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=self.routed_payload(),
        ), patch(
            'apps.layouts.services.compose_generated_poster',
            side_effect=RuntimeError('layout storage unavailable'),
        ):
            generate_content.call(str(generation.pk))

        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.COMPLETED)
        self.assertEqual(ContentItem.objects.count(), 1)
        self.assertTrue(GeminiGenerationResult.objects.filter(
            generation_request=generation
        ).exists())

    def test_result_persistence_failure_rolls_back_draft(self):
        reference = self.reference(
            analysis_status=BrandInspiration.AnalysisStatus.READY
        )
        InspirationSignal.objects.create(
            inspiration=reference,
            category='LAYOUT',
            attribute='grid',
            value='Editorial grid',
            sentiment=InspirationSignal.Sentiment.LIKED,
            origin=InspirationSignal.Origin.AI,
            user_confirmation=InspirationSignal.UserConfirmation.PENDING,
        )
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=self.routed_payload(),
        ), patch.object(
            GeminiGenerationResult.objects,
            'update_or_create',
            side_effect=RuntimeError('result database unavailable'),
        ), self.assertRaisesRegex(RuntimeError, 'result database unavailable'):
            generate_content.call(str(generation.pk))

        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.FAILED)
        self.assertFalse(ContentItem.objects.exists())
        self.assertFalse(GeminiGenerationResult.objects.exists())

    def test_inspiration_revoked_during_provider_call_is_not_persisted(self):
        reference = self.reference(
            analysis_status=BrandInspiration.AnalysisStatus.READY
        )
        InspirationSignal.objects.create(
            inspiration=reference,
            category='LAYOUT',
            attribute='grid',
            value='Editorial grid',
            sentiment=InspirationSignal.Sentiment.LIKED,
            origin=InspirationSignal.Origin.AI,
            user_confirmation=InspirationSignal.UserConfirmation.PENDING,
        )
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

        def generate(*_args, **_kwargs):
            reference.lifecycle_status = BrandInspiration.LifecycleStatus.ARCHIVED
            reference.save(update_fields=['lifecycle_status', 'updated_at'])
            return self.routed_payload()

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            side_effect=generate,
        ), self.assertRaisesRegex(ValueError, 'revoked'):
            generate_content.call(str(generation.pk))
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.FAILED)
        self.assertFalse(ContentItem.objects.exists())

    def test_default_brand_switch_cannot_reassign_inspiration_output(self):
        reference = self.reference(
            analysis_status=BrandInspiration.AnalysisStatus.READY
        )
        InspirationSignal.objects.create(
            inspiration=reference,
            category='LAYOUT',
            attribute='grid',
            value='Editorial grid',
            sentiment=InspirationSignal.Sentiment.LIKED,
            origin=InspirationSignal.Origin.AI,
            user_confirmation=InspirationSignal.UserConfirmation.PENDING,
        )
        response = self.queue(reference)
        generation = GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

        def generate(*_args, **kwargs):
            self.assertEqual(kwargs['brand'].pk, self.brand.pk)
            self.brand.is_default = False
            self.brand.save(update_fields=['is_default', 'updated_at'])
            self.other_brand.is_default = True
            self.other_brand.save(update_fields=['is_default', 'updated_at'])
            return self.routed_payload()

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            side_effect=generate,
        ):
            generate_content.call(str(generation.pk))

        item = ContentItem.objects.get()
        self.assertEqual(item.brand_id, self.brand.pk)

    def test_instruction_and_preprocessing_list_are_bounded(self):
        reference = self.reference()
        too_long = self.queue(
            reference,
            payload=self.payload(reference, instruction='x' * 1001),
        )
        self.assertEqual(too_long.status_code, status.HTTP_400_BAD_REQUEST)
        too_many = self.queue(
            reference,
            payload=self.payload(
                reference,
                analyzeBeforeGenerationIds=[str(reference.pk)] * 13,
            ),
        )
        self.assertEqual(too_many.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(GeminiGenerationRequest.objects.exists())
