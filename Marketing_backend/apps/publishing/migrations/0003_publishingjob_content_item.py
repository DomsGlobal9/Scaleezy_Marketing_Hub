import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0002_contentitem_layout_config_contentitem_layout_plugin'),
        ('publishing', '0002_add_caption_to_publishingjob'),
    ]

    operations = [
        migrations.AddField(
            model_name='publishingjob',
            name='content_item',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='publishing_jobs',
                to='content.contentitem',
            ),
        ),
    ]
