"""
Brand Brain compile health.

Four nullable/blank columns, no backfill. An existing brand reads as "never
recorded a compile" until its next rebuild, which is accurate — before this
migration nothing recorded one.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0003_brand_signup_approval'),
    ]

    operations = [
        migrations.AddField(
            model_name='brand',
            name='brain_compiled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='brand',
            name='brain_version',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='brand',
            name='brain_last_error',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='brand',
            name='brain_failed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
