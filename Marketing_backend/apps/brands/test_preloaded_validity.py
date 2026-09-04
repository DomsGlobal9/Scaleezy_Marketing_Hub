"""The approved validity rule also applies to preloaded Platform snapshots."""
from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.common.testing import TenantFixtureMixin
from apps.context.services.readiness import score_brand_readiness
from apps.knowledge.models import BrandMemory, BrandSource
from apps.platform.views_clients import PortfolioStats, client_row

from .models import Brand
from .services.brand_brain import compile_brand_brain, compile_brand_brain_from_records


class PreloadedMemoryValidityTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.at = datetime(2026, 9, 4, 12, 0, tzinfo=datetime_timezone.utc)
        self.workspace = self.make_workspace('Validity client', 'preloaded-validity')
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Default brand', is_default=True,
            status=Brand.Status.ACTIVE,
        )
        self.source = BrandSource.objects.create(
            workspace=self.workspace, brand=self.brand, title='Retained source',
            status=BrandSource.SourceStatus.READY, raw_text='Original source evidence',
        )

    def memory(self, content, **kwargs):
        return BrandMemory.objects.create(
            workspace=self.workspace, brand=self.brand, source=self.source,
            status=BrandMemory.MemoryStatus.CONFIRMED, content=content,
            **{'memory_type': BrandMemory.MemoryType.PRODUCT_TRUTH, **kwargs},
        )

    def cases(self):
        before = self.at - timedelta(microseconds=1)
        after = self.at + timedelta(microseconds=1)
        return [
            (self.memory('No bounds'), True),
            (self.memory('Start bound only', valid_from=before), True),
            (self.memory('End bound only', valid_until=after), True),
            (self.memory('Inside window', valid_from=before, valid_until=after), True),
            (self.memory('Start inclusive', valid_from=self.at, valid_until=after), True),
            (self.memory('End exclusive', valid_from=before, valid_until=self.at), False),
            (self.memory('Future', valid_from=after), False),
            (self.memory('Expired', valid_until=before), False),
        ]

    def preloaded(self, memories):
        return compile_brand_brain_from_records(
            self.brand, memories=memories, rules=[], preferences=[], signals=[],
        )

    def test_preloaded_null_current_and_exact_time_boundaries(self):
        cases = self.cases()
        with patch('apps.brands.services.brand_brain.timezone.now', return_value=self.at):
            for memory, eligible in cases:
                with self.subTest(content=memory.content):
                    brain = self.preloaded([memory])
                    self.assertEqual(
                        brain['verified_product_truth'], [memory.content] if eligible else [],
                    )
                    self.assertEqual(
                        brain['sources']['memory_ids'], [str(memory.pk)] if eligible else [],
                    )

    def test_ordinary_and_preloaded_fingerprints_match_at_frozen_time(self):
        rows = [memory for memory, _eligible in self.cases()]
        with patch('apps.brands.services.brand_brain.timezone.now', return_value=self.at):
            ordinary = compile_brand_brain(self.brand)
            preloaded = self.preloaded(rows)
        self.assertEqual(preloaded['brain_version'], ordinary['brain_version'])
        self.assertEqual(preloaded, ordinary)

    def test_generator_input_and_order_preserve_the_same_eligible_fingerprint(self):
        rows = [memory for memory, _eligible in self.cases()]
        with patch('apps.brands.services.brand_brain.timezone.now', return_value=self.at):
            ordinary = compile_brand_brain(self.brand)
            preloaded = self.preloaded(memory for memory in reversed(rows))
        self.assertEqual(preloaded, ordinary)

    def test_compilation_is_read_only_and_retains_all_source_records(self):
        rows = [memory for memory, _eligible in self.cases()]
        memory_before = list(BrandMemory.objects.filter(brand=self.brand).order_by('pk').values())
        source_before = BrandSource.objects.filter(pk=self.source.pk).values().get()
        with patch('apps.brands.services.brand_brain.timezone.now', return_value=self.at):
            with self.assertNumQueries(0):
                self.preloaded(rows)
        self.assertEqual(
            list(BrandMemory.objects.filter(brand=self.brand).order_by('pk').values()),
            memory_before,
        )
        self.assertEqual(BrandSource.objects.filter(pk=self.source.pk).values().get(), source_before)
        self.brand.refresh_from_db()
        self.assertFalse(self.brand.creative_brain)
        self.assertIsNone(self.brand.brain_compiled_at)

    def test_platform_missing_snapshot_and_readiness_use_the_filtered_preload(self):
        self.memory('Current fact')
        self.memory(
            'Expired positioning', memory_type=BrandMemory.MemoryType.POSITIONING_SIGNAL,
            valid_until=self.at,
        )
        self.memory(
            'Future pain', memory_type=BrandMemory.MemoryType.BUYER_PAIN,
            valid_from=self.at + timedelta(microseconds=1),
        )
        with patch('apps.brands.services.brand_brain.timezone.now', return_value=self.at):
            with CaptureQueriesContext(connection) as captured:
                stats = PortfolioStats([self.workspace.pk])
                row = client_row(self.workspace, stats)
            ordinary = compile_brand_brain(self.brand)
        writes = [
            query['sql'] for query in captured
            if query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
        ]
        self.assertEqual(writes, [])
        self.assertEqual(stats.brains[self.brand.pk], ordinary)
        self.assertEqual(stats.brains[self.brand.pk]['positioning']['statements'], [])
        self.assertEqual(stats.brains[self.brand.pk]['audiences']['pains'], [])
        expected = score_brand_readiness(
            self.brand, stats.readiness[self.brand.pk], brain=ordinary,
        )
        self.assertEqual(row['readiness'], {
            'score': expected['readiness_score'], 'level': expected['readiness_level'],
        })
        self.brand.refresh_from_db()
        self.assertFalse(self.brand.creative_brain)
        self.assertIsNone(self.brand.brain_compiled_at)
        self.assertEqual(BrandMemory.objects.filter(brand=self.brand).count(), 3)

    def test_platform_preload_does_not_mix_sibling_or_foreign_brand_sources(self):
        own = self.memory('Local fact', valid_from=self.at)
        foreign_workspace = self.make_workspace('Foreign client', 'preloaded-foreign')
        for workspace in (self.workspace, foreign_workspace):
            other = Brand.objects.create(workspace=workspace, name='Other brand')
            BrandMemory.objects.create(
                workspace=workspace, brand=other, memory_type='PRODUCT_TRUTH',
                status='CONFIRMED', content='Other brand fact', valid_from=self.at,
            )
        with patch('apps.brands.services.brand_brain.timezone.now', return_value=self.at):
            stats = PortfolioStats([self.workspace.pk])
        self.assertEqual(set(stats.brains), {self.brand.pk})
        self.assertEqual(stats.brains[self.brand.pk]['verified_product_truth'], ['Local fact'])
        self.assertEqual(stats.brains[self.brand.pk]['sources']['memory_ids'], [str(own.pk)])
