"""Install the open-ended text-provider catalogue in every deployment.

The deploy command normally synchronises catalogue rows from installed
adapters.  Keeping this additive migration as well makes the provider list
independent of a hosting dashboard overriding that command.
"""
from decimal import Decimal

from django.db import migrations


PROVIDERS = (
    (
        'groq',
        'Groq',
        'openai/gpt-oss-20b',
        'https://console.groq.com/docs/overview',
    ),
    (
        'mistral',
        'Mistral AI',
        'mistral-small-latest',
        'https://docs.mistral.ai/',
    ),
    (
        'deepseek',
        'DeepSeek',
        'deepseek-v4-flash',
        'https://api-docs.deepseek.com/',
    ),
    (
        'openrouter',
        'OpenRouter',
        'openai/gpt-oss-20b',
        'https://openrouter.ai/docs/quickstart',
    ),
    (
        'together',
        'Together AI',
        'openai/gpt-oss-20b',
        'https://docs.together.ai/docs/quickstart',
    ),
)


def seed_openai_compatible_providers(apps, schema_editor):
    AIProvider = apps.get_model('ai', 'AIProvider')

    for key, display_name, default_model, docs_url in PROVIDERS:
        defaults = {
            'display_name': display_name,
            'capabilities': ['TEXT'],
            'default_model': default_model,
            'unit_cost': Decimal('0.0400'),
            'docs_url': docs_url,
        }
        provider, created = AIProvider.objects.get_or_create(
            key=key,
            defaults={**defaults, 'is_available': True},
        )
        if not created:
            # Metadata belongs to the installed adapter. Preserve the
            # operator-owned global availability kill switch.
            for field, value in defaults.items():
                setattr(provider, field, value)
            provider.save(update_fields=list(defaults))

    # Deliberately no workspace provider or routing writes. Tenants choose
    # which integrations to enable and may configure any number of them.


class Migration(migrations.Migration):
    dependencies = [('ai', '0006_seed_openai_provider')]

    operations = [
        # Reverse is non-destructive because workspace configuration may
        # reference catalogue rows after this migration is applied.
        migrations.RunPython(
            seed_openai_compatible_providers,
            migrations.RunPython.noop,
        ),
    ]
