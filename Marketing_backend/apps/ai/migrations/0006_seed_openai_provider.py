"""Install OpenAI in the global catalogue without opting in any tenant."""
from decimal import Decimal

from django.db import migrations


CAPABILITIES = (
    'TEXT',
    'IMAGE',
    'IMAGE_ANALYSIS',
    'IMAGE_CAPTION',
    'EMBEDDING',
)


def seed_openai_provider(apps, schema_editor):
    AIProvider = apps.get_model('ai', 'AIProvider')

    gemini_cost = (
        AIProvider.objects.filter(key='gemini')
        .values_list('unit_cost', flat=True)
        .first()
    )
    cost = max(
        Decimal('0.0300'),
        Decimal(str(gemini_cost or 0)) + Decimal('0.0100'),
    )
    defaults = {
        'display_name': 'OpenAI',
        'capabilities': list(CAPABILITIES),
        'default_model': 'gpt-4.1-mini',
        'unit_cost': cost,
        'docs_url': 'https://platform.openai.com/docs/overview',
    }
    provider, created = AIProvider.objects.get_or_create(
        key='openai',
        defaults={**defaults, 'is_available': True},
    )
    if not created:
        # Preserve an operator's global kill-switch choice if a catalogue row
        # was created before this migration reached the deployment.
        for field, value in defaults.items():
            setattr(provider, field, value)
        provider.save(update_fields=list(defaults))

    # Deliberately no WorkspaceAIProvider or WorkspaceAIRoute writes here.
    # Provider enablement and redundancy policy remain explicit admin actions.


class Migration(migrations.Migration):
    dependencies = [('ai', '0005_analysis_and_caption_capabilities')]

    operations = [
        # Reverse is intentionally non-destructive: deleting this catalogue
        # row would cascade any workspace configuration created after deploy.
        migrations.RunPython(seed_openai_provider, migrations.RunPython.noop),
    ]
