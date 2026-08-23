"""
Per-capability ceilings.

Both columns default to an empty dict, which means "no per-capability limit" —
so every existing plan and subscription behaves exactly as it did, metered by
`monthly_generations` and `monthly_spend_cap` alone.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_seed_plans'),
    ]

    operations = [
        migrations.AddField(
            model_name='plan',
            name='capability_limits',
            field=models.JSONField(
                blank=True, default=dict,
                help_text=(
                    'Per-capability ceilings, e.g. {"IMAGE": 100, "VIDEO": 10}. '
                    'Absent or 0 = unlimited.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='subscription',
            name='capability_limit_overrides',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
