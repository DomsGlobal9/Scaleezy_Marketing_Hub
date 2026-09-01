from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gemini', '0002_provider_neutral_request_defaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='geminigenerationrequest',
            name='retry_count',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='geminigenerationrequest',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
    ]
