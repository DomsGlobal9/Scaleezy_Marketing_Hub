"""
Platform authority and its audit trail.

Both tables are new; nothing existing is altered and there is nothing to
backfill. `PlatformAdmin` starts empty on purpose — the first grant is made
with `manage.py grant_platform_admin`.
"""
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0001_initial'),
        ('workspaces', '0003_client_code_and_status'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PlatformAdmin',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('is_active', models.BooleanField(default=True)),
                ('note', models.CharField(blank=True, max_length=255)),
                ('granted_at', models.DateTimeField(auto_now_add=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('granted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='platform_admin_grants', to=settings.AUTH_USER_MODEL)),
                ('revoked_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='platform_admin_revocations', to=settings.AUTH_USER_MODEL)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='platform_admin', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'platform_admins', 'ordering': ['-granted_at']},
        ),
        migrations.CreateModel(
            name='PlatformAuditLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('actor_username', models.CharField(blank=True, max_length=255)),
                ('action', models.CharField(db_index=True, max_length=64)),
                ('target', models.CharField(blank=True, max_length=255)),
                ('detail', models.JSONField(blank=True, default=dict)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='platform_audit_entries', to=settings.AUTH_USER_MODEL)),
                ('workspace', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='platform_audit_entries', to='workspaces.marketingworkspace')),
            ],
            options={'db_table': 'platform_audit_logs', 'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='platformauditlog',
            index=models.Index(fields=['-created_at'], name='platform_au_created_f8bce8_idx'),
        ),
        migrations.AddIndex(
            model_name='platformauditlog',
            index=models.Index(fields=['actor', '-created_at'], name='platform_au_actor_i_a236dd_idx'),
        ),
        migrations.AddIndex(
            model_name='platformauditlog',
            index=models.Index(fields=['workspace', '-created_at'], name='platform_au_workspa_1708d2_idx'),
        ),
        migrations.AddIndex(
            model_name='platformauditlog',
            index=models.Index(fields=['action', '-created_at'], name='platform_au_action_a11f82_idx'),
        ),
    ]
