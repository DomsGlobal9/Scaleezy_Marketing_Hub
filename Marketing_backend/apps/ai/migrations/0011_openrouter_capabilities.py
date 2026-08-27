"""Update OpenRouter and Together AI capabilities in catalogue to include Image, Vision, and Embedding."""
from django.db import migrations


def update_capabilities(apps, schema_editor):
    AIProvider = apps.get_model('ai', 'AIProvider')
    capabilities = ['TEXT', 'IMAGE', 'IMAGE_ANALYSIS', 'IMAGE_CAPTION', 'EMBEDDING']
    AIProvider.objects.filter(key__in=['openrouter', 'together']).update(capabilities=capabilities)


def revert_capabilities(apps, schema_editor):
    AIProvider = apps.get_model('ai', 'AIProvider')
    AIProvider.objects.filter(key__in=['openrouter', 'together']).update(capabilities=['TEXT'])


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0010_alter_workspaceairoute_unique_together_and_more'),
    ]

    operations = [
        migrations.RunPython(update_capabilities, revert_capabilities),
    ]
