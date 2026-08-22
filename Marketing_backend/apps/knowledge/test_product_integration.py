"""
The Brand Master knowledge flow end to end: typed uploads, pasted text
sources, and a confirmed fact that reaches the compiled Brand Brain and the
readiness counts without anyone pressing "rebuild".
"""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.brands.models import Brand
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

from .models import BrandMemory, BrandSource

User = get_user_model()


class KnowledgeProductIntegrationTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(customer_id='k1', workspace_name='K')
        self.user = User.objects.create_user(username='kuser', password='p')
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=self.user, role=WorkspaceMember.Role.EDITOR
        )
        self.brand = Brand.objects.create(workspace=self.workspace, name='Kbrand')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.id)}

    def _upload(self, **fields):
        data = {'brand': str(self.brand.id)}
        data.update(fields)
        return self.client.post(
            '/api/marketing/knowledge/sources/upload/', data, format='multipart', **self.headers
        )

    def test_upload_records_declared_source_type_and_title(self):
        response = self._upload(
            file=SimpleUploadedFile('call.txt', b'notes', content_type='text/plain'),
            source_type='CUSTOMER_CALL',
            title='Discovery call with Acme',
        )
        self.assertEqual(response.status_code, 200, response.content)
        source = BrandSource.objects.get(pk=response.json()['data']['id'])
        self.assertEqual(source.source_type, BrandSource.SourceType.CUSTOMER_CALL)
        self.assertEqual(source.title, 'Discovery call with Acme')
        # Honest state: stored, not processed. Nothing here claims READY.
        self.assertEqual(source.status, BrandSource.SourceStatus.UPLOADED)

    def test_upload_defaults_stay_backward_compatible(self):
        response = self._upload(
            file=SimpleUploadedFile('deck.pdf', b'%PDF', content_type='application/pdf'),
        )
        self.assertEqual(response.status_code, 200, response.content)
        source = BrandSource.objects.get(pk=response.json()['data']['id'])
        self.assertEqual(source.source_type, BrandSource.SourceType.DOCUMENT)
        self.assertEqual(source.title, 'deck.pdf')

    def test_unknown_source_type_rejected(self):
        response = self._upload(
            file=SimpleUploadedFile('x.txt', b'x', content_type='text/plain'),
            source_type='NOT_A_TYPE',
        )
        self.assertEqual(response.status_code, 400)

    def test_text_source_then_confirmed_fact_reaches_brain_and_readiness(self):
        # 1. A pasted transcript becomes a real source row.
        response = self.client.post(
            '/api/marketing/knowledge/sources/',
            {'brand': str(self.brand.id), 'source_type': 'TRANSCRIPT',
             'title': 'Founder call', 'raw_text': 'We roast every Tuesday.'},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 201, response.content)
        source_id = response.json()['id']

        # 2. A fact captured against it starts as a candidate...
        response = self.client.post(
            '/api/marketing/knowledge/memories/',
            {'brand': str(self.brand.id), 'source': source_id,
             'memory_type': 'PRODUCT_TRUTH', 'content': 'Beans are roasted every Tuesday.'},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 201, response.content)
        memory_id = response.json()['id']
        self.brand.refresh_from_db()
        self.assertNotIn(
            'Beans are roasted every Tuesday.',
            (self.brand.creative_brain or {}).get('verified_product_truth', []),
        )

        # 3. ...and confirming it recompiles the brain the generation path reads.
        response = self.client.post(
            '/api/marketing/knowledge/memories/%s/confirm/' % memory_id, **self.headers
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.brand.refresh_from_db()
        self.assertIn(
            'Beans are roasted every Tuesday.',
            self.brand.creative_brain['verified_product_truth'],
        )

        # 4. Readiness counts it, through the Brand Master overview.
        response = self.client.get(
            '/api/marketing/brand-master/%s/' % self.brand.id, **self.headers
        )
        self.assertEqual(response.status_code, 200, response.content)
        counts = response.json()['data']['readiness']['counts']
        self.assertEqual(counts['sources'], 1)
        self.assertEqual(counts['memories'], 1)

        # 5. Archiving the source withdraws the fact from the brain (PR1-010).
        response = self.client.post(
            '/api/marketing/knowledge/sources/%s/revoke/' % source_id, **self.headers
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.brand.refresh_from_db()
        self.assertNotIn(
            'Beans are roasted every Tuesday.',
            self.brand.creative_brain['verified_product_truth'],
        )

    def test_viewer_cannot_confirm_a_fact(self):
        viewer = User.objects.create_user(username='kviewer', password='p')
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=viewer, role=WorkspaceMember.Role.VIEWER
        )
        memory = BrandMemory.objects.create(
            workspace=self.workspace, brand=self.brand,
            memory_type=BrandMemory.MemoryType.FACT, content='x',
        )
        client = APIClient()
        client.force_authenticate(user=viewer)
        response = client.post(
            '/api/marketing/knowledge/memories/%s/confirm/' % memory.id, **self.headers
        )
        self.assertEqual(response.status_code, 403)
