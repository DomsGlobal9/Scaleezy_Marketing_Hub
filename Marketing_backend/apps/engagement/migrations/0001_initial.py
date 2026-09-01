import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('brands', '0004_brand_brain_health'),
        ('social_accounts', '0001_initial'),
        ('workspaces', '0002_workspacemember'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EngagementSyncRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('QUEUED', 'Queued'), ('PROCESSING', 'Processing'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed')], default='QUEUED', max_length=20)),
                ('task_id', models.CharField(blank=True, max_length=64)),
                ('cursor', models.CharField(blank=True, max_length=500)),
                ('imported_count', models.PositiveIntegerField(default=0)),
                ('seen_count', models.PositiveIntegerField(default=0)),
                ('error', models.TextField(blank=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('brand', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='engagement_sync_runs', to='brands.brand')),
                ('initiated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='engagement_sync_runs', to=settings.AUTH_USER_MODEL)),
                ('social_connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='engagement_sync_runs', to='social_accounts.socialconnection')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='engagement_sync_runs', to='workspaces.marketingworkspace')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='SavedReply',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=120)),
                ('body', models.TextField(max_length=2000)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='saved_replies_created', to=settings.AUTH_USER_MODEL)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saved_replies', to='workspaces.marketingworkspace')),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='EngagementItem',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('platform', models.CharField(max_length=50)),
                ('kind', models.CharField(choices=[('COMMENT', 'Comment'), ('MENTION', 'Mention'), ('MESSAGE', 'Direct message')], max_length=20)),
                ('external_id', models.CharField(max_length=255)),
                ('thread_id', models.CharField(blank=True, max_length=255)),
                ('author_name', models.CharField(blank=True, max_length=255)),
                ('author_handle', models.CharField(blank=True, max_length=255)),
                ('body', models.TextField()),
                ('source_url', models.URLField(blank=True, max_length=1000)),
                ('occurred_at', models.DateTimeField()),
                ('source_payload', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('NEW', 'New'), ('IN_PROGRESS', 'In progress'), ('AWAITING_APPROVAL', 'Awaiting approval'), ('APPROVED', 'Approved to send'), ('SENDING', 'Sending'), ('RESOLVED', 'Resolved'), ('IGNORED', 'Ignored')], default='NEW', max_length=24)),
                ('sentiment', models.CharField(choices=[('UNKNOWN', 'Unknown'), ('POSITIVE', 'Positive'), ('NEUTRAL', 'Neutral'), ('NEGATIVE', 'Negative')], default='UNKNOWN', max_length=16)),
                ('urgency', models.CharField(choices=[('LOW', 'Low'), ('NORMAL', 'Normal'), ('HIGH', 'High'), ('CRITICAL', 'Critical')], default='NORMAL', max_length=16)),
                ('lock_expires_at', models.DateTimeField(blank=True, null=True)),
                ('ai_draft', models.TextField(blank=True)),
                ('draft_status', models.CharField(choices=[('NOT_REQUESTED', 'Not requested'), ('QUEUED', 'Queued'), ('PROCESSING', 'Processing'), ('READY', 'Ready for review'), ('FAILED', 'Failed')], default='NOT_REQUESTED', max_length=20)),
                ('draft_task_id', models.CharField(blank=True, max_length=64)),
                ('ai_provider_key', models.CharField(blank=True, max_length=100)),
                ('ai_provider_name', models.CharField(blank=True, max_length=100)),
                ('ai_risk_flags', models.JSONField(blank=True, default=list)),
                ('approved_response', models.TextField(blank=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('external_response_id', models.CharField(blank=True, max_length=255)),
                ('responded_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_engagement_items', to=settings.AUTH_USER_MODEL)),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_engagement_items', to=settings.AUTH_USER_MODEL)),
                ('brand', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='engagement_items', to='brands.brand')),
                ('locked_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='locked_engagement_items', to=settings.AUTH_USER_MODEL)),
                ('social_connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='engagement_items', to='social_accounts.socialconnection')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='engagement_items', to='workspaces.marketingworkspace')),
            ],
            options={'ordering': ['-occurred_at', '-created_at']},
        ),
        migrations.AddIndex(model_name='engagementsyncrun', index=models.Index(fields=['workspace', 'status', '-created_at'], name='engagement__workspa_dada1f_idx')),
        migrations.AddConstraint(model_name='savedreply', constraint=models.UniqueConstraint(fields=('workspace', 'name'), name='uniq_saved_reply_name')),
        migrations.AddIndex(model_name='engagementitem', index=models.Index(fields=['workspace', 'status', '-occurred_at'], name='engagement__workspa_53fb87_idx')),
        migrations.AddIndex(model_name='engagementitem', index=models.Index(fields=['workspace', 'assigned_to', 'status'], name='engagement__workspa_246e19_idx')),
        migrations.AddIndex(model_name='engagementitem', index=models.Index(fields=['workspace', 'platform', '-occurred_at'], name='engagement__workspa_b09245_idx')),
        migrations.AddConstraint(model_name='engagementitem', constraint=models.UniqueConstraint(fields=('social_connection', 'external_id'), name='uniq_engagement_external_item')),
    ]
