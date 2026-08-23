"""
Approval becomes a property of the CLIENT (workspace), not of a brand.

Deriving "approved" from "does any brand happen to be ACTIVE" let a pending
customer approve themselves by creating a second brand. This column is what
the spend gate reads from now on.

Default APPROVED, so every workspace that existed before approval keeps
working untouched. The backfill marks as PENDING only workspaces that clearly
came through signup and were never approved: they have brands, none ACTIVE,
at least one PENDING.
"""
from django.db import migrations, models


def backfill(apps, schema_editor):
    Workspace = apps.get_model('workspaces', 'MarketingWorkspace')
    Brand = apps.get_model('brands', 'Brand')

    pending_ids = set(
        Brand.objects.filter(status='PENDING').values_list('workspace_id', flat=True)
    )
    active_ids = set(
        Brand.objects.filter(status='ACTIVE').values_list('workspace_id', flat=True)
    )
    for ws_id in pending_ids - active_ids:
        Workspace.objects.filter(pk=ws_id).update(approval_status='PENDING')


def noop(apps, schema_editor):
    """Reverse drops the column."""


class Migration(migrations.Migration):

    dependencies = [
        ('workspaces', '0003_client_code_and_status'),
        ('brands', '0004_brand_brain_health'),
    ]

    operations = [
        migrations.AddField(
            model_name='marketingworkspace',
            name='approval_status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Awaiting Scaleezy approval'),
                    ('APPROVED', 'Approved'),
                    ('REJECTED', 'Rejected'),
                ],
                db_index=True, default='APPROVED', max_length=20,
            ),
        ),
        migrations.RunPython(backfill, noop),
    ]
