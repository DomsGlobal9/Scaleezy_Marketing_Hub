"""User-uploaded brand templates ride BrandInspiration.

A BRAND_TEMPLATE row is a poster design the brand uploaded for generation to
match (the founder's replacement for the removed built-in catalogue).
`template_last_used_at` is the rotation clock: plain nullable AddField, so
existing rows backfill NULL — which the rotation reads as "never used, pick
first". No data migration needed.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inspirations', '0004_research_discovery'),
    ]

    operations = [
        migrations.AddField(
            model_name='brandinspiration',
            name='template_last_used_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='brandinspiration',
            name='inspiration_type',
            field=models.CharField(choices=[('IMAGE', 'Image'), ('SCREENSHOT', 'Screenshot'), ('URL', 'URL'), ('WEB_PAGE', 'Web page'), ('POST', 'Social post'), ('REEL', 'Reel / short video'), ('VIDEO', 'Video'), ('AD', 'Advertisement'), ('PIN', 'Pinboard pin'), ('COMPETITOR', 'Competitor reference'), ('REFERENCE', 'General reference'), ('MOODBOARD', 'Moodboard'), ('TEXT', 'Text / copy'), ('BRAND_TEMPLATE', 'Brand template'), ('OTHER', 'Other')], default='REFERENCE', max_length=20),
        ),
    ]
