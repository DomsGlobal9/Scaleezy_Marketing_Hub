"""Real carousel/video production through frozen Context Gateway and AIRouter."""
import base64
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status

from apps.ai.models import Capability
from apps.ai.router import NoProviderAvailable
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.content.models import ContentItem
from apps.gemini.models import GeminiGenerationRequest
from apps.marketing.models import MarketingAsset
from apps.workspaces.models import WorkspaceMember


ASYNC_URL = '/api/marketing/gemini/generate-async/'


class ProductionClosureTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Production client', 'production-client')
        self.user, self.client = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'production-admin'
        )
        Brand.objects.create(
            workspace=self.workspace, name='Production Brand', is_default=True
        )

    def queue(self, payload):
        payload = {'creativeMode': 'AI_ORIGINAL', **payload}
        queued = SimpleNamespace(enqueue=lambda _request_id: SimpleNamespace(id='task-1'))
        with patch('apps.gemini.tasks.generate_content', new=queued):
            response = self.client.post(
                ASYNC_URL, payload, format='json', **workspace_header(self.workspace)
            )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.content)
        return GeminiGenerationRequest.objects.get(
            pk=response.json()['data']['generationId']
        )

    @staticmethod
    def text_result():
        return {
            'headline': 'One system',
            'caption': 'A complete social operating loop.',
            'hashtags': '#scaleezy',
            'provider': 'copy-ai',
            'provider_name': 'Copy AI',
        }

    def test_video_settings_route_to_video_and_persist_a_durable_video_asset(self):
        request = self.queue({
            'campaignName': 'Video launch',
            'contentType': 'video',
            'videoDuration': '15 seconds',
            'videoAspect': '9:16 (Reels / Shorts)',
            'videoStyle': 'Product showcase',
            'videoScript': 'Open on the product, then reveal the benefit.',
        })
        stored = json.loads(request.prompt_data)
        self.assertEqual(stored['video_duration'], '15 seconds')
        self.assertEqual(stored['video_aspect'], '9:16 (Reels / Shorts)')
        self.assertEqual(stored['video_style'], 'Product showcase')

        calls = []

        def dispatch(_router, capability, brief, content_item_id=None):
            calls.append((capability, brief))
            if capability == Capability.TEXT:
                return self.text_result()
            if capability == Capability.VIDEO:
                return {
                    'video_base64': base64.b64encode(b'video-bytes').decode(),
                    'mime_type': 'video/mp4',
                    'duration': 15,
                    'provider': 'video-ai',
                    'provider_name': 'Video AI',
                }
            raise AssertionError(capability)

        from apps.gemini.tasks import generate_content

        with patch('apps.ai.router.AIRouter.dispatch', new=dispatch):
            generate_content.call(str(request.pk))

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.COMPLETED)
        self.assertEqual([capability for capability, _brief in calls], [
            Capability.TEXT, Capability.VIDEO,
        ])
        video_brief = next(brief for capability, brief in calls if capability == Capability.VIDEO)
        self.assertEqual(video_brief['video_duration'], '15 seconds')
        self.assertIn('Open on the product', video_brief['instruction'])

        item = ContentItem.objects.get(pk=request.result.metadata['contentItemId'])
        self.assertEqual(item.content_format, ContentItem.Format.VIDEO)
        self.assertEqual(item.asset.asset_type, MarketingAsset.AssetType.VIDEO)
        self.assertEqual(item.asset.mime_type, 'video/mp4')
        self.assertEqual(item.preview_url, item.asset.file_url)
        self.assertEqual(request.result.metadata['videoUrl'], item.asset.file_url)

    def test_carousel_generates_and_persists_every_ordered_slide(self):
        request = self.queue({
            'campaignName': 'Carousel launch',
            'contentType': 'carousel',
            'slides': [
                {'position': 1, 'description': 'Hook'},
                {'position': 2, 'description': 'Product'},
                {'position': 3, 'description': 'Proof'},
            ],
        })
        calls = []

        def dispatch(_router, capability, brief, content_item_id=None):
            if capability == Capability.TEXT:
                return self.text_result()
            position = brief['slide']['position']
            calls.append(position)
            return {
                'image_base64': base64.b64encode(f'slide-{position}'.encode()).decode(),
                'mime_type': 'image/png',
                'provider': 'image-ai',
                'provider_name': 'Image AI',
            }

        from apps.gemini.tasks import generate_content

        with patch('apps.ai.router.AIRouter.primary_adapter', return_value=object()), patch(
            'apps.ai.router.AIRouter.dispatch', new=dispatch
        ):
            generate_content.call(str(request.pk))

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.COMPLETED)
        self.assertEqual(sorted(calls), [1, 2, 3])
        item = ContentItem.objects.get(pk=request.result.metadata['contentItemId'])
        self.assertEqual(item.content_format, ContentItem.Format.CAROUSEL)
        self.assertEqual([row['position'] for row in item.slides], [1, 2, 3])
        self.assertTrue(all(row['preview_url'].startswith('https://storage.test/') for row in item.slides))
        self.assertEqual(
            request.result.metadata['slideImageUrls'],
            [row['preview_url'] for row in item.slides],
        )
        self.assertEqual(item.preview_url, item.slides[0]['preview_url'])

    def test_failed_carousel_retry_reuses_completed_copy_and_slides(self):
        request = self.queue({
            'campaignName': 'Resume carousel',
            'contentType': 'carousel',
            'slides': [
                {'position': 1, 'description': 'Hook'},
                {'position': 2, 'description': 'Product'},
                {'position': 3, 'description': 'Proof'},
            ],
        })
        first_calls = []

        def flaky(_router, capability, brief, content_item_id=None):
            if capability == Capability.TEXT:
                first_calls.append('text')
                return self.text_result()
            position = brief['slide']['position']
            first_calls.append(position)
            if position == 2:
                raise NoProviderAvailable('image provider unavailable')
            return {
                'image_base64': base64.b64encode(f'slide-{position}'.encode()).decode(),
                'mime_type': 'image/png',
                'provider': 'image-ai',
            }

        from apps.context.services.generation import OutputRejected
        from apps.gemini.tasks import generate_content

        with patch('apps.ai.router.AIRouter.primary_adapter', return_value=object()), patch(
            'apps.ai.router.AIRouter.dispatch', new=flaky
        ), self.assertRaises(OutputRejected):
            generate_content.call(str(request.pk))

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.FAILED)
        checkpoint = json.loads(request.prompt_data)['production_state']
        self.assertIn('text', checkpoint)
        self.assertEqual(set(checkpoint['slides']), {'1', '3'})
        detail = self.client.get(
            f'/api/marketing/gemini/{request.pk}/',
            **workspace_header(self.workspace),
        )
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.json()['progress']['completed_slides'], 2)
        self.assertEqual(detail.json()['progress']['total_slides'], 3)
        self.assertNotIn('prompt_data', detail.json())

        retry_calls = []

        def recovered(_router, capability, brief, content_item_id=None):
            retry_calls.append(capability if capability == Capability.TEXT else brief['slide']['position'])
            if capability == Capability.TEXT:
                return self.text_result()
            return {
                'image_base64': base64.b64encode(b'slide-2').decode(),
                'mime_type': 'image/png',
                'provider': 'image-ai',
            }

        with patch('apps.ai.router.AIRouter.primary_adapter', return_value=object()), patch(
            'apps.ai.router.AIRouter.dispatch', new=recovered
        ):
            generate_content.call(str(request.pk))

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.COMPLETED)
        self.assertEqual(retry_calls, [2])
        self.assertEqual(request.error_message, '')

    def test_editor_can_retry_one_draft_slide_without_touching_the_rest(self):
        asset = MarketingAsset.objects.create(
            workspace=self.workspace,
            asset_type=MarketingAsset.AssetType.IMAGE,
            file_name='slide-1.png',
            file_url='https://storage.test/slide-1.png',
            source=MarketingAsset.Source.AI_GENERATED,
            created_by=self.user,
        )
        item = ContentItem.objects.create(
            workspace=self.workspace,
            brand=self.workspace.brands.get(is_default=True),
            asset=asset,
            content_format=ContentItem.Format.CAROUSEL,
            status=ContentItem.Status.DRAFT,
            headline='Carousel',
            preview_url=asset.file_url,
            slides=[
                {'position': 1, 'description': 'Hook', 'preview_url': asset.file_url},
                {
                    'position': 2,
                    'description': 'Product',
                    'preview_url': 'https://storage.test/slide-2-old.png',
                },
            ],
            created_by=self.user,
        )
        replacement = {
            'image_url': 'https://storage.test/slide-2-new.png',
            'storage_path': 'generated/slide-2-new.png',
            'mime_type': 'image/png',
            'provider': 'image-ai',
        }
        with patch(
            'apps.context.services.generation.retry_image', return_value=replacement
        ) as retry:
            response = self.client.post(
                f'/api/marketing/content/{item.pk}/regenerate-slide/',
                {'position': 2},
                format='json',
                **workspace_header(self.workspace),
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        item.refresh_from_db()
        self.assertEqual(item.asset_id, asset.pk)
        self.assertEqual(item.slides[0]['preview_url'], asset.file_url)
        self.assertEqual(item.slides[1]['preview_url'], replacement['image_url'])
        self.assertEqual(item.layout_config['carousel_retries'][0]['position'], 2)
        self.assertEqual(retry.call_count, 1)

    def test_missing_video_route_fails_without_a_fake_result(self):
        request = self.queue({
            'campaignName': 'Unavailable video',
            'contentType': 'video',
        })

        def unavailable(_router, capability, brief, content_item_id=None):
            if capability == Capability.TEXT:
                return self.text_result()
            raise NoProviderAvailable('No VIDEO provider configured')

        from apps.context.services.generation import NoProviderConfigured
        from apps.gemini.tasks import generate_content

        with patch('apps.ai.router.AIRouter.dispatch', new=unavailable), self.assertRaises(
            NoProviderConfigured
        ):
            generate_content.call(str(request.pk))

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.FAILED)
        self.assertFalse(hasattr(request, 'result'))
        self.assertIn('No VIDEO provider', request.error_message)

    def test_private_provider_media_url_is_rejected_before_download(self):
        from apps.context.services.generation import OutputRejected, _public_media_url

        with self.assertRaises(OutputRejected):
            _public_media_url('https://127.0.0.1/generated/video.mp4?token=secret')

    def test_worker_persistence_failure_never_claims_completed(self):
        request = self.queue({
            'campaignName': 'Persistence failure',
            'contentType': 'video',
        })

        routed = {
            'provider': 'video-ai',
            'provider_name': 'Video AI',
            'brain_version': 'brain-v1',
            'trace': {},
            'payload': {
                'postTitle': 'Generated but not saved',
                'postDescription': 'This must not be marked complete.',
                'postHashtags': '#honest',
                'videoUrl': 'https://storage.test/video.mp4',
                'posterImageUrl': '',
                'slideImageUrls': [],
                'metadata': {},
            },
        }

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=routed,
        ), patch(
            'apps.gemini.tasks._persist',
            side_effect=RuntimeError('storage unavailable'),
        ), self.assertRaises(RuntimeError):
            generate_content.call(str(request.pk))

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.FAILED)
        self.assertIn('storage unavailable', request.error_message)
        self.assertFalse(hasattr(request, 'result'))
