"""
Signup intake fields: the legal company name and the named contact person.

Both are plain blank CharFields backfilled with '' — safe as a single AddField
on Postgres (no index or uniqueness transition involved).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0005_alter_brand_layout_preference'),
    ]

    operations = [
        migrations.AddField(
            model_name='brand',
            name='legal_name',
            field=models.CharField(blank=True, default='', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='brand',
            name='contact_person',
            field=models.CharField(blank=True, default='', max_length=150),
            preserve_default=False,
        ),
    ]
