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
        # Unconditional backfill: AddField fills existing rows with the
        # migration's own run time (Django's effective default for auto_now),
        # not NULL — left like that, every pre-sweep stuck row would look
        # freshly stuck and get bought a rescue. Rewinding the clock to
        # created_at lets the rescue-horizon age check retire that debris
        # honestly instead.
        migrations.RunSQL(
            "UPDATE gemini_generation_requests SET updated_at = created_at",
            migrations.RunSQL.noop,
        ),
        migrations.AddIndex(
            model_name='geminigenerationrequest',
            index=models.Index(
                fields=['updated_at'],
                name='gemini_req_generating_idx',
                condition=models.Q(status='GENERATING'),
            ),
        ),
    ]
