import uuid
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from django.contrib.auth import get_user_model
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember
from apps.brands.models import Brand
from .models import BrandSource, BrandMemory

User = get_user_model()

class KnowledgeAPITests(TestCase):
    def setUp(self):
        self.client1 = APIClient()
        self.client2 = APIClient()
        self.viewer_client = APIClient()
        
        # Workspace 1 setup
        self.workspace1 = MarketingWorkspace.objects.create(customer_id='c1', workspace_name='Workspace 1')
        self.user1 = User.objects.create_user(username='user1', password='p')
        WorkspaceMember.objects.create(workspace=self.workspace1, user=self.user1, role=WorkspaceMember.Role.ADMIN)
        self.brand1 = Brand.objects.create(workspace=self.workspace1, name='Brand 1')
        self.client1.force_authenticate(user=self.user1)
        
        # Viewer in Workspace 1 setup
        self.user_viewer = User.objects.create_user(username='viewer', password='p')
        WorkspaceMember.objects.create(workspace=self.workspace1, user=self.user_viewer, role=WorkspaceMember.Role.VIEWER)
        self.viewer_client.force_authenticate(user=self.user_viewer)

        # Workspace 2 setup
        self.workspace2 = MarketingWorkspace.objects.create(customer_id='c2', workspace_name='Workspace 2')
        self.user2 = User.objects.create_user(username='user2', password='p')
        WorkspaceMember.objects.create(workspace=self.workspace2, user=self.user2, role=WorkspaceMember.Role.ADMIN)
        self.brand2 = Brand.objects.create(workspace=self.workspace2, name='Brand 2')
        self.client2.force_authenticate(user=self.user2)

        self.source1 = BrandSource.objects.create(
            workspace=self.workspace1,
            brand=self.brand1,
            title='Test Source 1',
            created_by=self.user1
        )

    def test_create_source_tenant_isolation(self):
        # User 1 creates source in Workspace 1
        url = '/api/marketing/knowledge/sources/'
        data = {
            'brand': str(self.brand1.id),
            'title': 'Test Source',
            'source_type': BrandSource.SourceType.WEBSITE,
            'source_url': 'https://example.com'
        }
        response = self.client1.post(url, data, format='json', HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        source_id = response.json()['id']
        
        # User 2 cannot access User 1's source
        detail_url = f"{url}{source_id}/"
        response2 = self.client2.get(detail_url, HTTP_X_WORKSPACE_ID=str(self.workspace2.id))
        self.assertEqual(response2.status_code, status.HTTP_404_NOT_FOUND)

    def test_process_source_action(self):
        url = f'/api/marketing/knowledge/sources/{self.source1.id}/process/'
        response = self.client1.post(url, HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.source1.refresh_from_db()
        self.assertEqual(self.source1.status, BrandSource.SourceStatus.QUEUED)

    @patch('apps.knowledge.tasks.process_source_task')
    def test_process_source_enqueue_failure_is_recorded_honestly(self, task):
        task.enqueue.side_effect = RuntimeError('queue unavailable')
        url = f'/api/marketing/knowledge/sources/{self.source1.id}/process/'

        response = self.client1.post(url, HTTP_X_WORKSPACE_ID=str(self.workspace1.id))

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(response.json()['success'])
        self.assertEqual(response.json()['error']['code'], 'QUEUE_ENQUEUE_FAILED')
        self.source1.refresh_from_db()
        self.assertEqual(self.source1.status, BrandSource.SourceStatus.FAILED)
        processing = self.source1.metadata['processing']
        self.assertTrue(processing['failed_at'])
        self.assertEqual(
            processing['error'],
            'Source processing could not enter the task queue. Try again.',
        )
        task.enqueue.assert_called_once_with(str(self.source1.pk))

    @patch('apps.knowledge.processing.AIRouter.dispatch')
    def test_processing_creates_grounded_review_candidates(self, dispatch):
        dispatch.return_value = {
            'provider': 'test-provider',
            'raw': {
                'memories': [{
                    'memory_type': 'FACT',
                    'content': 'Scaleezy serves marketing teams.',
                    'normalized_key': 'target_customer',
                    'confidence': 0.9,
                    'quote': 'serves marketing teams',
                }],
            },
        }
        self.source1.raw_text = 'Scaleezy serves marketing teams with an AI workspace.'
        self.source1.save(update_fields=['raw_text'])

        from .processing import process_source
        result = process_source(str(self.source1.pk))

        self.source1.refresh_from_db()
        memory = BrandMemory.objects.get(source=self.source1)
        self.assertEqual(result['candidates'], 1)
        self.assertEqual(self.source1.status, BrandSource.SourceStatus.NEEDS_REVIEW)
        self.assertEqual(memory.status, BrandMemory.MemoryStatus.CANDIDATE)
        self.assertEqual(memory.extracted_by_provider, 'test-provider')

    def test_memory_tenant_isolation(self):
        source = BrandSource.objects.create(
            workspace=self.workspace1,
            brand=self.brand1,
            title='Test Source',
            created_by=self.user1
        )
        memory = BrandMemory.objects.create(
            workspace=self.workspace1,
            brand=self.brand1,
            source=source,
            memory_type=BrandMemory.MemoryType.FACT,
            content="This is a test memory."
        )
        
        url = f'/api/marketing/knowledge/memories/{memory.id}/'
        # User 1 can see it
        response1 = self.client1.get(url, HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        
        # User 2 cannot see it
        response2 = self.client2.get(url, HTTP_X_WORKSPACE_ID=str(self.workspace2.id))
        self.assertEqual(response2.status_code, status.HTTP_404_NOT_FOUND)

    def test_memory_confirm_action(self):
        memory = BrandMemory.objects.create(
            workspace=self.workspace1,
            brand=self.brand1,
            memory_type=BrandMemory.MemoryType.FACT,
            content="Test memory",
            status=BrandMemory.MemoryStatus.CANDIDATE
        )
        url = f'/api/marketing/knowledge/memories/{memory.id}/confirm/'
        response = self.client1.post(url, HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        memory.refresh_from_db()
        self.assertEqual(memory.status, BrandMemory.MemoryStatus.CONFIRMED)

    # Negative Tests
    def test_cross_tenant_brand_injection_blocked(self):
        # User 1 tries to create source for User 2's brand
        url = '/api/marketing/knowledge/sources/'
        data = {
            'brand': str(self.brand2.id), # Cross-tenant brand ID
            'title': 'Test Source',
            'source_type': BrandSource.SourceType.WEBSITE,
            'source_url': 'https://example.com'
        }
        response = self.client1.post(url, data, format='json', HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("brand", response.json())

    def test_cross_brand_source_injection_blocked(self):
        # Create brand3 in workspace1
        brand3 = Brand.objects.create(workspace=self.workspace1, name='Brand 3')
        # Create a source for brand1
        source_brand1 = BrandSource.objects.create(
            workspace=self.workspace1,
            brand=self.brand1,
            title='Brand 1 Source',
            created_by=self.user1
        )
        # Try to create a memory on brand3 but using brand1's source
        url = '/api/marketing/knowledge/memories/'
        data = {
            'brand': str(brand3.id),
            'source': str(source_brand1.id),
            'memory_type': BrandMemory.MemoryType.FACT,
            'content': 'Cross brand memory'
        }
        response = self.client1.post(url, data, format='json', HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("source", response.json())

    def test_viewer_cannot_create_source(self):
        url = '/api/marketing/knowledge/sources/'
        data = {
            'brand': str(self.brand1.id),
            'title': 'Viewer Source',
            'source_type': BrandSource.SourceType.WEBSITE,
        }
        response = self.viewer_client.post(url, data, format='json', HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_status_field_is_read_only(self):
        # Try to create a memory directly as CONFIRMED
        url = '/api/marketing/knowledge/memories/'
        data = {
            'brand': str(self.brand1.id),
            'memory_type': BrandMemory.MemoryType.FACT,
            'content': 'Status bypass',
            'status': BrandMemory.MemoryStatus.CONFIRMED # Attempt to bypass CANDIDATE
        }
        response = self.client1.post(url, data, format='json', HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        memory = BrandMemory.objects.get(id=response.json()['id'])
        # It should fall back to the model's default, which is CANDIDATE
        self.assertEqual(memory.status, BrandMemory.MemoryStatus.CANDIDATE)

    def test_cross_tenant_upload_brand_injection(self):
        # Client 1 tries to upload a file but assigns it to Brand 2 (which belongs to workspace 2)
        from django.core.files.uploadedfile import SimpleUploadedFile
        url = '/api/marketing/knowledge/sources/upload/'
        file_obj = SimpleUploadedFile("test_file.txt", b"dummy content", content_type="text/plain")
        data = {
            'brand': str(self.brand2.id),
            'file': file_obj
        }
        response = self.client1.post(url, data, format='multipart', HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid pk", response.json()['error']['brand'][0])

    def test_patch_relationship_injection_brand(self):
        # Create a memory in workspace 1
        memory = BrandMemory.objects.create(
            workspace=self.workspace1,
            brand=self.brand1,
            memory_type=BrandMemory.MemoryType.FACT,
            content="Original content"
        )
        url = f'/api/marketing/knowledge/memories/{memory.id}/'
        # Try to change its brand to brand 2
        data = {'brand': str(self.brand2.id)}
        response = self.client1.patch(url, data, format='json', HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_relationship_injection_supersedes(self):
        # Create two memories in workspace 1
        memory1 = BrandMemory.objects.create(
            workspace=self.workspace1,
            brand=self.brand1,
            memory_type=BrandMemory.MemoryType.FACT,
            content="Mem 1"
        )
        # Create a memory in workspace 2
        memory2 = BrandMemory.objects.create(
            workspace=self.workspace2,
            brand=self.brand2,
            memory_type=BrandMemory.MemoryType.FACT,
            content="Mem 2"
        )
        
        url = f'/api/marketing/knowledge/memories/{memory1.id}/'
        # Try to supersede memory2 from workspace 1
        data = {'supersedes': str(memory2.id)}
        response = self.client1.patch(url, data, format='json', HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_process_archived_source(self):
        url = f'/api/marketing/knowledge/sources/{self.source1.id}/process/'
        
        # Archive it first
        revoke_url = f'/api/marketing/knowledge/sources/{self.source1.id}/revoke/'
        self.client1.post(revoke_url, HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        
        # Now try to process it
        response = self.client1.post(url, HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Archived sources cannot be processed", response.json()['message'])
