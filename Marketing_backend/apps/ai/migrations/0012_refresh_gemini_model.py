from django.db import migrations


RETIRED_MODELS = ('gemini-1.5-pro', 'models/gemini-1.5-pro')
SUPPORTED_MODEL = 'gemini-2.5-flash'


def refresh_gemini_model(apps, schema_editor):
    AIProvider = apps.get_model('ai', 'AIProvider')
    WorkspaceAIProvider = apps.get_model('ai', 'WorkspaceAIProvider')

    gemini = AIProvider.objects.filter(key='gemini').first()
    if gemini is None:
        return

    gemini.default_model = SUPPORTED_MODEL
    gemini.save(update_fields=['default_model'])
    WorkspaceAIProvider.objects.filter(
        provider=gemini,
        model_override__in=RETIRED_MODELS,
    ).update(model_override=SUPPORTED_MODEL)


class Migration(migrations.Migration):
    dependencies = [('ai', '0011_default_round_robin_routing')]

    operations = [
        migrations.RunPython(refresh_gemini_model, migrations.RunPython.noop),
    ]
