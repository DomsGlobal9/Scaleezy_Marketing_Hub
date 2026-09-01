# The shared cache's table, created where it cannot be skipped.
#
# PR #8 moved Django's cache from per-process memory to the database — that is
# what fixed OAuth callbacks landing on a worker that had never seen the state.
# The table itself was created by `manage.py createcachetable` in render.yaml's
# build command. But render.yaml only governs services created FROM the
# blueprint; the production services were created by hand in the dashboard, so
# the file's build command never ran, the code deployed anyway, and every
# cache operation raised ProgrammingError: relation "scaleezy_cache" does not
# exist. Signup 500'd on its throttle, OAuth 500'd on its state write — and
# the context gateway reads the cache on every generation, so generation
# itself was down. The test suite could not catch it: tests run on LocMemCache
# precisely so they need no table.
#
# A migration is the one place guaranteed to run on every deploy path —
# dashboard-managed, blueprint-managed, or a laptop — because `migrate` is in
# every build. `createcachetable` is idempotent: it skips tables that already
# exist and does nothing for non-database cache backends, so this is safe
# everywhere, including under test.
from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command('createcachetable', database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
