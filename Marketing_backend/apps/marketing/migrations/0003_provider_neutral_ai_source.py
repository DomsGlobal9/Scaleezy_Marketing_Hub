from django.db import migrations, models


def migrate_source(apps, schema_editor):
    apps.get_model('marketing', 'MarketingAsset').objects.filter(
        source='GEMINI_GENERATED'
    ).update(source='AI_GENERATED')


class Migration(migrations.Migration):
    dependencies = [('marketing', '0002_alter_marketingasset_source')]

    operations = [
        migrations.AlterField(
            model_name='marketingasset',
            name='generation_id',
            field=models.CharField(
                blank=True,
                help_text='Reference to the provider-neutral generation result, if applicable',
                max_length=255,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='marketingasset',
            name='source',
            field=models.CharField(
                choices=[
                    ('AI_GENERATED', 'AI generated'),
                    ('GEMINI_GENERATED', 'Legacy AI generated'),
                    ('MANUAL_UPLOAD', 'Manual Upload'),
                    ('COMPOSED', 'Composed from brand'),
                ],
                max_length=50,
            ),
        ),
        migrations.RunPython(migrate_source, migrations.RunPython.noop),
    ]
