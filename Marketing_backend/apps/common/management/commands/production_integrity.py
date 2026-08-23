"""
Production integrity gate.

    manage.py production_integrity

Runs after `migrate` in the deploy build and exits non-zero when the
environment the code is about to serve from is not the one it expects:

* the database is reachable;
* the engine is PostgreSQL (SQLite in production is a silent data-loss
  configuration, see settings.DATABASES);
* every migration is applied;
* every table and column the PR0-PR6 product flows depend on physically
  exists - a migration FILE existing is not evidence that the schema does;
* Django's system checks (including the security checks in
  apps.common.checks) report no errors;
* the non-secret configuration the product needs is present.

Deliberately cheap: a dozen metadata queries and no data reads. It is a gate,
not a regression suite - the suite proves the code, this proves the
environment.
"""
import sys

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, SystemCheckError
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor

#: app_label.ModelName for every table a user-facing PR0-PR6 flow touches.
#: Checked column by column against the model, so a partially applied or
#: hand-edited schema fails here instead of as a 500 on the first request.
CRITICAL_MODELS = (
    'workspaces.MarketingWorkspace',
    'workspaces.WorkspaceMember',
    'brands.Brand',
    'knowledge.BrandSource',
    'knowledge.BrandMemory',
    'inspirations.BrandInspiration',
    'inspirations.InspirationSignal',
    'learning.LearningEvent',
    'learning.BrandPreference',
    'learning.BrandRule',
    'onboarding.BrandOnboarding',
    'onboarding.CalibrationDirection',
    'content.ContentItem',
    'feedback.Feedback',
    'ai.AIProvider',
    'ai.WorkspaceAIProvider',
    'ai.WorkspaceAIRoute',
    'ai.AIUsageLog',
    'social_accounts.SocialConnection',
    'publishing.PublishingJob',
    'publishing.PublishingJobItem',
    # Added with the approval / console work: a deploy where these are
    # missing serves 500s on signup and on every platform endpoint.
    'billing.Plan',
    'billing.Subscription',
    'audit.PlatformAdmin',
    'audit.PlatformAuditLog',
    'universal.UniversalStandard',
    'universal.PlatformInspiration',
)

#: Non-secret settings production cannot run without. Values are never
#: printed - only presence is reported.
REQUIRED_PRODUCTION_SETTINGS = (
    ('CORS_ALLOWED_ORIGINS', 'the frontend origin allowlist'),
    ('SUPABASE_URL', 'file storage for knowledge, inspiration and logo uploads'),
    ('SUPABASE_SERVICE_ROLE_KEY', 'file storage credentials'),
)


def running_tests():
    return 'test' in sys.argv or 'pytest' in sys.modules


def schema_gaps(connection, model_labels=CRITICAL_MODELS):
    """Tables and columns the models expect that the live database lacks."""
    gaps = []
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
        for label in model_labels:
            try:
                model = apps.get_model(label)
            except LookupError:
                gaps.append("model not installed: %s" % label)
                continue
            table = model._meta.db_table
            if table not in tables:
                gaps.append("table missing: %s (%s)" % (table, label))
                continue
            columns = {
                column.name
                for column in connection.introspection.get_table_description(cursor, table)
            }
            for field in model._meta.local_concrete_fields:
                if field.column not in columns:
                    gaps.append(
                        "column missing: %s.%s (%s)" % (table, field.column, label)
                    )
    return gaps


def unapplied_migrations(connection):
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return ["%s.%s" % (migration.app_label, migration.name) for migration, _back in plan]


class Command(BaseCommand):
    help = "Verifies the live environment matches what the code expects. Exits 1 on failure."

    def add_arguments(self, parser):
        parser.add_argument(
            '--database', default=DEFAULT_DB_ALIAS,
            help="Database alias to verify (default: default).",
        )
        parser.add_argument(
            '--allow-sqlite', action='store_true',
            help="Accept a SQLite engine (local or throwaway environments only).",
        )
        parser.add_argument(
            '--strict', action='store_true',
            help=(
                "Apply the production-only checks (engine, required settings) "
                "even under DEBUG. They are always applied when DEBUG is off."
            ),
        )

    def handle(self, *args, **options):
        connection = connections[options['database']]
        strict = options['strict'] or (not settings.DEBUG and not running_tests())
        failures = []

        def report(name, ok, detail=""):
            mark = self.style.SUCCESS('OK  ') if ok else self.style.ERROR('FAIL')
            line = "%s %s" % (mark, name)
            if detail:
                line += " - %s" % detail
            self.stdout.write(line)
            if not ok:
                failures.append("%s: %s" % (name, detail) if detail else name)

        # 1. Connectivity. Nothing else can be checked without it.
        try:
            connection.ensure_connection()
            report('database connection', True, connection.vendor)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            report('database connection', False, str(exc)[:200])
            raise CommandError("Production integrity FAILED: " + "; ".join(failures))

        # 2. Engine.
        if connection.vendor == 'sqlite' and not options['allow_sqlite'] and strict:
            report('database engine', False, 'sqlite is not a production database')
        else:
            report('database engine', True, connection.vendor)

        # 3. Migrations.
        pending = unapplied_migrations(connection)
        report(
            'migrations applied', not pending,
            ("%d unapplied: %s" % (len(pending), ", ".join(pending[:8])))
            if pending else 'none pending',
        )

        # 4. Physical schema.
        gaps = schema_gaps(connection)
        report(
            'critical tables and columns', not gaps,
            "; ".join(gaps[:10]) if gaps else "%d models verified" % len(CRITICAL_MODELS),
        )

        # 5. System checks (security checks are registered in apps.common.checks).
        try:
            call_command('check', verbosity=0)
            report('django system checks', True)
        except SystemCheckError as exc:
            report('django system checks', False, str(exc).strip().splitlines()[-1][:200])

        # 6. Required non-secret configuration.
        if strict:
            for name, why in REQUIRED_PRODUCTION_SETTINGS:
                present = bool(getattr(settings, name, None))
                report(
                    "setting %s" % name, present,
                    'present' if present else "missing - %s" % why,
                )
        else:
            self.stdout.write("skip production-only configuration checks (DEBUG or tests)")

        if failures:
            raise CommandError(
                "Production integrity FAILED (%d): %s" % (len(failures), "; ".join(failures))
            )
        self.stdout.write(self.style.SUCCESS("Production integrity OK"))
