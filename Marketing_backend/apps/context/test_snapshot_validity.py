"""Saved and warm-cached context cannot outlive authoritative eligibility."""
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.brands.models import Brand
from apps.brands.services.brand_brain import (
    brain_snapshot_needs_refresh,
    compile_brand_brain,
    rebuild_brand_brain,
)
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import BrandRule
from apps.universal.models import LifecycleStatus, UniversalStandard
from apps.workspaces.models import WorkspaceMember

from .services.context_gateway import ContextError, build_generation_context, resolved_brain
from .services.generation import intelligence_in_force


class SnapshotValidityTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.workspace = self.make_workspace('Snapshot', 'snapshot-validity')
        self.user, self.client = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'snapshot-admin',
        )
        self.headers = workspace_header(self.workspace)
        self.brand = Brand.objects.create(workspace=self.workspace, name='Snapshot brand')
        self.source = BrandSource.objects.create(
            workspace=self.workspace, brand=self.brand, title='Evidence', status='READY',
        )
        self.memory = BrandMemory.objects.create(
            workspace=self.workspace, brand=self.brand, source=self.source,
            memory_type='PRODUCT_TRUTH', status='CONFIRMED', content='Limited offer',
            normalized_key='FACT/offer',
        )
        self.at = timezone.now()

    def compile_at(self, when):
        with patch('apps.brands.services.brand_brain.timezone.now', return_value=when):
            return rebuild_brand_brain(self.brand)

    def context_at(self, when):
        with patch('apps.brands.services.brand_brain.timezone.now', return_value=when):
            return build_generation_context(self.workspace, self.brand)

    def test_expiry_invalidates_an_already_warm_context_at_exact_boundary(self):
        boundary = self.at + timedelta(minutes=1)
        self.memory.valid_until = boundary
        self.memory.save(update_fields=['valid_until'])
        saved = self.compile_at(self.at)
        before = self.context_at(boundary - timedelta(microseconds=1))
        self.assertIn('Limited offer', before['verified_truth'])
        after = self.context_at(boundary)
        self.assertNotIn('Limited offer', after['verified_truth'])
        self.assertNotEqual(before['brain_version'], after['brain_version'])
        self.assertEqual(Brand.objects.get(pk=self.brand.pk).creative_brain, saved)

    def test_future_fact_enters_at_exact_start_without_a_write_or_manual_rebuild(self):
        boundary = self.at + timedelta(minutes=1)
        self.memory.valid_from = boundary
        self.memory.save(update_fields=['valid_from'])
        saved = self.compile_at(self.at)
        before = self.context_at(boundary - timedelta(microseconds=1))
        self.assertNotIn('Limited offer', before['verified_truth'])
        after = self.context_at(boundary)
        self.assertIn('Limited offer', after['verified_truth'])
        self.assertNotEqual(before['brain_version'], after['brain_version'])
        self.assertEqual(Brand.objects.get(pk=self.brand.pk).creative_brain, saved)

    def test_legacy_snapshot_cannot_carry_already_expired_or_future_facts(self):
        self.compile_at(self.at)
        for dates in (
            {'valid_until': self.at - timedelta(days=1), 'valid_from': None},
            {'valid_until': None, 'valid_from': self.at + timedelta(days=1)},
        ):
            with self.subTest(dates=dates):
                BrandMemory.objects.filter(pk=self.memory.pk).update(**dates)
                self.brand.refresh_from_db()
                self.assertNotIn('Limited offer', self.context_at(self.at)['verified_truth'])

    def test_source_revoke_with_failed_rebuild_cannot_reuse_warm_context(self):
        saved = self.compile_at(self.at)
        self.context_at(self.at)
        with patch('apps.brands.services.brand_brain.compile_brand_brain', side_effect=RuntimeError('test compile failure')):
            response = self.client.post(
                f'/api/marketing/knowledge/sources/{self.source.pk}/revoke/', **self.headers,
            )
        self.assertEqual(response.status_code, 200)
        current = Brand.objects.get(pk=self.brand.pk)
        self.assertTrue(current.brain_last_error)
        self.assertEqual(current.creative_brain, saved)
        # This instance predates the failure; freshness must not trust its flag.
        self.assertFalse(self.brand.brain_last_error)
        context = self.context_at(self.at)
        self.assertNotIn('Limited offer', context['verified_truth'])

    def test_confirmed_edit_with_failed_rebuild_withdraws_old_context(self):
        self.compile_at(self.at)
        self.context_at(self.at)
        with patch('apps.brands.services.brand_brain.compile_brand_brain', side_effect=RuntimeError('test compile failure')):
            response = self.client.patch(
                f'/api/marketing/knowledge/memories/{self.memory.pk}/',
                {'content': 'Unconfirmed replacement'}, format='json', **self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.memory.refresh_from_db()
        self.assertEqual(self.memory.status, 'CANDIDATE')
        context = self.context_at(self.at)
        self.assertNotIn('Limited offer', context['verified_truth'])
        self.assertNotIn('Unconfirmed replacement', context['verified_truth'])

    def test_failed_resolution_fails_closed_even_when_old_cut_is_cached(self):
        self.compile_at(self.at)
        self.context_at(self.at)
        Brand.objects.filter(pk=self.brand.pk).update(brain_last_error='private failure')
        with patch('apps.context.services.context_gateway.compile_brand_brain', side_effect=RuntimeError('private failure')):
            with self.assertRaises(ContextError) as caught:
                self.context_at(self.at)
        self.assertNotIn('private failure', str(caught.exception))

    def test_persisted_failure_forces_refresh_even_when_memory_ids_are_unchanged(self):
        retired = BrandRule.objects.create(
            workspace=self.workspace, brand=self.brand, text='Old rule', hardness='HARD',
        )
        kept = BrandRule.objects.create(
            workspace=self.workspace, brand=self.brand, text='Still active', hardness='HARD',
        )
        saved = self.compile_at(self.at)
        self.context_at(self.at)
        BrandRule.objects.filter(pk=retired.pk).update(is_active=False)
        Brand.objects.filter(pk=self.brand.pk).update(brain_last_error='compile failed')
        context = self.context_at(self.at)
        self.assertEqual([row['text'] for row in context['hard_rules']], ['Still active'])
        self.assertEqual(intelligence_in_force(self.brand, context['brain_version'])['rule_ids'], [str(kept.pk)])
        self.assertEqual(Brand.objects.get(pk=self.brand.pk).creative_brain, saved)

    def test_universal_precedence_uses_the_newly_resolved_snapshot(self):
        boundary = self.at + timedelta(minutes=1)
        self.memory.valid_from = boundary
        self.memory.save(update_fields=['valid_from'])
        standard = UniversalStandard.objects.create(
            title='Generic offer', category='FACT', attribute='offer', value='Generic',
            guidance='Use generic guidance', status=LifecycleStatus.PUBLISHED,
        )
        self.compile_at(self.at)
        before = self.context_at(self.at)
        self.assertEqual([row['standard_id'] for row in before['universal_standards']], [str(standard.pk)])
        after = self.context_at(boundary)
        self.assertEqual(after['universal_standards'], [])
        self.assertIn('Limited offer', after['verified_truth'])

    def test_foreign_temporal_changes_do_not_refresh_or_leak_into_local_context(self):
        self.compile_at(self.at)
        foreign_workspace = self.make_workspace('Foreign', 'snapshot-foreign')
        for workspace in (self.workspace, foreign_workspace):
            other = Brand.objects.create(workspace=workspace, name='Other brand')
            BrandMemory.objects.create(
                workspace=workspace, brand=other, memory_type='PRODUCT_TRUTH',
                status='CONFIRMED', content='Foreign fact', valid_from=self.at,
            )
        with patch('apps.context.services.context_gateway.compile_brand_brain', wraps=compile_brand_brain) as compiler:
            context = self.context_at(self.at)
            compiler.assert_not_called()
        self.assertNotIn('Foreign fact', str(context))
        with self.assertRaises(ContextError):
            build_generation_context(foreign_workspace, self.brand)

    def test_current_snapshot_check_is_fixed_query_and_never_recompiles(self):
        BrandMemory.objects.bulk_create([
            BrandMemory(
                workspace=self.workspace, brand=self.brand, memory_type='FACT',
                status='CONFIRMED', content=f'Fact {index}',
            ) for index in range(50)
        ])
        self.compile_at(self.at)
        with self.assertNumQueries(2):
            self.assertFalse(brain_snapshot_needs_refresh(self.brand, self.brand.creative_brain))
        with patch('apps.context.services.context_gateway.compile_brand_brain') as compiler:
            self.context_at(self.at)
            compiler.assert_not_called()

    def test_stale_read_is_pure_and_preserves_saved_brain_contract(self):
        saved = self.compile_at(self.at)
        BrandMemory.objects.filter(pk=self.memory.pk).update(valid_until=self.at)
        with CaptureQueriesContext(connection) as captured:
            current = resolved_brain(self.brand)
        writes = [query['sql'] for query in captured if query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
        self.assertEqual(writes, [])
        self.assertEqual(set(current), set(saved))
        self.assertNotIn('Limited offer', current['verified_product_truth'])
        self.assertEqual(self.brand.creative_brain, saved)
        self.assertEqual(Brand.objects.get(pk=self.brand.pk).creative_brain, saved)
