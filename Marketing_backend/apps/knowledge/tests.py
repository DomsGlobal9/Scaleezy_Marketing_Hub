import uuid
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
        
        # Workspace 1 setup
        self.workspace1 = MarketingWorkspace.objects.create(customer_id='c1', workspace_name='Workspace 1')
        self.user1 = User.objects.create_user(username='user1', password='p')
        WorkspaceMember.objects.create(workspace=self.workspace1, user=self.user1, role=WorkspaceMember.Role.ADMIN)
        self.brand1 = Brand.objects.create(workspace=self.workspace1, name='Brand 1')
        self.client1.force_authenticate(user=self.user1)
        
        # Workspace 2 setup
        self.workspace2 = MarketingWorkspace.objects.create(customer_id='c2', workspace_name='Workspace 2')
        self.user2 = User.objects.create_user(username='user2', password='p')
        WorkspaceMember.objects.create(workspace=self.workspace2, user=self.user2, role=WorkspaceMember.Role.ADMIN)
        self.brand2 = Brand.objects.create(workspace=self.workspace2, name='Brand 2')
        self.client2.force_authenticate(user=self.user2)

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
        source = BrandSource.objects.create(
            workspace=self.workspace1,
            brand=self.brand1,
            title='Test Source',
            created_by=self.user1
        )
        url = f'/api/marketing/knowledge/sources/{source.id}/process/'
        response = self.client1.post(url, HTTP_X_WORKSPACE_ID=str(self.workspace1.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        source.refresh_from_db()
        self.assertEqual(source.status, BrandSource.SourceStatus.QUEUED)

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
