"""Untrusted API edits cannot rewrite the source of a confirmed assertion."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.inspirations.models import BrandInspiration, InspirationSignal
from apps.learning.models import LearningEvent, BrandPreference, PreferenceEvidence
from apps.learning.serializers import BrandPreferenceSerializer
from apps.learning.views import BrandPreferenceViewSet
from apps.workspaces.models import WorkspaceMember
from .models import BrandMemory, BrandSource


class EvidenceBoundaryTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Evidence', 'evidence-boundaries')
        self.user, self.client = self.authenticate_as(self.workspace, WorkspaceMember.Role.ADMIN, 'evidence-admin')
        self.headers = workspace_header(self.workspace)
        self.brand = Brand.objects.create(workspace=self.workspace, name='Evidence brand')
        self.source = BrandSource.objects.create(workspace=self.workspace, brand=self.brand, title='Original', raw_text='Original evidence')
        self.memory = BrandMemory.objects.create(workspace=self.workspace, brand=self.brand, source=self.source, memory_type='FACT', content='Original fact')
        self.memory_url = f'/api/marketing/knowledge/memories/{self.memory.pk}/'

    def test_source_reference_and_storage_cannot_be_rewritten(self):
        url = f'/api/marketing/knowledge/sources/{self.source.pk}/'
        for data in ({'raw_text': 'Replacement'}, {'source_url': 'https://different.example'}, {'source_type': 'WEBSITE'}):
            with self.subTest(data=data):
                self.assertEqual(self.client.patch(url, data, format='json', **self.headers).status_code, 400)
        self.assertEqual(self.client.patch(url, {'file_url': 'http://127.0.0.1/private', 'content_hash': 'forged', 'metadata': {'processing': {'complete': True}}}, format='json', **self.headers).status_code, 200)
        self.source.refresh_from_db()
        self.assertEqual(self.source.raw_text, 'Original evidence')
        self.assertIsNone(self.source.file_url)
        self.assertIsNone(self.source.content_hash)
        self.assertEqual(self.source.metadata, {})

    def test_memory_provenance_cannot_be_removed(self):
        response = self.client.patch(self.memory_url, {'source': None}, format='json', **self.headers)
        self.assertEqual(response.status_code, 400)
        self.memory.refresh_from_db()
        self.assertEqual(self.memory.source_id, self.source.pk)

    def test_api_cannot_forge_machine_confidence(self):
        response = self.client.patch(self.memory_url, {'confidence': 1, 'extracted_by_provider': 'trusted', 'normalized_key': 'forged'}, format='json', **self.headers)
        self.assertEqual(response.status_code, 200)
        self.memory.refresh_from_db()
        self.assertEqual(self.memory.confidence, 0)
        self.assertIsNone(self.memory.extracted_by_provider)
        self.assertIsNone(self.memory.normalized_key)

    def test_retired_or_out_of_date_memory_cannot_be_confirmed(self):
        for data in (
            {'status': 'SUPERSEDED'}, {'status': 'EXPIRED'},
            {'status': 'CANDIDATE', 'valid_until': timezone.now() - timedelta(days=1)},
            {'valid_until': None, 'valid_from': timezone.now() + timedelta(days=1)},
        ):
            with self.subTest(data=data):
                BrandMemory.objects.filter(pk=self.memory.pk).update(**data)
                self.assertEqual(self.client.post(self.memory_url + 'confirm/', **self.headers).status_code, 400)
        self.assertFalse(LearningEvent.objects.filter(subject_id=self.memory.pk).exists())

    def test_archived_source_cannot_gain_new_confirmation(self):
        self.source.status = 'ARCHIVED'
        self.source.save()
        self.assertEqual(self.client.post(self.memory_url + 'confirm/', **self.headers).status_code, 400)
        self.assertEqual(self.client.patch(self.memory_url, {'content': 'Changed'}, format='json', **self.headers).status_code, 400)

    def test_changed_fact_needs_a_new_verdict_and_preserves_previous_event(self):
        self.assertEqual(self.client.post(self.memory_url + 'confirm/', **self.headers).status_code, 200)
        self.assertEqual(self.client.patch(self.memory_url, {'content': 'Corrected fact'}, format='json', **self.headers).status_code, 200)
        self.memory.refresh_from_db()
        self.assertEqual(self.memory.status, 'CANDIDATE')
        self.assertIsNone(self.memory.reviewed_by_id)
        self.assertEqual(self.client.post(self.memory_url + 'confirm/', **self.headers).status_code, 200)
        events = LearningEvent.objects.filter(subject_id=self.memory.pk, event_type='MEMORY_CONFIRMED')
        self.assertEqual(events.count(), 2)
        self.assertEqual({event.context['content'] for event in events}, {'Original fact', 'Corrected fact'})
        self.client.post(self.memory_url + 'confirm/', **self.headers)
        self.assertEqual(events.count(), 2)

    def test_scope_change_withdraws_confirmation(self):
        self.client.post(self.memory_url + 'confirm/', **self.headers)
        self.assertEqual(self.client.patch(self.memory_url, {'scope': 'CAMPAIGN'}, format='json', **self.headers).status_code, 200)
        self.memory.refresh_from_db()
        self.assertEqual(self.memory.status, 'CANDIDATE')

    def test_inspiration_identity_and_analysis_lineage_are_protected(self):
        inspiration = BrandInspiration.objects.create(workspace=self.workspace, brand=self.brand, title='Reference', reference_url='https://example.com/original', metadata={'analysis': {'provider': 'original'}, 'platform_inspiration_id': 'library-id'})
        url = f'/api/marketing/inspirations/{inspiration.pk}/'
        self.assertEqual(self.client.patch(url, {'reference_url': 'https://example.com/replaced'}, format='json', **self.headers).status_code, 400)
        self.assertEqual(self.client.patch(url, {'metadata': {'analysis': {'provider': 'fake'}}}, format='json', **self.headers).status_code, 400)
        self.assertEqual(self.client.patch(url, {'metadata': {'note': 'My note'}}, format='json', **self.headers).status_code, 200)
        inspiration.refresh_from_db()
        self.assertEqual(inspiration.metadata['analysis'], {'provider': 'original'})
        self.assertEqual(inspiration.metadata['platform_inspiration_id'], 'library-id')

    def test_user_cannot_mint_raw_learning_evidence(self):
        response = self.client.post('/api/marketing/learning-events/', {'brand': str(self.brand.pk), 'event_type': 'APPROVED', 'outcome': 'POSITIVE'}, format='json', **self.headers)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(LearningEvent.objects.count(), 0)

    def test_preference_evidence_serialization_uses_bounded_queries(self):
        for index in range(15):
            preference = BrandPreference.objects.create(workspace=self.workspace, brand=self.brand, category='VOICE', attribute=f'voice-{index}', value='direct')
            event = LearningEvent.objects.create(workspace=self.workspace, brand=self.brand, event_type='APPROVED')
            PreferenceEvidence.objects.create(preference=preference, learning_event=event)
        with self.assertNumQueries(2):
            data = BrandPreferenceSerializer(BrandPreferenceViewSet.queryset.filter(workspace=self.workspace), many=True).data
        self.assertEqual(len(data), 15)
        self.assertTrue(all(len(row['evidence_event_ids']) == 1 for row in data))
