"""
Unique client code, and the client lifecycle status.

`client_code` is added without its unique constraint, backfilled for every
existing workspace, and only then made unique — the only order that works on
a populated table.

`status` defaults to ACTIVE, so every existing client keeps behaving exactly
as it did.
"""
from django.db import migrations, models


def assign_client_codes(apps, schema_editor):
    import secrets

    alphabet = 'ABCDEFGHJKLMNPQRTUVWXYZ2346789'
    Workspace = apps.get_model('workspaces', 'MarketingWorkspace')
    seen = set(
        Workspace.objects.exclude(client_code='').values_list('client_code', flat=True)
    )
    for workspace in Workspace.objects.filter(client_code=''):
        while True:
            code = 'SCZ-' + ''.join(secrets.choice(alphabet) for _ in range(8))
            if code not in seen:
                seen.add(code)
                break
        workspace.client_code = code
        workspace.save(update_fields=['client_code'])


def noop_reverse(apps, schema_editor):
    """Reversing drops the columns; the codes go with them."""


class Migration(migrations.Migration):

    dependencies = [
        ('workspaces', '0002_workspacemember'),
    ]

    operations = [
        migrations.AddField(
            model_name='marketingworkspace',
            name='client_code',
            field=models.CharField(blank=True, db_index=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='marketingworkspace',
            name='status',
            field=models.CharField(
                choices=[
                    ('ACTIVE', 'Active'),
                    ('SUSPENDED', 'Suspended'),
                    ('ARCHIVED', 'Archived'),
                ],
                db_index=True, default='ACTIVE', max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='marketingworkspace',
            name='status_reason',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='marketingworkspace',
            name='status_changed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(assign_client_codes, noop_reverse),
        migrations.AlterField(
            model_name='marketingworkspace',
            name='client_code',
            field=models.CharField(
                blank=True, db_index=True, max_length=32, unique=True,
                help_text='Unique client identifier, e.g. SCZ-K4M2R9TB. Assigned automatically.',
            ),
        ),
    ]
