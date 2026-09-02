from django.db import migrations, models


def adopt_round_robin_default(apps, schema_editor):
    WorkspaceAIRoute = apps.get_model('ai', 'WorkspaceAIRoute')
    WorkspaceAIRoute.objects.filter(strategy='FAILOVER').update(
        strategy='ROUND_ROBIN'
    )


class Migration(migrations.Migration):
    dependencies = [('ai', '0010_research_engagement_capabilities')]

    operations = [
        migrations.AlterField(
            model_name='workspaceairoute',
            name='strategy',
            field=models.CharField(
                choices=[
                    ('FAILOVER', 'Failover — first healthy provider wins'),
                    ('BEST_OF', 'Best of — run all, keep the highest scoring'),
                    ('ROUND_ROBIN', 'Round robin — spread load and spend'),
                ],
                default='ROUND_ROBIN',
                max_length=20,
            ),
        ),
        migrations.RunPython(
            adopt_round_robin_default,
            migrations.RunPython.noop,
        ),
    ]
