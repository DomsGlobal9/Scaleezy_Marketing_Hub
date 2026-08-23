from django.db import migrations, models


def copy_provider_capabilities(apps, schema_editor):
    WorkspaceAIProvider = apps.get_model('ai', 'WorkspaceAIProvider')
    for configured in WorkspaceAIProvider.objects.select_related('provider').iterator():
        configured.capabilities = list(configured.provider.capabilities or [])
        configured.save(update_fields=['capabilities'])


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0008_custom_ai_provider_ownership'),
    ]

    operations = [
        migrations.AddField(
            model_name='workspaceaiprovider',
            name='capabilities',
            field=models.JSONField(
                blank=True,
                default=None,
                help_text=(
                    "Capabilities this workspace assigned to this provider/model. "
                    "Must remain within the installed adapter's technical support."
                ),
                null=True,
            ),
        ),
        migrations.RunPython(copy_provider_capabilities, migrations.RunPython.noop),
    ]
