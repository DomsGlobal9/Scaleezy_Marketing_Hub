"""
Re-syncs the catalogue with the installed adapters, and routes the new
EMBEDDING capability.

Migration 0002 read the adapters as they were then, so a database already
migrated has a Gemini row that does not list EMBEDDING — and the router checks
`provider.supports(capability)` before dispatching, so the capability would be
invisible on exactly the installations that already exist. A fresh database
gets this from 0002 automatically; this brings the older ones level.

Embedding calls are cheap and only happen on a review action, so routing them
matches what a fresh install already does. A workspace that would rather not
pay for them can delete the route; feedback then falls back to the local
embedding, which is the default when nothing is routed.
"""
from django.db import migrations


def refresh(apps, schema_editor):
    AIProvider = apps.get_model('ai', 'AIProvider')
    WorkspaceAIProvider = apps.get_model('ai', 'WorkspaceAIProvider')
    WorkspaceAIRoute = apps.get_model('ai', 'WorkspaceAIRoute')

    from apps.ai.registry import all_adapters

    adapters = all_adapters()
    for key, adapter in adapters.items():
        AIProvider.objects.filter(key=key).update(capabilities=list(adapter.capabilities))

    for provider in AIProvider.objects.all():
        if 'EMBEDDING' not in (provider.capabilities or []):
            continue
        # Only workspaces that already use this provider — never switch a
        # customer onto a provider they have not enabled.
        for wp in WorkspaceAIProvider.objects.filter(provider=provider, enabled=True):
            WorkspaceAIRoute.objects.get_or_create(
                workspace_id=wp.workspace_id,
                capability='EMBEDDING',
                provider=provider,
                defaults={'priority': 10, 'enabled': True, 'strategy': 'FAILOVER'},
            )


def unroute(apps, schema_editor):
    apps.get_model('ai', 'WorkspaceAIRoute').objects.filter(capability='EMBEDDING').delete()


class Migration(migrations.Migration):
    dependencies = [('ai', '0003_alter_aiusagelog_capability_and_more')]

    operations = [migrations.RunPython(refresh, unroute)]
