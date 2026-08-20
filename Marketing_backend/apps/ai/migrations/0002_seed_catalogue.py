"""
Seeds the provider catalogue from the installed adapters, and routes every
existing workspace to Gemini so generation keeps working unchanged.

Idempotent: re-running only fills gaps.
"""
from django.db import migrations


def seed(apps, schema_editor):
    AIProvider = apps.get_model('ai', 'AIProvider')
    WorkspaceAIProvider = apps.get_model('ai', 'WorkspaceAIProvider')
    WorkspaceAIRoute = apps.get_model('ai', 'WorkspaceAIRoute')
    MarketingWorkspace = apps.get_model('workspaces', 'MarketingWorkspace')

    from apps.ai.registry import all_adapters

    for key, adapter in all_adapters().items():
        AIProvider.objects.update_or_create(
            key=key,
            defaults={
                'display_name': adapter.display_name or key.title(),
                'capabilities': list(adapter.capabilities),
                'default_model': adapter.default_model,
                'unit_cost': adapter.unit_cost,
                'is_available': True,
            },
        )

    gemini = AIProvider.objects.filter(key='gemini').first()
    if not gemini:
        return

    # Existing workspaces already generate with Gemini; preserve that so the
    # router is a no-op change for them rather than a break.
    for workspace in MarketingWorkspace.objects.all():
        WorkspaceAIProvider.objects.get_or_create(
            workspace=workspace, provider=gemini, defaults={'enabled': True},
        )
        for capability in gemini.capabilities:
            WorkspaceAIRoute.objects.get_or_create(
                workspace=workspace,
                capability=capability,
                provider=gemini,
                defaults={'priority': 10, 'enabled': True, 'strategy': 'FAILOVER'},
            )


def unseed(apps, schema_editor):
    apps.get_model('ai', 'AIProvider').objects.filter(key='gemini').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('ai', '0001_initial'),
        ('workspaces', '0002_workspacemember'),
    ]

    operations = [migrations.RunPython(seed, unseed)]
