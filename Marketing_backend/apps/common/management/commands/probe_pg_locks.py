"""
Executes every row-locking query shape in the codebase against the connected
database and rolls back.

Why this exists: PostgreSQL refuses FOR UPDATE on the nullable side of an
outer join (NotSupportedError), but SQLite ignores row locks entirely — so a
select_for_update() applied to a queryset that select_relates or filters
through a nullable FK passes the whole test suite and then fails every
matching request in production. This class of bug shipped three times
(autopilot execute_run, create-from-inspiration save, engagement claim)
before this probe existed.

Run against a real PostgreSQL database — production is safe: each probe
targets a random UUID that matches nothing, takes no locks that survive the
statement, and every transaction is rolled back.

    python manage.py probe_pg_locks

Exit code is non-zero if any probe fails, so it can gate a deploy.
"""
import uuid

from django.core.management.base import BaseCommand
from django.db import connection, transaction


def _probes():
    """One (label, callable) per locking site. Labels name the source."""
    from apps.autopilot.models import AutopilotPolicy, AutopilotRun
    from apps.engagement.views import EngagementItemViewSet
    from apps.gemini.models import GeminiGenerationRequest
    from apps.inspirations.models import BrandInspiration, ResearchFinding
    from apps.jobs.models import TaskRun
    from apps.knowledge.models import BrandSource
    from apps.publishing.models import PublishingJob
    from apps.workspaces.models import MarketingWorkspace
    from apps.brands.models import Brand
    from apps.ai.models import AIProvider, WorkspaceAIRoute

    missing = uuid.uuid4()

    return [
        # apps/autopilot/services.py execute_run
        ('autopilot.execute_run', lambda: AutopilotRun.objects.select_for_update(
            of=('self',)
        ).select_related(
            'workspace', 'policy__brand', 'policy__created_by', 'generation_request'
        ).filter(pk=missing).first()),
        # apps/autopilot/services.py emergency_stop
        ('autopilot.emergency_stop', lambda: AutopilotPolicy.objects.select_for_update(
        ).filter(pk=missing).first()),
        # apps/gemini/tasks.py generate_content locked save block
        ('gemini.locked_workspace', lambda: MarketingWorkspace.objects.select_for_update(
        ).filter(pk=missing).first()),
        ('gemini.locked_brand', lambda: Brand.objects.select_for_update(
        ).filter(pk=missing).first()),
        # Calls the real helper so the probe tracks the code, not a copy: it
        # executes the inspiration lock (join-free by design) and returns
        # early on the count mismatch.
        ('gemini.locked_references', lambda: __import__(
            'apps.gemini.tasks', fromlist=['_lock_generation_references']
        )._lock_generation_references(
            reference_ids=[missing], workspace=None, brand=None
        )),
        # apps/inspirations/research.py adopt_finding
        ('research.adopt_finding', lambda: ResearchFinding.objects.select_for_update(
            of=('self',)
        ).select_related(
            'run', 'workspace', 'brand', 'adopted_inspiration'
        ).filter(pk=missing).first()),
        # apps/inspirations/analysis.py analyze_inspiration (both locks)
        ('inspirations.analyze_claim', lambda: BrandInspiration.objects.select_for_update(
        ).select_related('workspace', 'brand').filter(pk=missing).first()),
        # apps/engagement/views.py claim/approve — reuses the viewset's real
        # class queryset so the probe tracks the code, not a copy of it.
        ('engagement.claim', lambda: EngagementItemViewSet.queryset.select_for_update(
            of=('self',)
        ).filter(pk=missing).first()),
        # apps/jobs/runner.py claim
        ('jobs.claim', lambda: TaskRun.objects.filter(pk=missing).select_for_update(
            skip_locked=connection.features.has_select_for_update_skip_locked
        ).first()),
        # apps/publishing/scheduler.py enqueue_due_jobs
        ('publishing.scheduler_claim', lambda: PublishingJob.objects.select_for_update(
        ).filter(pk=missing).first()),
        # apps/knowledge/processing.py
        ('knowledge.process_claim', lambda: BrandSource.objects.select_for_update(
        ).filter(pk=missing).first()),
        # apps/ai/views.py route replace + apps/ai/catalogue.py
        ('ai.route_replace', lambda: list(WorkspaceAIRoute.objects.select_for_update(
        ).filter(pk=missing))),
        ('ai.catalogue_refresh', lambda: AIProvider.objects.select_for_update(
        ).filter(key='__probe__').first()),
        # apps/gemini polling/claim paths lock the request row directly
        ('gemini.request_claim', lambda: GeminiGenerationRequest.objects.select_for_update(
        ).filter(pk=missing).first()),
        # apps/content/views.py pick_twin — both halves of an A/B pair,
        # join-free by design.
        ('content.pick_twin', lambda: list(__import__(
            'apps.content.models', fromlist=['ContentItem']
        ).ContentItem.objects.select_for_update().filter(
            layout_config__ab_group=str(missing)
        ))),
    ]


class Command(BaseCommand):
    help = 'Execute every FOR UPDATE query shape against this database, rolled back.'

    def handle(self, *args, **options):
        failures = 0
        self.stdout.write(f'Probing on {connection.vendor}')
        for label, probe in _probes():
            try:
                with transaction.atomic():
                    probe()
                    transaction.set_rollback(True)
                self.stdout.write(f'  OK    {label}')
            except Exception as exc:
                failures += 1
                self.stderr.write(f'  FAIL  {label}: {type(exc).__name__}: {exc}')
        total = len(_probes())
        if failures:
            self.stderr.write(f'{failures}/{total} locking sites failed on {connection.vendor}.')
            raise SystemExit(1)
        self.stdout.write(f'All {total} locking sites execute cleanly on {connection.vendor}.')
