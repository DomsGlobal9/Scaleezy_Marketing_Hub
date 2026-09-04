from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from apps.context.services.generation import create_generated_asset
from apps.marketing.models import MarketingAsset
from apps.marketing.services.storage import StorageError
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember


class MarketingAssetBoundaryTests(APITestCase):
    untrusted_urls = (
        'http://127.0.0.1/admin',
        'http://[::1]/admin',
        'http://169.254.169.254/latest/meta-data/',
        'http://10.0.0.1/private',
        'https://attacker.example/arbitrary.jpg',
    )

    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='asset-boundary', workspace_name='Asset boundary',
        )
        self.other_workspace = MarketingWorkspace.objects.create(
            customer_id='other-asset-boundary', workspace_name='Other workspace',
        )
        self.user = get_user_model().objects.create_user(username='asset-owner')
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=self.user, role=WorkspaceMember.Role.OWNER,
        )
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str(self.workspace.id))
        self.asset = MarketingAsset.objects.create(
            workspace=self.workspace,
            file_name='existing.jpg',
            file_url='https://storage.test/existing.jpg',
            storage_path='assets/existing.jpg',
            source=MarketingAsset.Source.MANUAL_UPLOAD,
            created_by=self.user,
        )

    def file(self):
        return SimpleUploadedFile('uploaded.jpg', b'uploaded-image', content_type='image/jpeg')

    def test_generic_create_rejects_url_payloads_in_json_and_multipart(self):
        for request_format in ('json', 'multipart'):
            for url in self.untrusted_urls:
                with self.subTest(format=request_format, url=url):
                    response = self.client.post('/api/marketing/assets/', {
                        'file_name': 'forged.jpg',
                        'file_url': url,
                        'storage_path': 'other-workspace/forged.jpg',
                        'asset_type': 'IMAGE',
                        'source': 'MANUAL_UPLOAD',
                    }, format=request_format)
                    self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
                    self.assertEqual(MarketingAsset.objects.count(), 1)

    def test_generic_put_and_patch_cannot_replace_asset_storage_metadata(self):
        original = MarketingAsset.objects.values().get(pk=self.asset.pk)
        for method in ('put', 'patch'):
            for request_format in ('json', 'multipart'):
                for url in self.untrusted_urls:
                    with self.subTest(method=method, format=request_format, url=url):
                        response = getattr(self.client, method)(
                            f'/api/marketing/assets/{self.asset.pk}/', {
                                'file_name': 'forged.jpg',
                                'file_url': url,
                                'storage_path': 'other-workspace/forged.jpg',
                                'mime_type': 'video/mp4',
                                'file_size': 99999,
                                'asset_type': 'VIDEO',
                                'source': 'AI_GENERATED',
                            }, format=request_format,
                        )
                        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
                        self.assertEqual(
                            MarketingAsset.objects.values().get(pk=self.asset.pk), original,
                        )

    @patch('apps.marketing.views.SupabaseStorageService.upload_and_describe')
    def test_upload_uses_file_and_storage_result_not_supplied_url_or_metadata(self, upload):
        trusted_url = 'https://storage.test/owned/uploaded.jpg'
        upload.return_value = {'url': trusted_url, 'path': 'owned/uploaded.jpg'}
        for url in self.untrusted_urls:
            with self.subTest(url=url):
                response = self.client.post('/api/marketing/assets/upload/', {
                    'workspace_id': str(self.workspace.id),
                    'file': self.file(),
                    'file_url': url,
                    'storage_path': 'other-workspace/forged.mp4',
                    'mime_type': 'video/mp4',
                    'file_size': 99999,
                    'file_name': 'forged.mp4',
                    'asset_type': 'VIDEO',
                    'generation_id': 'forged-generation',
                }, format='multipart')
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                asset = MarketingAsset.objects.get(pk=response.data['data']['id'])
                self.assertEqual(asset.workspace, self.workspace)
                self.assertEqual(asset.created_by, self.user)
                self.assertEqual(asset.file_url, trusted_url)
                self.assertEqual(asset.storage_path, 'owned/uploaded.jpg')
                self.assertEqual(asset.file_name, 'uploaded.jpg')
                self.assertEqual(asset.mime_type, 'image/jpeg')
                self.assertEqual(asset.file_size, len(b'uploaded-image'))
                self.assertEqual(asset.asset_type, MarketingAsset.AssetType.IMAGE)
                self.assertEqual(asset.source, MarketingAsset.Source.MANUAL_UPLOAD)
                self.assertIsNone(asset.generation_id)
                self.assertEqual(upload.call_args.args[0], str(self.workspace.id))
                self.assertEqual(upload.call_args.kwargs['prefix'], 'assets')

    @patch('apps.marketing.views.SupabaseStorageService.upload_and_describe')
    def test_upload_cannot_substitute_a_url_for_a_file(self, upload):
        response = self.client.post('/api/marketing/assets/upload/', {
            'workspace_id': str(self.workspace.id),
            'file_url': self.untrusted_urls[0],
        }, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(MarketingAsset.objects.count(), 1)
        upload.assert_not_called()

    @patch('apps.marketing.views.SupabaseStorageService.upload_and_describe')
    def test_upload_remains_authenticated_and_workspace_scoped(self, upload):
        response = self.client.post('/api/marketing/assets/upload/', {
            'workspace_id': str(self.other_workspace.id), 'file': self.file(),
        }, format='multipart')
        self.assertIn(response.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN))
        self.client.credentials(HTTP_X_WORKSPACE_ID=str(self.other_workspace.id))
        response = self.client.post('/api/marketing/assets/upload/', {
            'workspace_id': str(self.other_workspace.id), 'file': self.file(),
        }, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(user=None)
        response = self.client.post('/api/marketing/assets/upload/', {
            'workspace_id': str(self.workspace.id), 'file': self.file(),
        }, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(MarketingAsset.objects.count(), 1)
        upload.assert_not_called()

    @patch('apps.marketing.views.SupabaseStorageService.upload_and_describe')
    def test_failed_storage_does_not_create_an_asset(self, upload):
        upload.side_effect = StorageError('Storage unavailable.')
        response = self.client.post('/api/marketing/assets/upload/', {
            'workspace_id': str(self.workspace.id), 'file': self.file(),
        }, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(response.data['success'])
        self.assertEqual(MarketingAsset.objects.count(), 1)

    def test_internal_generation_assets_remain_readable_and_tenant_scoped(self):
        asset = create_generated_asset(self.workspace, {
            'metadata': {'generated_image': {
                'image_url': 'https://storage.test/generated.jpg',
                'storage_path': 'generated/image.jpg',
                'file_name': 'generated.jpg',
            }},
        }, user=self.user)
        self.assertEqual(asset.source, MarketingAsset.Source.AI_GENERATED)
        response = self.client.get(f'/api/marketing/assets/{asset.pk}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['file_url'], asset.file_url)
        other_asset = MarketingAsset.objects.create(
            workspace=self.other_workspace,
            file_name='other.jpg', source=MarketingAsset.Source.COMPOSED,
        )
        response = self.client.get('/api/marketing/assets/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({row['id'] for row in response.data}, {str(self.asset.pk), str(asset.pk)})
        response = self.client.get(f'/api/marketing/assets/{other_asset.pk}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_existing_scoped_delete_is_preserved(self):
        response = self.client.delete(f'/api/marketing/assets/{self.asset.pk}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(MarketingAsset.objects.filter(pk=self.asset.pk).exists())
