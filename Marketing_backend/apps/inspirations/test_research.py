from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status

from apps.ai.models import Capability
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.workspaces.models import WorkspaceMember

from .models import BrandInspiration, ResearchFinding, ResearchRun
from .research import execute_research


class ResearchClosureTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.ws1 = self.make_workspace('One', 'research-one')
        self.user1, self.client1 = self.authenticate_as(
            self.ws1, WorkspaceMember.Role.ADMIN, 'research-admin-1'
        )
        self.brand1 = Brand.objects.create(workspace=self.ws1, name='One Brand')
        self.viewer, self.viewer_client = self.authenticate_as(
            self.ws1, WorkspaceMember.Role.VIEWER, 'research-viewer'
        )
        self.ws2 = self.make_workspace('Two', 'research-two')
        self.user2, self.client2 = self.authenticate_as(
            self.ws2, WorkspaceMember.Role.ADMIN, 'research-admin-2'
        )
        self.brand2 = Brand.objects.create(workspace=self.ws2, name='Two Brand')

    def header(self, workspace=None):
        return workspace_header(workspace or self.ws1)

    def test_create_is_queued_and_cross_tenant_brand_is_refused(self):
        response = self.client1.post(
            '/api/marketing/research-runs/',
            {'brand': str(self.brand1.pk), 'query': 'premium retail posters'},
            format='json', **self.header(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        run = ResearchRun.objects.get(pk=response.json()['id'])
        self.assertEqual(run.status, ResearchRun.Status.QUEUED)
        self.assertTrue(run.task_id)

        leaked = self.client1.post(
            '/api/marketing/research-runs/',
            {'brand': str(self.brand2.pk), 'query': 'steal brand context'},
            format='json', **self.header(),
        )
        self.assertEqual(leaked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ResearchRun.objects.filter(brand=self.brand2).count(), 0)

    def test_viewer_cannot_spend_on_research(self):
        response = self.viewer_client.post(
            '/api/marketing/research-runs/',
            {'brand': str(self.brand1.pk), 'query': 'poster references'},
            format='json', **self.header(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('apps.inspirations.research.safe_fetch', return_value=('visible source', 'a' * 64))
    @patch('apps.inspirations.research.assert_safe', return_value=True)
    @patch('apps.inspirations.research.AIRouter.dispatch')
    def test_task_routes_research_verifies_citations_and_is_idempotent(
        self, dispatch, _assert_safe, _safe_fetch
    ):
        dispatch.return_value = {
            'provider': 'customer-research',
            'provider_name': 'Customer research gateway',
            'findings': [{
                'kind': 'POSTER',
                'title': 'Retail launch reference',
                'source_url': 'https://example.com/campaign',
                'preview_url': 'https://example.com/preview.jpg',
                'source_name': 'Example design archive',
                'platform': 'Web',
                'excerpt': 'A high-contrast retail launch.',
                'observed_at': '2026-08-31T10:00:00Z',
            }],
        }
        run = ResearchRun.objects.create(
            workspace=self.ws1, brand=self.brand1, query='retail posters',
            initiated_by=self.user1,
        )
        first = execute_research(run.pk)
        run.status = ResearchRun.Status.QUEUED
        run.save(update_fields=['status', 'updated_at'])
        second = execute_research(run.pk)

        self.assertEqual(first['findings'], 1)
        self.assertEqual(second['findings'], 1)
        self.assertEqual(run.findings.count(), 1)
        self.assertEqual(dispatch.call_args.args[0], Capability.RESEARCH)
        finding = run.findings.get()
        self.assertEqual(finding.verification_status, ResearchFinding.VerificationStatus.VERIFIED)
        self.assertEqual(finding.rights_status, ResearchFinding.RightsStatus.UNKNOWN)
        self.assertEqual(finding.preview_url, 'https://example.com/preview.jpg')

    def test_unverified_or_restricted_findings_cannot_be_adopted(self):
        run = ResearchRun.objects.create(
            workspace=self.ws1, brand=self.brand1, query='references'
        )
        finding = ResearchFinding.objects.create(
            run=run, workspace=self.ws1, brand=self.brand1,
            title='Unsafe', source_url='https://example.com/unsafe',
            dedupe_key='unsafe', verification_status=ResearchFinding.VerificationStatus.FAILED,
        )
        response = self.client1.post(
            f'/api/marketing/research-findings/{finding.pk}/adopt/',
            format='json', **self.header(),
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(BrandInspiration.objects.count(), 0)

        finding.verification_status = ResearchFinding.VerificationStatus.VERIFIED
        finding.rights_status = ResearchFinding.RightsStatus.RESTRICTED
        finding.save(update_fields=['verification_status', 'rights_status', 'updated_at'])
        response = self.client1.post(
            f'/api/marketing/research-findings/{finding.pk}/adopt/',
            format='json', **self.header(),
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_adoption_is_idempotent_and_preserves_lineage(self):
        run = ResearchRun.objects.create(
            workspace=self.ws1, brand=self.brand1, query='references'
        )
        finding = ResearchFinding.objects.create(
            run=run, workspace=self.ws1, brand=self.brand1,
            title='Chosen reference', source_url='https://example.com/chosen',
            source_name='Design archive', dedupe_key='chosen',
            source_content_hash='b' * 64,
            verification_status=ResearchFinding.VerificationStatus.VERIFIED,
        )
        url = f'/api/marketing/research-findings/{finding.pk}/adopt/'
        first = self.client1.post(url, format='json', **self.header())
        second = self.client1.post(url, format='json', **self.header())
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.content)
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.content)
        self.assertEqual(BrandInspiration.objects.count(), 1)
        inspiration = BrandInspiration.objects.get()
        self.assertEqual(inspiration.reference_url, finding.source_url)
        self.assertEqual(inspiration.metadata['research_finding_id'], str(finding.pk))

    def test_models_reject_a_cross_tenant_graph_outside_the_api(self):
        run = ResearchRun(workspace=self.ws1, brand=self.brand2, query='bad')
        with self.assertRaises(ValidationError):
            run.save()

    def test_other_tenant_cannot_read_finding(self):
        run = ResearchRun.objects.create(workspace=self.ws1, brand=self.brand1, query='x')
        finding = ResearchFinding.objects.create(
            run=run, workspace=self.ws1, brand=self.brand1, title='Hidden',
            source_url='https://example.com/hidden', dedupe_key='hidden',
        )
        response = self.client2.get(
            f'/api/marketing/research-findings/{finding.pk}/', **self.header(self.ws2)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
