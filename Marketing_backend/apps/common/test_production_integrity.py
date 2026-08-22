"""
The production integrity gate must pass on a healthy schema and fail loudly
when the physical schema is not what the models expect.
"""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from apps.common.management.commands.production_integrity import (
    CRITICAL_MODELS,
    schema_gaps,
    unapplied_migrations,
)


class ProductionIntegrityTests(TestCase):
    def test_gate_passes_on_migrated_test_database(self):
        out = StringIO()
        # Not strict: the test database is SQLite by design (settings.py).
        call_command('production_integrity', stdout=out)
        self.assertIn('Production integrity OK', out.getvalue())
        self.assertIn('critical tables and columns', out.getvalue())

    def test_no_unapplied_migrations_on_test_database(self):
        self.assertEqual(unapplied_migrations(connection), [])

    def test_every_critical_model_is_physically_present(self):
        self.assertEqual(schema_gaps(connection), [])
        # The gate is only as good as its list: every intelligence table the
        # PR0-PR6 flows write must be on it.
        for label in (
            'knowledge.BrandSource', 'inspirations.InspirationSignal',
            'learning.LearningEvent', 'onboarding.CalibrationDirection',
        ):
            self.assertIn(label, CRITICAL_MODELS)

    def test_missing_table_is_detected(self):
        # The introspection layer is what the gate trusts; make it report a
        # database with no tables and the gate must say so for every model.
        with mock.patch.object(connection.introspection, 'table_names', return_value=[]):
            gaps = schema_gaps(connection, model_labels=('knowledge.BrandSource',))
        self.assertEqual(len(gaps), 1)
        self.assertIn('table missing: knowledge_brandsource', gaps[0])

    def test_missing_column_is_detected(self):
        real = connection.introspection.get_table_description

        def without_status(cursor, table_name):
            rows = real(cursor, table_name)
            return [row for row in rows if row.name != 'status']

        with mock.patch.object(
            connection.introspection, 'get_table_description', side_effect=without_status
        ):
            gaps = schema_gaps(connection, model_labels=('knowledge.BrandSource',))
        self.assertEqual(gaps, ['column missing: knowledge_brandsource.status (knowledge.BrandSource)'])

    def test_gate_fails_when_schema_has_gaps(self):
        with mock.patch.object(connection.introspection, 'table_names', return_value=[]):
            with self.assertRaises(CommandError) as caught:
                call_command('production_integrity', stdout=StringIO())
        self.assertIn('critical tables and columns', str(caught.exception))

    def test_strict_mode_rejects_sqlite(self):
        with self.assertRaises(CommandError) as caught:
            call_command('production_integrity', '--strict', stdout=StringIO())
        self.assertIn('sqlite is not a production database', str(caught.exception))
