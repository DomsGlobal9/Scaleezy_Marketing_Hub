"""
Tests for PR2 — Inspiration Intelligence Foundation.

Structured as: the happy paths that prove the feature is connected, then the
adversarial paths that prove it cannot be talked out of its rules. The second
group is the point of the file.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.utils import IntegrityError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.brands.models import Brand
from apps.common.testing import (
    TenantFixtureMixin,
    TenantSecurityAssertions,
    workspace_header,
)
from apps.knowledge.models import BrandSource
from apps.workspaces.models import WorkspaceMember

from .models import BrandInspiration, InspirationSignal
from .services import InspirationSignalError, record_ai_signal

User = get_user_model()

INSPIRATIONS_URL = '/api/marketing/inspirations/'
SIGNALS_URL = '/api/marketing/inspiration-signals/'


class InspirationTestBase(TenantFixtureMixin, TenantSecurityAssertions, TestCase):
    """Two tenants, two brands inside tenant 1, and a viewer."""

    def setUp(self):
        # Tenant 1
        self.workspace1 = self.make_workspace('Workspace 1', 'c1')
        self.user1, self.client1 = self.authenticate_as(
            self.workspace1, WorkspaceMember.Role.ADMIN, 'user1'
        )
        self.viewer, self.viewer_client = self.authenticate_as(
            self.workspace1, WorkspaceMember.Role.VIEWER, 'viewer'
        )
        self.brand1 = Brand.objects.create(workspace=self.workspace1, name='Brand 1')
        # Second brand in the SAME workspace: workspace equality alone is not
        # enough to keep references straight (PR1-002).
        self.brand1b = Brand.objects.create(workspace=self.workspace1, name='Brand 1b')

        # Tenant 2
        self.workspace2 = self.make_workspace('Workspace 2', 'c2')
        self.user2, self.client2 = self.authenticate_as(
            self.workspace2, WorkspaceMember.Role.ADMIN, 'user2'
        )
        self.brand2 = Brand.objects.create(workspace=self.workspace2, name='Brand 2')

        self.source1 = BrandSource.objects.create(
            workspace=self.workspace1,
            brand=self.brand1,
            title='Brand 1 source',
            created_by=self.user1,
        )
        self.source1b = BrandSource.objects.create(
            workspace=self.workspace1, brand=self.brand1b, title='Brand 1b source'
        )
        self.source2 = BrandSource.objects.create(
            workspace=self.workspace2, brand=self.brand2, title='Brand 2 source'
        )

    def ws1(self):
        return workspace_header(self.workspace1)

    def ws2(self):
        return workspace_header(self.workspace2)

    def valid_payload(self, **overrides):
        """The smallest inspiration payload that would otherwise succeed.

        Attack tests start from this and change exactly one field, so a
        rejection can only be attributed to the attack.
        """
        payload = {
            'brand': str(self.brand1.id),
            'title': 'Reference',
            'reference_url': 'https://example.com/x',
        }
        payload.update(overrides)
        return payload

    def upload_payload(self, **overrides):
        """The multipart equivalent of valid_payload()."""
        payload = {
            'brand': str(self.brand1.id),
            'file': SimpleUploadedFile('ref.png', b'binary', content_type='image/png'),
        }
        payload.update(overrides)
        return payload

    def make_inspiration(self, brand=None, workspace=None, source=None, **kwargs):
        return BrandInspiration.objects.create(
            workspace=workspace or self.workspace1,
            brand=brand or self.brand1,
            source=source,
            title=kwargs.pop('title', 'Reference'),
            reference_url=kwargs.pop('reference_url', 'https://example.com/ref'),
            created_by=kwargs.pop('created_by', self.user1),
            **kwargs,
        )

    def make_user_signal(self, inspiration, **kwargs):
        return InspirationSignal.objects.create(
            inspiration=inspiration,
            category=kwargs.pop('category', 'TYPOGRAPHY'),
            attribute=kwargs.pop('attribute', 'headline_face'),
            value=kwargs.pop('value', 'Condensed grotesque'),
            sentiment=kwargs.pop('sentiment', InspirationSignal.Sentiment.LIKED),
            origin=InspirationSignal.Origin.USER,
            user_confirmation=InspirationSignal.UserConfirmation.CONFIRMED,
            created_by=self.user1,
            **kwargs,
        )


class InspirationHappyPathTests(InspirationTestBase):
    def test_create_inspiration_with_source_provenance(self):
        payload = {
            'brand': str(self.brand1.id),
            'source': str(self.source1.id),
            'title': 'Competitor launch post',
            'inspiration_type': BrandInspiration.InspirationType.POST,
            'annotation': 'Love the restraint in the layout.',
            'reference_url': 'https://example.com/post',
        }
        response = self.client1.post(
            INSPIRATIONS_URL, payload, format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body['workspace'], str(self.workspace1.id))
        self.assertEqual(body['source'], str(self.source1.id))
        self.assertEqual(body['created_by'], self.user1.id)
        # Nothing has analysed anything yet, and the API says so.
        self.assertEqual(body['analysis_status'], 'NOT_ANALYSED')
        self.assertEqual(body['retrieval_eligibility'], {'eligible': True, 'reason': 'ACTIVE'})

    def test_supported_inspiration_types_are_provider_neutral(self):
        for kind, platform in [
            (BrandInspiration.InspirationType.REEL, 'instagram'),
            (BrandInspiration.InspirationType.PIN, 'pinterest'),
            (BrandInspiration.InspirationType.COMPETITOR, 'linkedin'),
            (BrandInspiration.InspirationType.VIDEO, 'youtube'),
            (BrandInspiration.InspirationType.SCREENSHOT, ''),
        ]:
            response = self.client1.post(
                INSPIRATIONS_URL,
                {
                    'brand': str(self.brand1.id),
                    'title': f'{kind} reference',
                    'inspiration_type': kind,
                    'external_platform': platform,
                    'reference_url': 'https://example.com/x',
                    'metadata': {'duration_seconds': 15},
                },
                format='json',
                **self.ws1(),
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, kind)
            self.assertEqual(response.json()['external_platform'], platform)

    def test_partial_usage_scope_expresses_use_only_typography(self):
        response = self.client1.post(
            INSPIRATIONS_URL,
            {
                'brand': str(self.brand1.id),
                'title': 'Only the type',
                'reference_url': 'https://example.com/type',
                'usage_scope': BrandInspiration.UsageScope.SPECIFIC_ELEMENTS,
                'focus_areas': ['TYPOGRAPHY'],
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()['focus_areas'], ['TYPOGRAPHY'])

    def test_inspiration_and_signals_are_separately_addressable(self):
        inspiration = self.make_inspiration()
        signal = self.make_user_signal(inspiration)

        detail = self.client1.get(f'{INSPIRATIONS_URL}{inspiration.id}/', **self.ws1())
        self.assertEqual(detail.status_code, status.HTTP_200_OK)

        signal_detail = self.client1.get(f'{SIGNALS_URL}{signal.id}/', **self.ws1())
        self.assertEqual(signal_detail.status_code, status.HTTP_200_OK)

        scoped = self.client1.get(
            f'{SIGNALS_URL}?inspiration_id={inspiration.id}', **self.ws1()
        )
        self.assertEqual(scoped.status_code, status.HTTP_200_OK)
        self.assertEqual(len(scoped.json()), 1)

    def test_signal_mirrors_parent_workspace_and_brand(self):
        inspiration = self.make_inspiration(brand=self.brand1b)
        signal = self.make_user_signal(inspiration)
        body = self.client1.get(f'{SIGNALS_URL}{signal.id}/', **self.ws1()).json()
        self.assertEqual(body['workspace'], str(self.workspace1.id))
        self.assertEqual(body['brand'], str(self.brand1b.id))

    def test_create_signal_is_user_origin_and_confirmed(self):
        inspiration = self.make_inspiration()
        response = self.client1.post(
            SIGNALS_URL,
            {
                'inspiration': str(inspiration.id),
                'category': 'COLOR',
                'attribute': 'accent',
                'value': 'acid green',
                'sentiment': InspirationSignal.Sentiment.DISLIKED,
                'weight': 0.8,
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body['origin'], 'USER')
        self.assertEqual(body['user_confirmation'], 'CONFIRMED')
        self.assertEqual(body['sentiment'], 'DISLIKED')
        self.assertEqual(body['confirmed_by'], self.user1.id)

    def test_upload_stores_reference_and_server_assigns_storage(self):
        file_obj = SimpleUploadedFile('ref.png', b'binary', content_type='image/png')
        response = self.client1.post(
            f'{INSPIRATIONS_URL}upload/',
            {
                'brand': str(self.brand1.id),
                'source': str(self.source1.id),
                'file': file_obj,
                'annotation': 'The grid, not the colours.',
                'usage_scope': BrandInspiration.UsageScope.SPECIFIC_ELEMENTS,
                'focus_areas': ['LAYOUT'],
            },
            format='multipart',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()['data']
        self.assertEqual(data['workspace'], str(self.workspace1.id))
        self.assertEqual(data['file_name'], 'ref.png')
        self.assertIn(str(self.workspace1.id), data['file_url'])
        self.assertEqual(data['focus_areas'], ['LAYOUT'])


class InspirationTenantIsolationTests(InspirationTestBase):
    def test_cross_tenant_brand_injection_blocked(self):
        self.assert_cross_tenant_fk_rejected(
            client=self.client1, url=INSPIRATIONS_URL, workspace=self.workspace1,
            model=BrandInspiration, payload=self.valid_payload(),
            field='brand', foreign_id=self.brand2.id,
        )
        self.assertFalse(BrandInspiration.objects.filter(brand=self.brand2).exists())

    def test_cross_tenant_source_injection_blocked(self):
        self.assert_cross_tenant_fk_rejected(
            client=self.client1, url=INSPIRATIONS_URL, workspace=self.workspace1,
            model=BrandInspiration, payload=self.valid_payload(),
            field='source', foreign_id=self.source2.id,
        )

    def test_cross_brand_source_injection_blocked_inside_one_workspace(self):
        self.assert_cross_brand_fk_rejected(
            client=self.client1, url=INSPIRATIONS_URL, workspace=self.workspace1,
            model=BrandInspiration, payload=self.valid_payload(),
            field='source', foreign_id=self.source1b.id,
        )

    def test_inspiration_is_hidden_from_the_other_tenant(self):
        inspiration = self.make_inspiration()
        self.assert_object_hidden_from_other_workspace(
            client=self.client2,
            detail_url=f'{INSPIRATIONS_URL}{inspiration.id}/',
            list_url=INSPIRATIONS_URL,
            workspace=self.workspace2,
            object_id=inspiration.id,
        )

    def test_signal_is_hidden_from_the_other_tenant(self):
        signal = self.make_user_signal(self.make_inspiration())
        self.assert_object_hidden_from_other_workspace(
            client=self.client2,
            detail_url=f'{SIGNALS_URL}{signal.id}/',
            list_url=SIGNALS_URL,
            workspace=self.workspace2,
            object_id=signal.id,
        )

    def test_staff_without_membership_cannot_read(self):
        staff = User.objects.create_user(username='staff', password='p', is_staff=True)
        staff_client = APIClient()
        staff_client.force_authenticate(user=staff)
        inspiration = self.make_inspiration()
        response = staff_client.get(f'{INSPIRATIONS_URL}{inspiration.id}/', **self.ws1())
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_signal_cannot_attach_to_other_tenant_inspiration(self):
        inspiration = self.make_inspiration()
        response = self.client2.post(
            SIGNALS_URL,
            {
                'inspiration': str(inspiration.id),
                'category': 'COLOR',
                'attribute': 'accent',
                'sentiment': InspirationSignal.Sentiment.LIKED,
            },
            format='json',
            **self.ws2(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('inspiration', response.json())
        self.assertEqual(inspiration.signals.count(), 0)

    def test_upload_cross_tenant_brand_injection_blocked(self):
        self.assert_cross_tenant_fk_rejected(
            client=self.client1, url=f'{INSPIRATIONS_URL}upload/',
            workspace=self.workspace1, model=BrandInspiration,
            payload=self.upload_payload(), field='brand',
            foreign_id=self.brand2.id, format='multipart',
        )

    def test_upload_cross_tenant_source_injection_blocked(self):
        self.assert_cross_tenant_fk_rejected(
            client=self.client1, url=f'{INSPIRATIONS_URL}upload/',
            workspace=self.workspace1, model=BrandInspiration,
            payload=self.upload_payload(), field='source',
            foreign_id=self.source2.id, format='multipart',
        )


    def test_every_mutation_path_is_404_for_another_tenant(self):
        """The custom actions are mutation paths too (GLOBAL-010)."""
        inspiration = self.make_inspiration()
        signal = self.make_user_signal(inspiration)
        attempts = [
            self.client2.patch(
                f'{INSPIRATIONS_URL}{inspiration.id}/',
                {'annotation': 'mine now'},
                format='json',
                **self.ws2(),
            ),
            self.client2.put(
                f'{INSPIRATIONS_URL}{inspiration.id}/',
                {'brand': str(self.brand2.id), 'title': 'mine now'},
                format='json',
                **self.ws2(),
            ),
            self.client2.post(
                f'{INSPIRATIONS_URL}{inspiration.id}/archive/', **self.ws2()
            ),
            self.client2.post(
                f'{INSPIRATIONS_URL}{inspiration.id}/analyze/', format='json', **self.ws2()
            ),
            self.client2.post(
                f'{SIGNALS_URL}{signal.id}/confirm/', format='json', **self.ws2()
            ),
            self.client2.post(
                f'{SIGNALS_URL}{signal.id}/reject/', format='json', **self.ws2()
            ),
            self.client2.patch(
                f'{SIGNALS_URL}{signal.id}/',
                {'value': 'mine now'},
                format='json',
                **self.ws2(),
            ),
        ]
        for response in attempts:
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        inspiration.refresh_from_db()
        signal.refresh_from_db()
        self.assertEqual(inspiration.annotation, '')
        self.assertEqual(
            inspiration.lifecycle_status, BrandInspiration.LifecycleStatus.ACTIVE
        )
        self.assertEqual(signal.value, 'Condensed grotesque')

    def test_upload_cross_brand_source_injection_blocked(self):
        self.assert_cross_brand_fk_rejected(
            client=self.client1, url=f'{INSPIRATIONS_URL}upload/',
            workspace=self.workspace1, model=BrandInspiration,
            payload=self.upload_payload(), field='source',
            foreign_id=self.source1b.id, format='multipart',
        )


class InspirationImmutabilityTests(InspirationTestBase):
    def test_patch_cannot_move_inspiration_to_another_brand(self):
        inspiration = self.make_inspiration()
        self.assert_field_immutable(
            client=self.client1, url=f'{INSPIRATIONS_URL}{inspiration.id}/',
            instance=inspiration, field='brand', new_value=self.brand1b.id,
            workspace=self.workspace1,
        )

    def test_patch_cannot_move_inspiration_to_another_tenant_brand(self):
        inspiration = self.make_inspiration()
        self.assert_field_immutable(
            client=self.client1, url=f'{INSPIRATIONS_URL}{inspiration.id}/',
            instance=inspiration, field='brand', new_value=self.brand2.id,
            workspace=self.workspace1,
        )

    def test_put_cannot_move_inspiration_to_another_brand(self):
        inspiration = self.make_inspiration()
        response = self.client1.put(
            f'{INSPIRATIONS_URL}{inspiration.id}/',
            {
                'brand': str(self.brand1b.id),
                'title': 'Renamed',
                'reference_url': 'https://example.com/ref',
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        inspiration.refresh_from_db()
        self.assertEqual(inspiration.brand_id, self.brand1.id)

    def test_patch_cannot_change_source_provenance(self):
        inspiration = self.make_inspiration(source=self.source1)
        response = self.client1.patch(
            f'{INSPIRATIONS_URL}{inspiration.id}/',
            {'source': None},
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        inspiration.refresh_from_db()
        self.assertEqual(inspiration.source_id, self.source1.id)

    def test_patch_annotation_is_allowed(self):
        """The immutability rules must not freeze the whole record."""
        inspiration = self.make_inspiration()
        response = self.client1.patch(
            f'{INSPIRATIONS_URL}{inspiration.id}/',
            {'annotation': 'Only the pacing, not the copy.'},
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        inspiration.refresh_from_db()
        self.assertEqual(inspiration.annotation, 'Only the pacing, not the copy.')

    def test_patch_cannot_set_lifecycle_or_analysis_status(self):
        inspiration = self.make_inspiration()
        self.assert_protected_state_not_patchable(
            client=self.client1, url=f'{INSPIRATIONS_URL}{inspiration.id}/',
            instance=inspiration, workspace=self.workspace1,
            updates={'lifecycle_status': 'ARCHIVED', 'analysis_status': 'READY'},
        )
        self.assertEqual(inspiration.lifecycle_status, 'ACTIVE')
        self.assertEqual(inspiration.analysis_status, 'NOT_ANALYSED')

    def test_client_cannot_set_storage_coordinates(self):
        response = self.client1.post(
            INSPIRATIONS_URL,
            {
                'brand': str(self.brand1.id),
                'title': 'Pointing at someone else',
                'reference_url': 'https://example.com/x',
                'storage_path': 'inspirations/other-workspace/secret.png',
                'file_url': 'https://storage.test/other-workspace/secret.png',
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        inspiration = BrandInspiration.objects.get(id=response.json()['id'])
        self.assertIsNone(inspiration.storage_path)
        self.assertIsNone(inspiration.file_url)

    def test_signal_inspiration_is_immutable(self):
        inspiration = self.make_inspiration()
        other = self.make_inspiration(title='Other')
        signal = self.make_user_signal(inspiration)
        self.assert_field_immutable(
            client=self.client1, url=f'{SIGNALS_URL}{signal.id}/',
            instance=signal, field='inspiration', new_value=other.id,
            workspace=self.workspace1,
        )

    def test_inspiration_requires_a_reference(self):
        response = self.client1.post(
            INSPIRATIONS_URL,
            {'brand': str(self.brand1.id), 'title': 'Nothing attached'},
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class InspirationProvenanceTests(InspirationTestBase):
    """AI-derived and user-stated preferences must never blur together."""

    def test_payload_cannot_mint_an_ai_signal(self):
        inspiration = self.make_inspiration()
        response = self.client1.post(
            SIGNALS_URL,
            {
                'inspiration': str(inspiration.id),
                'category': 'TONE',
                'attribute': 'register',
                'sentiment': InspirationSignal.Sentiment.LIKED,
                'origin': 'AI',
                'extracted_by_provider': 'gemini',
                'user_confirmation': 'PENDING',
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        signal = InspirationSignal.objects.get(id=response.json()['id'])
        self.assertEqual(signal.origin, InspirationSignal.Origin.USER)
        self.assertEqual(signal.extracted_by_provider, '')
        self.assertEqual(
            signal.user_confirmation, InspirationSignal.UserConfirmation.CONFIRMED
        )

    def test_patch_cannot_convert_ai_signal_to_user_origin(self):
        inspiration = self.make_inspiration()
        ai_signal = record_ai_signal(
            inspiration=inspiration,
            category='COLOR',
            attribute='palette',
            value='muted earth',
            sentiment=InspirationSignal.Sentiment.LIKED,
            provider='test-provider',
        )
        self.assert_protected_state_not_patchable(
            client=self.client1, url=f'{SIGNALS_URL}{ai_signal.id}/',
            instance=ai_signal, workspace=self.workspace1,
            updates={'origin': 'USER', 'user_confirmation': 'CONFIRMED'},
        )
        self.assertEqual(ai_signal.origin, InspirationSignal.Origin.AI)
        self.assertEqual(
            ai_signal.user_confirmation, InspirationSignal.UserConfirmation.PENDING
        )

    def test_confirming_an_ai_signal_keeps_it_ai_derived(self):
        inspiration = self.make_inspiration()
        ai_signal = record_ai_signal(
            inspiration=inspiration,
            category='COLOR',
            attribute='palette',
            sentiment=InspirationSignal.Sentiment.LIKED,
        )
        response = self.client1.post(
            f'{SIGNALS_URL}{ai_signal.id}/confirm/', format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ai_signal.refresh_from_db()
        self.assertEqual(ai_signal.origin, InspirationSignal.Origin.AI)
        self.assertEqual(
            ai_signal.user_confirmation, InspirationSignal.UserConfirmation.CONFIRMED
        )
        self.assertEqual(ai_signal.confirmed_by_id, self.user1.id)

    def test_ai_signal_does_not_overwrite_user_signal(self):
        inspiration = self.make_inspiration()
        user_signal = self.make_user_signal(
            inspiration,
            category='TYPOGRAPHY',
            attribute='headline_face',
            sentiment=InspirationSignal.Sentiment.LIKED,
            value='Condensed grotesque',
        )

        ai_signal = record_ai_signal(
            inspiration=inspiration,
            category='TYPOGRAPHY',
            attribute='headline_face',
            value='Serif display',
            sentiment=InspirationSignal.Sentiment.DISLIKED,
            provider='test-provider',
        )

        user_signal.refresh_from_db()
        self.assertEqual(user_signal.sentiment, InspirationSignal.Sentiment.LIKED)
        self.assertEqual(user_signal.value, 'Condensed grotesque')
        self.assertEqual(user_signal.origin, InspirationSignal.Origin.USER)

        # The contradiction is recorded, not applied and not dropped.
        self.assertEqual(ai_signal.conflicts_with_id, user_signal.id)
        self.assertFalse(ai_signal.retrieval_eligibility()['eligible'])
        self.assertEqual(
            ai_signal.retrieval_eligibility()['reason'], 'CONFLICTS_WITH_USER_SIGNAL'
        )
        self.assertTrue(user_signal.retrieval_eligibility()['eligible'])

    def test_agreeing_ai_signal_is_not_flagged_as_conflict(self):
        inspiration = self.make_inspiration()
        self.make_user_signal(
            inspiration, sentiment=InspirationSignal.Sentiment.LIKED
        )
        ai_signal = record_ai_signal(
            inspiration=inspiration,
            category='TYPOGRAPHY',
            attribute='headline_face',
            sentiment=InspirationSignal.Sentiment.LIKED,
        )
        self.assertIsNone(ai_signal.conflicts_with_id)
        self.assertTrue(ai_signal.retrieval_eligibility()['eligible'])

    def test_record_ai_signal_is_idempotent(self):
        inspiration = self.make_inspiration()
        first = record_ai_signal(
            inspiration=inspiration,
            category='MOOD',
            attribute='overall',
            value='calm',
            sentiment=InspirationSignal.Sentiment.LIKED,
        )
        second = record_ai_signal(
            inspiration=inspiration,
            category='MOOD',
            attribute='overall',
            value='calm and confident',
            sentiment=InspirationSignal.Sentiment.LIKED,
        )
        self.assertEqual(first.id, second.id)
        self.assertEqual(
            inspiration.signals.filter(origin=InspirationSignal.Origin.AI).count(), 1
        )
        second.refresh_from_db()
        self.assertEqual(second.value, 'calm and confident')

    def test_reanalysis_does_not_reset_a_user_verdict(self):
        inspiration = self.make_inspiration()
        ai_signal = record_ai_signal(
            inspiration=inspiration,
            category='MOOD',
            attribute='overall',
            sentiment=InspirationSignal.Sentiment.LIKED,
        )
        self.client1.post(f'{SIGNALS_URL}{ai_signal.id}/reject/', format='json', **self.ws1())

        record_ai_signal(
            inspiration=inspiration,
            category='MOOD',
            attribute='overall',
            sentiment=InspirationSignal.Sentiment.LIKED,
        )
        ai_signal.refresh_from_db()
        self.assertEqual(
            ai_signal.user_confirmation, InspirationSignal.UserConfirmation.REJECTED
        )

    def test_duplicate_ai_signal_rows_are_rejected_by_the_database(self):
        inspiration = self.make_inspiration()
        record_ai_signal(
            inspiration=inspiration,
            category='MOOD',
            attribute='overall',
            sentiment=InspirationSignal.Sentiment.LIKED,
        )
        with self.assertRaises(IntegrityError):
            InspirationSignal.objects.create(
                inspiration=inspiration,
                category='MOOD',
                attribute='overall',
                sentiment=InspirationSignal.Sentiment.LIKED,
                origin=InspirationSignal.Origin.AI,
            )

    def test_ai_signal_rejected_for_archived_inspiration(self):
        inspiration = self.make_inspiration(
            lifecycle_status=BrandInspiration.LifecycleStatus.ARCHIVED
        )
        with self.assertRaises(InspirationSignalError):
            record_ai_signal(
                inspiration=inspiration,
                category='MOOD',
                attribute='overall',
                sentiment=InspirationSignal.Sentiment.LIKED,
            )


class InspirationSentimentTests(InspirationTestBase):
    def test_sentiment_is_required(self):
        inspiration = self.make_inspiration()
        response = self.client1.post(
            SIGNALS_URL,
            {
                'inspiration': str(inspiration.id),
                'category': 'COLOR',
                'attribute': 'accent',
                'weight': 0.9,
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sentiment', response.json())

    def test_weight_does_not_imply_sentiment(self):
        """A heavy dislike is still a dislike."""
        inspiration = self.make_inspiration()
        response = self.client1.post(
            SIGNALS_URL,
            {
                'inspiration': str(inspiration.id),
                'category': 'IMAGERY',
                'attribute': 'stock_photography',
                'sentiment': InspirationSignal.Sentiment.DISLIKED,
                'weight': 0.95,
                'confidence': 1.0,
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        signal = InspirationSignal.objects.get(id=response.json()['id'])
        self.assertEqual(signal.sentiment, InspirationSignal.Sentiment.DISLIKED)
        self.assertEqual(signal.weight, 0.95)

    def test_weight_out_of_range_is_rejected(self):
        inspiration = self.make_inspiration()
        response = self.client1.post(
            SIGNALS_URL,
            {
                'inspiration': str(inspiration.id),
                'category': 'IMAGERY',
                'attribute': 'stock_photography',
                'sentiment': InspirationSignal.Sentiment.NEUTRAL,
                'weight': 4.2,
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('weight', response.json())


class InspirationLifecycleTests(InspirationTestBase):
    def test_analyze_is_not_implemented(self):
        inspiration = self.make_inspiration()
        response = self.client1.post(
            f'{INSPIRATIONS_URL}{inspiration.id}/analyze/', format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_501_NOT_IMPLEMENTED)
        self.assertFalse(response.json()['success'])
        inspiration.refresh_from_db()
        self.assertEqual(
            inspiration.analysis_status, BrandInspiration.AnalysisStatus.NOT_ANALYSED
        )

    def test_analyze_archived_inspiration_is_rejected(self):
        inspiration = self.make_inspiration()
        self.client1.post(f'{INSPIRATIONS_URL}{inspiration.id}/archive/', **self.ws1())
        response = self.client1.post(
            f'{INSPIRATIONS_URL}{inspiration.id}/analyze/', format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_archive_makes_inspiration_ineligible(self):
        inspiration = self.make_inspiration()
        response = self.client1.post(
            f'{INSPIRATIONS_URL}{inspiration.id}/archive/', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        inspiration.refresh_from_db()
        self.assertEqual(
            inspiration.lifecycle_status, BrandInspiration.LifecycleStatus.ARCHIVED
        )
        self.assertEqual(inspiration.archived_by_id, self.user1.id)
        self.assertIsNotNone(inspiration.archived_at)
        self.assertEqual(
            inspiration.retrieval_eligibility(),
            {'eligible': False, 'reason': 'INSPIRATION_ARCHIVED'},
        )
        self.assertNotIn(
            inspiration, BrandInspiration.objects.eligible_for_retrieval()
        )

    def test_repeating_archive_does_not_compound(self):
        inspiration = self.make_inspiration()

        def state():
            inspiration.refresh_from_db()
            return (inspiration.lifecycle_status, inspiration.archived_at)

        self.assert_duplicate_action_idempotent(
            client=self.client1,
            url=f'{INSPIRATIONS_URL}{inspiration.id}/archive/',
            workspace=self.workspace1,
            state_of=state,
            expected_second_status=status.HTTP_400_BAD_REQUEST,
        )

    def test_repeating_analyze_does_not_compound(self):
        inspiration = self.make_inspiration()

        def state():
            inspiration.refresh_from_db()
            return (inspiration.analysis_status, inspiration.signals.count())

        self.assert_duplicate_action_idempotent(
            client=self.client1,
            url=f'{INSPIRATIONS_URL}{inspiration.id}/analyze/',
            workspace=self.workspace1,
            state_of=state,
            expected_second_status=status.HTTP_501_NOT_IMPLEMENTED,
        )

    def test_archive_twice_is_rejected(self):
        inspiration = self.make_inspiration()
        self.client1.post(f'{INSPIRATIONS_URL}{inspiration.id}/archive/', **self.ws1())
        response = self.client1.post(
            f'{INSPIRATIONS_URL}{inspiration.id}/archive/', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_archived_source_makes_inspiration_ineligible(self):
        inspiration = self.make_inspiration(source=self.source1)
        self.source1.status = BrandSource.SourceStatus.ARCHIVED
        self.source1.save(update_fields=['status'])

        inspiration.refresh_from_db()
        self.assertEqual(
            inspiration.retrieval_eligibility(),
            {'eligible': False, 'reason': 'SOURCE_ARCHIVED'},
        )
        self.assertNotIn(
            inspiration, BrandInspiration.objects.eligible_for_retrieval()
        )
        # And the API reports it honestly rather than still looking usable.
        body = self.client1.get(f'{INSPIRATIONS_URL}{inspiration.id}/', **self.ws1()).json()
        self.assertFalse(body['retrieval_eligibility']['eligible'])

    def test_inspiration_without_a_source_stays_eligible(self):
        """The archived-source exclusion must not drop source-less rows."""
        inspiration = self.make_inspiration(source=None)
        self.assertIn(inspiration, BrandInspiration.objects.eligible_for_retrieval())

    def test_eligible_only_filter_matches_the_retrieval_rule(self):
        active = self.make_inspiration(title='Active')
        archived = self.make_inspiration(title='Archived')
        self.client1.post(f'{INSPIRATIONS_URL}{archived.id}/archive/', **self.ws1())

        response = self.client1.get(f'{INSPIRATIONS_URL}?eligible_only=true', **self.ws1())
        ids = [row['id'] for row in response.json()]
        self.assertEqual(ids, [str(active.id)])

    def test_archived_inspiration_cannot_receive_new_signals(self):
        inspiration = self.make_inspiration()
        self.client1.post(f'{INSPIRATIONS_URL}{inspiration.id}/archive/', **self.ws1())
        response = self.client1.post(
            SIGNALS_URL,
            {
                'inspiration': str(inspiration.id),
                'category': 'COLOR',
                'attribute': 'accent',
                'sentiment': InspirationSignal.Sentiment.LIKED,
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_archived_source_cannot_start_a_new_inspiration(self):
        self.source1.status = BrandSource.SourceStatus.ARCHIVED
        self.source1.save(update_fields=['status'])
        response = self.client1.post(
            INSPIRATIONS_URL,
            {
                'brand': str(self.brand1.id),
                'source': str(self.source1.id),
                'title': 'From a revoked source',
                'reference_url': 'https://example.com/x',
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('source', response.json())

    def test_rejected_signal_is_ineligible(self):
        signal = self.make_user_signal(self.make_inspiration())
        response = self.client1.post(
            f'{SIGNALS_URL}{signal.id}/reject/', format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        signal.refresh_from_db()
        self.assertEqual(
            signal.retrieval_eligibility(),
            {'eligible': False, 'reason': 'REJECTED_BY_USER'},
        )
        self.assertNotIn(signal, InspirationSignal.objects.eligible_for_retrieval())

    def test_signals_of_archived_inspiration_are_ineligible(self):
        inspiration = self.make_inspiration()
        signal = self.make_user_signal(inspiration)
        self.client1.post(f'{INSPIRATIONS_URL}{inspiration.id}/archive/', **self.ws1())
        signal.refresh_from_db()
        self.assertFalse(signal.retrieval_eligibility()['eligible'])
        self.assertNotIn(signal, InspirationSignal.objects.eligible_for_retrieval())

    def test_delete_inspiration_is_disabled(self):
        inspiration = self.make_inspiration()
        response = self.client1.delete(
            f'{INSPIRATIONS_URL}{inspiration.id}/', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(BrandInspiration.objects.filter(id=inspiration.id).exists())

    def test_delete_signal_is_disabled(self):
        signal = self.make_user_signal(self.make_inspiration())
        response = self.client1.delete(f'{SIGNALS_URL}{signal.id}/', **self.ws1())
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(InspirationSignal.objects.filter(id=signal.id).exists())


class InspirationUsageScopeTests(InspirationTestBase):
    def test_specific_elements_requires_focus_areas(self):
        response = self.client1.post(
            INSPIRATIONS_URL,
            {
                'brand': str(self.brand1.id),
                'title': 'Ambiguous',
                'reference_url': 'https://example.com/x',
                'usage_scope': BrandInspiration.UsageScope.SPECIFIC_ELEMENTS,
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('focus_areas', response.json())

    def test_full_reference_rejects_focus_areas(self):
        response = self.client1.post(
            INSPIRATIONS_URL,
            {
                'brand': str(self.brand1.id),
                'title': 'Contradictory',
                'reference_url': 'https://example.com/x',
                'usage_scope': BrandInspiration.UsageScope.FULL_REFERENCE,
                'focus_areas': ['TYPOGRAPHY'],
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('focus_areas', response.json())

    def test_unknown_focus_area_is_rejected(self):
        response = self.client1.post(
            INSPIRATIONS_URL,
            {
                'brand': str(self.brand1.id),
                'title': 'Nonsense focus',
                'reference_url': 'https://example.com/x',
                'usage_scope': BrandInspiration.UsageScope.SPECIFIC_ELEMENTS,
                'focus_areas': ['VIBES'],
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('focus_areas', response.json())

    def test_usage_scope_can_be_widened_back_to_the_whole_reference(self):
        """The scope rules must leave a legal way back."""
        inspiration = self.make_inspiration(
            usage_scope=BrandInspiration.UsageScope.SPECIFIC_ELEMENTS,
            focus_areas=['TYPOGRAPHY'],
        )
        response = self.client1.patch(
            f'{INSPIRATIONS_URL}{inspiration.id}/',
            {
                'usage_scope': BrandInspiration.UsageScope.FULL_REFERENCE,
                'focus_areas': [],
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        inspiration.refresh_from_db()
        self.assertEqual(
            inspiration.usage_scope, BrandInspiration.UsageScope.FULL_REFERENCE
        )
        self.assertEqual(inspiration.focus_areas, [])

    def test_patch_to_specific_elements_without_focus_areas_is_rejected(self):
        """Partial PATCH is validated against the resulting object (PR1-008)."""
        inspiration = self.make_inspiration()
        response = self.client1.patch(
            f'{INSPIRATIONS_URL}{inspiration.id}/',
            {'usage_scope': BrandInspiration.UsageScope.SPECIFIC_ELEMENTS},
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        inspiration.refresh_from_db()
        self.assertEqual(
            inspiration.usage_scope, BrandInspiration.UsageScope.FULL_REFERENCE
        )


class InspirationRBACTests(InspirationTestBase):
    def test_viewer_can_read(self):
        """Positive control: the role gate restricts writes, not the team."""
        inspiration = self.make_inspiration()
        response = self.viewer_client.get(
            f'{INSPIRATIONS_URL}{inspiration.id}/', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_cannot_create_inspiration(self):
        self.assert_viewer_mutation_denied(
            client=self.viewer_client, method='post', url=INSPIRATIONS_URL,
            workspace=self.workspace1, model=BrandInspiration,
            payload=self.valid_payload(),
        )

    def test_viewer_cannot_upload_inspiration(self):
        self.assert_viewer_mutation_denied(
            client=self.viewer_client, method='post',
            url=f'{INSPIRATIONS_URL}upload/', workspace=self.workspace1,
            model=BrandInspiration, payload=self.upload_payload(),
            format='multipart',
        )

    def test_viewer_cannot_create_signal(self):
        inspiration = self.make_inspiration()
        self.assert_viewer_mutation_denied(
            client=self.viewer_client, method='post', url=SIGNALS_URL,
            workspace=self.workspace1, model=InspirationSignal,
            payload={
                'inspiration': str(inspiration.id),
                'category': 'COLOR',
                'attribute': 'accent',
                'sentiment': InspirationSignal.Sentiment.LIKED,
            },
        )

    def test_viewer_cannot_archive_inspiration(self):
        inspiration = self.make_inspiration()
        self.assert_viewer_mutation_denied(
            client=self.viewer_client, method='post',
            url=f'{INSPIRATIONS_URL}{inspiration.id}/archive/',
            workspace=self.workspace1, model=BrandInspiration, payload={},
        )
        inspiration.refresh_from_db()
        self.assertEqual(
            inspiration.lifecycle_status, BrandInspiration.LifecycleStatus.ACTIVE
        )

    def test_viewer_is_denied_on_every_mutation_path(self):
        """A role gate that holds on the endpoints nobody remembers to test.

        Table-driven because the failure mode here is a path being added later
        without a matching test, not any one of these cases being subtle.
        """
        inspiration = self.make_inspiration()
        signal = self.make_user_signal(inspiration)
        detail = f'{INSPIRATIONS_URL}{inspiration.id}/'
        signal_detail = f'{SIGNALS_URL}{signal.id}/'

        cases = [
            ('patch', detail, {'annotation': 'nope'}, BrandInspiration),
            ('put', detail, self.valid_payload(title='nope'), BrandInspiration),
            ('delete', detail, None, BrandInspiration),
            ('post', f'{detail}analyze/', {}, BrandInspiration),
            ('patch', signal_detail, {'value': 'nope'}, InspirationSignal),
            ('post', f'{signal_detail}confirm/', {}, InspirationSignal),
            ('post', f'{signal_detail}reject/', {}, InspirationSignal),
            ('delete', signal_detail, None, InspirationSignal),
        ]
        for method, url, payload, model in cases:
            with self.subTest(method=method, url=url):
                self.assert_viewer_mutation_denied(
                    client=self.viewer_client, method=method, url=url,
                    workspace=self.workspace1, model=model, payload=payload,
                )

        inspiration.refresh_from_db()
        signal.refresh_from_db()
        self.assertEqual(inspiration.annotation, '')
        self.assertEqual(
            inspiration.lifecycle_status, BrandInspiration.LifecycleStatus.ACTIVE
        )
        self.assertEqual(signal.value, 'Condensed grotesque')
        self.assertEqual(
            signal.user_confirmation, InspirationSignal.UserConfirmation.CONFIRMED
        )


class InspirationModelInvariantTests(InspirationTestBase):
    """The tenancy rule holds for ORM writers too, not just for requests.

    Serializers guard the API. Jobs, management commands and future services
    write through the model, and a row whose brand belongs to another
    workspace would not look like an error afterwards — it would look like
    data.
    """

    def test_model_refuses_a_brand_from_another_workspace(self):
        with self.assertRaises(ValidationError):
            BrandInspiration.objects.create(
                workspace=self.workspace1,
                brand=self.brand2,
                title='Smuggled',
                reference_url='https://example.com/x',
            )
        self.assertFalse(BrandInspiration.objects.exists())

    def test_model_refuses_a_source_from_another_brand(self):
        with self.assertRaises(ValidationError):
            BrandInspiration.objects.create(
                workspace=self.workspace1,
                brand=self.brand1,
                source=self.source1b,
                title='Wrong provenance',
                reference_url='https://example.com/x',
            )
        self.assertFalse(BrandInspiration.objects.exists())

    def test_model_refuses_a_source_from_another_workspace(self):
        with self.assertRaises(ValidationError):
            BrandInspiration.objects.create(
                workspace=self.workspace1,
                brand=self.brand1,
                source=self.source2,
                title='Foreign provenance',
                reference_url='https://example.com/x',
            )
        self.assertFalse(BrandInspiration.objects.exists())
