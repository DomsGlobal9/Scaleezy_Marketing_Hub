"""
The lock probe must execute every registered locking shape cleanly. On SQLite
this cannot catch the FOR UPDATE class itself (row locks are ignored) — the
real assertion happens when the command runs against PostgreSQL after a
deploy — but this pins the wiring: every probe imports, builds, and executes.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.common.management.commands.probe_pg_locks import _probes


class ProbePgLocksTests(TestCase):
    def test_every_probe_executes_and_command_passes(self):
        out = StringIO()
        call_command('probe_pg_locks', stdout=out)
        text = out.getvalue()
        for label, _ in _probes():
            self.assertIn(label, text)
        self.assertIn('execute cleanly', text)

    def test_probe_registry_covers_known_sites(self):
        labels = {label for label, _ in _probes()}
        for expected in (
            'autopilot.execute_run', 'gemini.locked_references',
            'research.adopt_finding', 'engagement.claim', 'jobs.claim',
        ):
            self.assertIn(expected, labels)
