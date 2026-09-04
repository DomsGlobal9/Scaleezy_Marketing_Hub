"""Studio authority, durable retry ownership and recovery of paid partial work."""
import uuid
from unittest.mock import patch

from django.db import connection
from django.tasks import TaskResultStatus
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.content.models import ContentItem
from apps.gemini.models import GeminiGenerationRequest
from apps.gemini.tasks import generate_content
from apps.jobs.models import TaskRun
from apps.jobs.runner import claim, execute
from apps.marketing.models import MarketingAsset
from apps.workspaces.models import WorkspaceMember


class StudioClosureTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Studio', 'studio')
        self.user, self.client = self.authenticate_as(self.workspace, WorkspaceMember.Role.EDITOR, 'editor')
        self.brand = Brand.objects.create(workspace=self.workspace, name='Studio', is_default=True, status='ACTIVE')
        self.headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.pk)}
        self.payload = {'creativeMode': 'AI_ORIGINAL', 'contentType': 'poster', 'campaignName': 'Launch'}
        self.routed = {
            'provider': 'test', 'provider_name': 'Test', 'brain_version': '',
            'payload': {'postTitle': 'Paid copy', 'postDescription': 'Keep these words', 'postHashtags': '#saved', 'metadata': {}},
            'trace': {'capabilities': {'TEXT': {'status': 'OK'}, 'IMAGE': {'status': 'FAILED', 'error': 'Image storage failed'}}},
        }

    def enqueue(self, **extra):
        response = self.client.post('/api/marketing/ai-generation/generate-async/', {**self.payload, **extra}, format='json', **self.headers)
        self.assertEqual(response.status_code, 202, response.data)
        return GeminiGenerationRequest.objects.get(pk=response.data['data']['generationId'])

    def partial(self):
        generation = self.enqueue()
        with patch('apps.context.services.generation.generate_marketing_payload', return_value=self.routed), patch('apps.layouts.services.compose_generated_poster'):
            self.assertTrue(execute(claim()))
        generation.refresh_from_db()
        return generation

    def test_viewer_cannot_mutate_any_alias_or_creative_mode(self):
        _, viewer = self.authenticate_as(self.workspace, WorkspaceMember.Role.VIEWER, 'viewer')
        generation = GeminiGenerationRequest.objects.create(workspace=self.workspace, user=self.user)
        for alias in ('ai-generation', 'gemini'):
            base = f'/api/marketing/{alias}/'
            for mode in ('AI_ORIGINAL', 'CATALOG_TEMPLATE', 'REFERENCE'):
                for action in ('generate/', 'generate-async/'):
                    with self.subTest(alias=alias, mode=mode, action=action):
                        response = viewer.post(base + action, {**self.payload, 'creativeMode': mode}, format='json', **self.headers)
                        self.assertEqual(response.status_code, 403)
            for action in ('analyze-image/', 'analyze-video/', 'generate-captions/', f'{generation.pk}/retry-image/'):
                self.assertEqual(viewer.post(base + action, {}, format='json', **self.headers).status_code, 403)
            self.assertEqual(viewer.get(base, **self.headers).status_code, 200)
            self.assertEqual(viewer.get(base + f'{generation.pk}/', **self.headers).status_code, 200)
        self.assertEqual(GeminiGenerationRequest.objects.count(), 1)
        self.assertFalse(TaskRun.objects.exists())

    def test_generic_writes_are_unavailable_even_to_editor(self):
        generation = GeminiGenerationRequest.objects.create(workspace=self.workspace, user=self.user)
        for alias in ('ai-generation', 'gemini'):
            base = f'/api/marketing/{alias}/'
            for method, path in (('post', base), ('put', base + f'{generation.pk}/'), ('patch', base + f'{generation.pk}/'), ('delete', base + f'{generation.pk}/')):
                self.assertEqual(getattr(self.client, method)(path, {}, format='json', **self.headers).status_code, 405)
        self.assertTrue(GeminiGenerationRequest.objects.filter(pk=generation.pk).exists())

    def test_delivery_key_reuses_one_request_and_one_task(self):
        key = str(uuid.uuid4())
        first = self.enqueue(requestId=key)
        second = self.enqueue(requestId=key, campaignName='Changed browser state')
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.campaign_name, 'Launch')
        self.assertEqual(TaskRun.objects.count(), 1)

    def test_resuming_known_delivery_does_not_reapply_new_spend_quota(self):
        first = self.enqueue(requestId=str(uuid.uuid4()))
        with patch('apps.gemini.views.GeminiGenerationViewSet._quota_error', side_effect=AssertionError('resume must not request new spend')):
            second = self.enqueue(requestId=str(first.pk))
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(TaskRun.objects.count(), 1)

    def test_delivery_key_cannot_reuse_another_clients_record(self):
        other = self.make_workspace('Other', 'other')
        generation = GeminiGenerationRequest.objects.create(workspace=other)
        response = self.client.post('/api/marketing/ai-generation/generate-async/', {**self.payload, 'requestId': str(generation.pk)}, format='json', **self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(TaskRun.objects.exists())

    def test_partial_media_is_honest_and_image_retry_preserves_copy(self):
        generation = self.partial()
        item = ContentItem.objects.get()
        response = self.client.get(f'/api/marketing/ai-generation/{generation.pk}/', **self.headers)
        self.assertEqual(response.data['execution']['state'], 'PARTIAL')
        self.assertTrue(response.data['execution']['image_retry_allowed'])
        self.assertEqual(generation.result.metadata['media']['status'], 'FAILED')
        self.assertIsNone(generation.result.metadata['assetId'])
        path = f'/api/marketing/ai-generation/{generation.pk}/retry-image/'
        self.assertEqual(self.client.post(path, {}, format='json', **self.headers).status_code, 202)
        self.assertEqual(self.client.post(path, {}, format='json', **self.headers).status_code, 409)
        image = {'image_url': 'https://storage.test/saved.png', 'storage_path': 'workspace/saved.png', 'mime_type': 'image/png', 'provider': 'test'}
        with patch('apps.context.services.generation.retry_image', return_value=image) as repair, patch('apps.context.services.generation.generate_marketing_payload') as full, patch('apps.layouts.services.compose_generated_poster'):
            self.assertTrue(execute(claim()))
            generate_content.func(str(generation.pk))
        repair.assert_called_once()
        full.assert_not_called()
        item.refresh_from_db()
        generation.refresh_from_db()
        self.assertEqual(ContentItem.objects.count(), 1)
        self.assertEqual(item.caption, 'Keep these words')
        self.assertEqual(item.headline, 'Paid copy')
        self.assertIsNotNone(item.asset_id)
        self.assertEqual(generation.result.metadata['assetId'], str(item.asset_id))
        self.assertEqual(generation.result.metadata['media']['status'], 'READY')
        self.assertEqual(self.client.post(path, {}, format='json', **self.headers).status_code, 409)

    def test_failed_row_is_retry_pending_until_its_task_is_terminal(self):
        generation = self.enqueue()
        with patch('apps.context.services.generation.generate_marketing_payload', side_effect=RuntimeError('provider failed')):
            self.assertFalse(execute(claim()))
        url = f'/api/marketing/ai-generation/{generation.pk}/'
        state = self.client.get(url, **self.headers).data['execution']
        self.assertEqual(state['state'], 'RETRY_PENDING')
        self.assertFalse(state['terminal'])
        self.assertFalse(state['retry_allowed'])
        TaskRun.objects.update(status=TaskResultStatus.FAILED, attempts=3)
        state = self.client.get(url, **self.headers).data['execution']
        self.assertEqual(state['state'], 'FAILED')
        self.assertTrue(state['terminal'])
        self.assertTrue(state['retry_allowed'])

    def test_sync_partial_has_same_image_only_recovery_handle(self):
        with patch('apps.context.services.generation.generate_marketing_payload', return_value=self.routed), patch('apps.layouts.services.compose_generated_poster'):
            response = self.client.post('/api/marketing/ai-generation/generate/', self.payload, format='json', **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data['data']
        generation = GeminiGenerationRequest.objects.get(pk=data['generationId'])
        self.assertEqual(data['metadata']['media']['status'], 'FAILED')
        self.assertIsNone(data['assetId'])
        self.assertEqual(generation.result.metadata['contentItemId'], data['contentItemId'])
        self.assertEqual(self.client.post(f'/api/marketing/ai-generation/{generation.pk}/retry-image/', {}, format='json', **self.headers).status_code, 202)

    def test_image_retry_is_scoped_and_requires_editable_draft(self):
        generation = self.partial()
        path = f'/api/marketing/ai-generation/{generation.pk}/retry-image/'
        other = self.make_workspace('Another', 'another')
        _, outsider = self.authenticate_as(other, WorkspaceMember.Role.ADMIN, 'outsider')
        self.assertEqual(outsider.post(path, {}, format='json', HTTP_X_WORKSPACE_ID=str(other.pk)).status_code, 404)
        ContentItem.objects.update(status=ContentItem.Status.PENDING_REVIEW)
        self.assertEqual(self.client.post(path, {}, format='json', **self.headers).status_code, 409)
        self.assertEqual(TaskRun.objects.count(), 1)

    def test_image_retry_enqueue_failure_preserves_partial_and_allows_retry(self):
        generation = self.partial()
        path = f'/api/marketing/ai-generation/{generation.pk}/retry-image/'
        with patch('django.tasks.base.Task.enqueue', side_effect=RuntimeError('queue unavailable')):
            response = self.client.post(path, {}, format='json', **self.headers)
        self.assertEqual(response.status_code, 503)
        generation.refresh_from_db()
        self.assertEqual(generation.status, 'COMPLETED')
        self.assertEqual(ContentItem.objects.get().caption, 'Keep these words')
        self.assertEqual(self.client.post(path, {}, format='json', **self.headers).status_code, 202)

    def test_image_retry_failure_keeps_copy_and_never_allows_full_retry(self):
        generation = self.partial()
        path = f'/api/marketing/ai-generation/{generation.pk}/retry-image/'
        self.client.post(path, {}, format='json', **self.headers)
        with patch('apps.context.services.generation.retry_image', side_effect=RuntimeError('image failed')):
            self.assertFalse(execute(claim()))
        TaskRun.objects.update(status=TaskResultStatus.FAILED)
        state = self.client.get(f'/api/marketing/ai-generation/{generation.pk}/', **self.headers).data['execution']
        self.assertFalse(state['retry_allowed'])
        self.assertTrue(state['image_retry_allowed'])
        self.assertEqual(ContentItem.objects.get().caption, 'Keep these words')

    def test_image_retry_preserves_an_image_supplied_while_provider_was_busy(self):
        generation = self.partial()
        item = ContentItem.objects.get()
        supplied = MarketingAsset.objects.create(
            workspace=self.workspace, file_name='manual.png',
            file_url='https://storage.test/manual.png', source='MANUAL_UPLOAD',
        )
        self.client.post(f'/api/marketing/ai-generation/{generation.pk}/retry-image/', {}, format='json', **self.headers)

        def complete_image(*args, **kwargs):
            ContentItem.objects.filter(pk=item.pk).update(asset=supplied, preview_url=supplied.file_url)
            return {'image_url': 'https://storage.test/generated.png'}

        with patch('apps.context.services.generation.retry_image', side_effect=complete_image), patch('apps.layouts.services.compose_generated_poster') as compose:
            self.assertTrue(execute(claim()))
        compose.assert_not_called()
        item.refresh_from_db()
        generation.refresh_from_db()
        self.assertEqual(item.asset_id, supplied.pk)
        self.assertEqual(item.caption, 'Keep these words')
        self.assertEqual(generation.result.metadata['assetId'], str(supplied.pk))
        self.assertEqual(MarketingAsset.objects.count(), 1)

    def test_generation_list_batches_execution_state(self):
        self.enqueue()
        url = '/api/marketing/ai-generation/?page_size=25'
        self.client.get(url, **self.headers)
        with CaptureQueriesContext(connection) as small:
            self.client.get(url, **self.headers)
        for index in range(24):
            GeminiGenerationRequest.objects.create(workspace=self.workspace, user=self.user)
        with CaptureQueriesContext(connection) as large:
            response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(large), len(small))
        self.assertLessEqual(len(large), 5)
