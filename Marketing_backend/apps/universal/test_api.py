"""
The client-facing universal endpoints, through HTTP with tenant permissions.

What these prove: a note returns cards and writes nothing but the note; a
pending client is refused before any provider call; accepting a card writes a
SOFT rule or a CONFIRMED memory and nothing stronger; a brand id from another
workspace is not found; the library honours the opt-out; adoption copies into
the brand's own inspirations; enrichment returns its report; a VIEWER cannot
write through any of it.
"""
import uuid
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework import status

from apps.brands.models import Brand
from apps.brands.services.brand_brain import rebuild_brand_brain
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.inspirations.models import BrandInspiration
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import BrandRule
from apps.universal.models import PlatformInspiration
from apps.universal.services import publish_inspiration, set_client_universal
from apps.workspaces.models import WorkspaceMember

NOTE = "We never discount, and our tone is warm but not cutesy."
LIBRARY = '/api/marketing/universal/library/'


def notes_url(brand):
    return f'/api/marketing/brands/{brand.pk}/notes/'


def enrich_url(brand):
    return f'/api/marketing/brands/{brand.pk}/enrich/'


class UniversalAPITests(TenantFixtureMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.workspace = self.make_workspace('Acme', 'c1')
        self.user, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner@acme.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', industry='Coffee',
            website='https://acme.test', is_default=True, status=Brand.Status.ACTIVE,
        )
        rebuild_brand_brain(self.brand)
        self.headers = workspace_header(self.workspace)

        self.other_workspace = self.make_workspace('Rival', 'c2')
        self.other_brand = Brand.objects.create(
            workspace=self.other_workspace, name='Rival Tea', industry='Tea',
            website='https://rival.test', is_default=True, status=Brand.Status.ACTIVE,
        )

    def parse_returning(self, proposals):
        return patch(
            'apps.ai.router.AIRouter.dispatch',
            return_value={'raw': {'proposals': proposals}, 'provider': 'TEST'},
        )

    def make_pending(self):
        self.brand.status = Brand.Status.PENDING
        self.brand.save(update_fields=['status'])

    # ───────────────────────────────────────────── notes

    def test_a_note_returns_cards_and_writes_nothing_but_the_note(self):
        memories_before = BrandMemory.objects.count()
        rules_before = BrandRule.objects.count()
        with self.parse_returning([
            {'kind': 'TONE', 'category': 'TONE', 'attribute': 'register',
             'value': 'warm', 'text': 'Tone is warm but not cutesy',
             'quote': 'our tone is warm but not cutesy'},
            {'kind': 'FACT', 'text': 'Market leader', 'quote': 'we lead the market'},
        ]) as dispatch:
            response = self.api.post(
                notes_url(self.brand), {'text': NOTE}, format='json', **self.headers,
            )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual(dispatch.call_count, 1)
        # Only the grounded card survives; nothing is marked accepted.
        self.assertEqual([p['kind'] for p in data['proposals']], ['TONE'])
        self.assertFalse(data['proposals'][0]['accepted'])

        note = BrandSource.objects.get(pk=data['note_id'])
        self.assertEqual(note.raw_text, NOTE)
        self.assertEqual(note.brand, self.brand)
        self.assertEqual(BrandMemory.objects.count(), memories_before)
        self.assertEqual(BrandRule.objects.count(), rules_before)

    def test_a_pending_client_is_refused_before_any_provider_call(self):
        self.make_pending()
        with self.parse_returning([]) as dispatch:
            response = self.api.post(
                notes_url(self.brand), {'text': NOTE}, format='json', **self.headers,
            )
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(response.json()['error']['code'], 'CLIENT_NOT_APPROVED')
            self.assertEqual(dispatch.call_count, 0)
            # Not even the note is stored: the client cannot use the feature yet.
            self.assertFalse(BrandSource.objects.filter(brand=self.brand).exists())

            with patch('apps.universal.enrichment.safe_fetch') as fetch:
                response = self.api.post(enrich_url(self.brand), {}, format='json', **self.headers)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(response.json()['error']['code'], 'CLIENT_NOT_APPROVED')
                self.assertEqual(fetch.call_count, 0)

    def test_an_empty_note_is_refused(self):
        response = self.api.post(
            notes_url(self.brand), {'text': '   '}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(BrandSource.objects.filter(brand=self.brand).exists())

    def test_accept_writes_a_soft_rule_or_a_confirmed_memory(self):
        with self.parse_returning([]):
            note_id = self.api.post(
                notes_url(self.brand), {'text': NOTE}, format='json', **self.headers,
            ).json()['data']['note_id']
        accept = f'{notes_url(self.brand)}{note_id}/accept/'

        response = self.api.post(
            accept, {'proposal': {'kind': 'PREFERENCE', 'text': 'Never discount'}},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()['data']
        self.assertEqual(data['kind'], 'PREFERENCE')
        rule = BrandRule.objects.get(pk=data['id'])
        self.assertEqual(rule.hardness, BrandRule.Hardness.SOFT)
        self.assertEqual(rule.brand, self.brand)
        self.assertEqual(rule.workspace, self.workspace)

        response = self.api.post(
            accept, {'proposal': {'kind': 'FACT', 'text': 'We never discount'}},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        memory = BrandMemory.objects.get(pk=response.json()['data']['id'])
        self.assertEqual(memory.status, BrandMemory.MemoryStatus.CONFIRMED)
        self.assertEqual(str(memory.source_id), note_id)

        # A hard rule cannot be minted through this door.
        response = self.api.post(
            accept, {'proposal': {'kind': 'HARD_RULE', 'text': 'x'}},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(BrandRule.objects.filter(hardness=BrandRule.Hardness.HARD).exists())

    def test_a_brand_from_another_workspace_is_not_found(self):
        with self.parse_returning([]) as dispatch:
            response = self.api.post(
                notes_url(self.other_brand), {'text': NOTE}, format='json', **self.headers,
            )
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(dispatch.call_count, 0)
        self.assertFalse(BrandSource.objects.filter(brand=self.other_brand).exists())

        response = self.api.post(enrich_url(self.other_brand), {}, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # And an accept aimed at a note in another workspace is not found either.
        foreign_note = BrandSource.objects.create(
            workspace=self.other_workspace, brand=self.other_brand,
            source_type=BrandSource.SourceType.OTHER, title='theirs', raw_text='theirs',
            status=BrandSource.SourceStatus.READY,
        )
        response = self.api.post(
            f'{notes_url(self.brand)}{foreign_note.pk}/accept/',
            {'proposal': {'kind': 'FACT', 'text': 'x'}}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(BrandMemory.objects.filter(brand=self.brand).exists())

    # ───────────────────────────────────────────── library

    def test_the_library_respects_the_opt_out_and_hides_the_curator(self):
        reference = publish_inspiration(PlatformInspiration.objects.create(
            title='Great minimal poster', reference_url='https://example.test/poster',
            annotation='Negative space.', tags=['minimal'], industry='Coffee',
        ))
        PlatformInspiration.objects.create(
            title='Still a draft', reference_url='https://example.test/draft',
        )
        response = self.api.get(LIBRARY, **self.headers)
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()['data']['inspirations']
        self.assertEqual([r['id'] for r in rows], [str(reference.pk)])
        self.assertNotIn('curated_by', rows[0])
        self.assertEqual(rows[0]['adoption_count'], 0)

        response = self.api.get(LIBRARY, {'industry': 'Tea'}, **self.headers)
        self.assertEqual(response.json()['data']['inspirations'], [])

        set_client_universal(self.workspace, inspirations=False, by=self.user)
        response = self.api.get(LIBRARY, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['inspirations'], [])
        # Opted out means not adoptable either.
        response = self.api.post(
            f'{LIBRARY}{reference.pk}/adopt/', {'brand_id': str(self.brand.pk)},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(BrandInspiration.objects.filter(brand=self.brand).exists())

    def test_adopt_copies_into_the_brands_own_inspirations(self):
        reference = publish_inspiration(PlatformInspiration.objects.create(
            title='Great minimal poster', reference_url='https://example.test/poster',
            annotation='Negative space.',
        ))
        url = f'/api/marketing/inspirations/library/{reference.pk}/adopt/'
        response = self.api.post(
            url, {'brand_id': str(self.brand.pk)}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()['data']
        self.assertTrue(data['created'])
        adopted = BrandInspiration.objects.get(pk=data['inspiration_id'])
        self.assertEqual(adopted.brand, self.brand)
        self.assertEqual(adopted.workspace, self.workspace)
        self.assertEqual(adopted.metadata['platform_inspiration_id'], str(reference.pk))

        # Idempotent, and never into somebody else's brand.
        response = self.api.post(
            url, {'brand_id': str(self.brand.pk)}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['data']['created'])
        response = self.api.post(
            url, {'brand_id': str(self.other_brand.pk)}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(BrandInspiration.objects.count(), 1)

        # A draft reference is refused by the service.
        draft = PlatformInspiration.objects.create(
            title='Draft', reference_url='https://example.test/d',
        )
        response = self.api.post(
            f'{LIBRARY}{draft.pk}/adopt/', {'brand_id': str(self.brand.pk)},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ───────────────────────────────────────────── enrichment

    def test_enrich_returns_the_report_and_captures_discovered_sources(self):
        with patch(
            'apps.universal.enrichment.safe_fetch',
            return_value=('Acme roasts coffee in small batches.', 'hash-1'),
        ):
            response = self.api.post(enrich_url(self.brand), {}, format='json', **self.headers)
        self.assertEqual(response.status_code, 200, response.content)
        report = response.json()['data']
        self.assertFalse(report['skipped'])
        self.assertEqual(report['host'], 'acme.test')
        self.assertEqual(report['pages_fetched'], 1)
        source = BrandSource.objects.get(pk=report['sources_created'][0])
        self.assertEqual(source.metadata['origin'], 'DISCOVERED')
        self.assertEqual(source.workspace, self.workspace)

        self.brand.website = ''
        self.brand.save(update_fields=['website'])
        response = self.api.post(enrich_url(self.brand), {}, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['error']['code'], 'ENRICHMENT_FAILED')

    # ───────────────────────────────────────────── roles

    def test_a_viewer_can_read_the_library_but_cannot_post_anything(self):
        _, viewer_api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.VIEWER, 'viewer@acme.test'
        )
        reference = publish_inspiration(PlatformInspiration.objects.create(
            title='Poster', reference_url='https://example.test/p',
        ))
        self.assertEqual(viewer_api.get(LIBRARY, **self.headers).status_code, 200)

        with self.parse_returning([]) as dispatch:
            response = viewer_api.post(
                notes_url(self.brand), {'text': NOTE}, format='json', **self.headers,
            )
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(dispatch.call_count, 0)
        self.assertFalse(BrandSource.objects.filter(brand=self.brand).exists())

        response = viewer_api.post(
            f'{LIBRARY}{reference.pk}/adopt/', {'brand_id': str(self.brand.pk)},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(BrandInspiration.objects.exists())

        with patch('apps.universal.enrichment.safe_fetch') as fetch:
            response = viewer_api.post(enrich_url(self.brand), {}, format='json', **self.headers)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(fetch.call_count, 0)

        response = viewer_api.post(
            f'{notes_url(self.brand)}{uuid.uuid4()}/accept/',
            {'proposal': {'kind': 'FACT', 'text': 'x'}}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_no_workspace_header_and_no_membership_means_nothing_resolves(self):
        outsider_ws = self.make_workspace('Outsider', 'c3')
        _, outsider_api = self.authenticate_as(
            outsider_ws, WorkspaceMember.Role.OWNER, 'owner@outsider.test'
        )
        # Pointing at Acme's workspace from an Outsider account: refused.
        response = outsider_api.post(
            notes_url(self.brand), {'text': NOTE}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Using their own (single) workspace, Acme's brand is simply absent.
        response = outsider_api.post(notes_url(self.brand), {'text': NOTE}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(BrandSource.objects.filter(brand=self.brand).exists())
