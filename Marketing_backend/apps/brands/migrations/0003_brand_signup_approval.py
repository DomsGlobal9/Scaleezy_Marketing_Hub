"""
Signup approval state on Brand.

PENDING joins the status choices; `reviewed_at` / `reviewed_by` record the
operator decision. Additive and nullable: every existing brand keeps its
status and needs no backfill.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0002_brand_business_profile'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='brand',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Pending approval'),
                    ('ACTIVE', 'Active'),
                    ('ARCHIVED', 'Archived'),
                ],
                default='ACTIVE',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='brand',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='brand',
            name='reviewed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reviewed_brands',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
