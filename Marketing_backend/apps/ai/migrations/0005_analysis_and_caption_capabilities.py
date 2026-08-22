from django.db import migrations, models


NEW_CAPABILITIES = ('IMAGE_CAPTION', 'VIDEO_ANALYSIS')


def refresh_catalogue_and_routes(apps, schema_editor):
    AIProvider = apps.get_model('ai', 'AIProvider')
    WorkspaceAIProvider = apps.get_model('ai', 'WorkspaceAIProvider')
    WorkspaceAIRoute = apps.get_model('ai', 'WorkspaceAIRoute')

    from apps.ai.registry import all_adapters

    adapters = all_adapters()
    for key, adapter in adapters.items():
        AIProvider.objects.filter(key=key).update(capabilities=list(adapter.capabilities))

    for wp in WorkspaceAIProvider.objects.filter(enabled=True).select_related('provider'):
        supported = set(wp.provider.capabilities or [])
        for capability in NEW_CAPABILITIES:
            if capability not in supported:
                continue
            next_priority = (
                WorkspaceAIRoute.objects.filter(
                    workspace_id=wp.workspace_id,
                    capability=capability,
                ).count()
                + 1
            ) * 10
            WorkspaceAIRoute.objects.get_or_create(
                workspace_id=wp.workspace_id,
                capability=capability,
                provider_id=wp.provider_id,
                defaults={
                    'priority': next_priority,
                    'enabled': True,
                    'strategy': 'FAILOVER',
                },
            )


def unroute(apps, schema_editor):
    apps.get_model('ai', 'WorkspaceAIRoute').objects.filter(
        capability__in=NEW_CAPABILITIES
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('ai', '0004_refresh_capabilities')]

    operations = [
        migrations.AlterField(
            model_name='aiusagelog',
            name='capability',
            field=models.CharField(
                choices=[
                    ('TEXT', 'Copy (headline, caption, hashtags)'),
                    ('IMAGE', 'Image generation'),
                    ('IMAGE_ANALYSIS', 'Image analysis'),
                    ('IMAGE_CAPTION', 'Image caption generation'),
                    ('VIDEO', 'Video generation'),
                    ('VIDEO_ANALYSIS', 'Video analysis'),
                    ('EMBEDDING', 'Text embedding (feedback similarity)'),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name='workspaceairoute',
            name='capability',
            field=models.CharField(
                choices=[
                    ('TEXT', 'Copy (headline, caption, hashtags)'),
                    ('IMAGE', 'Image generation'),
                    ('IMAGE_ANALYSIS', 'Image analysis'),
                    ('IMAGE_CAPTION', 'Image caption generation'),
                    ('VIDEO', 'Video generation'),
                    ('VIDEO_ANALYSIS', 'Video analysis'),
                    ('EMBEDDING', 'Text embedding (feedback similarity)'),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(refresh_catalogue_and_routes, unroute),
    ]
