from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('ai', '0007_seed_openai_compatible_providers'),
        ('workspaces', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiprovider',
            name='base_url',
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name='aiprovider',
            name='integration_type',
            field=models.CharField(
                choices=[
                    ('INSTALLED', 'Installed adapter'),
                    ('OPENAI_COMPATIBLE', 'Custom OpenAI-compatible endpoint'),
                    ('SCALEEZY_JSON', 'Scaleezy universal JSON endpoint'),
                ],
                default='INSTALLED',
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='aiprovider',
            name='owner_workspace',
            field=models.ForeignKey(
                blank=True,
                help_text='Null for platform integrations; set for a tenant-owned custom endpoint.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='custom_ai_providers',
                to='workspaces.marketingworkspace',
            ),
        ),
    ]
