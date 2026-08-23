from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('workspaces', '0004_workspace_approval_status')]

    operations = [
        migrations.AddField(
            model_name='marketingworkspace',
            name='kind',
            field=models.CharField(
                choices=[('CLIENT', 'Client'), ('INTERNAL', 'Internal / test')],
                db_index=True,
                default='CLIENT',
                help_text='INTERNAL workspaces are excluded from shared learning.',
                max_length=16,
            ),
        ),
    ]
