import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('inspirations', '0003_brandinspiration_text_type'),
        ('brands', '0002_brand_business_profile'),
        ('workspaces', '0002_workspacemember'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ResearchRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('query', models.CharField(max_length=1000)),
                ('objectives', models.JSONField(blank=True, default=list)),
                ('sources', models.JSONField(blank=True, default=list)),
                ('status', models.CharField(choices=[('QUEUED', 'Queued'), ('PROCESSING', 'Processing'), ('NEEDS_REVIEW', 'Needs review'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed')], default='QUEUED', max_length=20)),
                ('result_count', models.PositiveIntegerField(default=0)),
                ('provider_key', models.CharField(blank=True, max_length=100)),
                ('provider_name', models.CharField(blank=True, max_length=100)),
                ('task_id', models.CharField(blank=True, max_length=64)),
                ('error', models.TextField(blank=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('brand', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='research_runs', to='brands.brand')),
                ('initiated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='creative_research_runs', to=settings.AUTH_USER_MODEL)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='creative_research_runs', to='workspaces.marketingworkspace')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='ResearchFinding',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('kind', models.CharField(choices=[('POSTER', 'Poster / static creative'), ('SOCIAL_POST', 'Social post'), ('VIDEO', 'Video / reel'), ('CAMPAIGN', 'Campaign'), ('COMPETITOR', 'Competitor'), ('TREND', 'Trend'), ('HOOK', 'Hook / copy pattern'), ('OTHER', 'Other')], default='OTHER', max_length=20)),
                ('title', models.CharField(max_length=255)),
                ('source_url', models.URLField(max_length=1000)),
                ('preview_url', models.URLField(blank=True, max_length=1000)),
                ('source_name', models.CharField(blank=True, max_length=255)),
                ('platform', models.CharField(blank=True, max_length=100)),
                ('excerpt', models.TextField(blank=True)),
                ('observed_at', models.DateTimeField(blank=True, null=True)),
                ('rights_status', models.CharField(choices=[('UNKNOWN', 'Rights unknown'), ('PUBLIC_REFERENCE', 'Public reference only'), ('OWNED', 'Owned by this workspace'), ('LICENSED', 'Licensed for reuse'), ('RESTRICTED', 'Restricted / do not reuse')], default='UNKNOWN', max_length=24)),
                ('verification_status', models.CharField(choices=[('PENDING', 'Pending verification'), ('VERIFIED', 'Source verified'), ('FAILED', 'Source unavailable or unsafe')], default='PENDING', max_length=20)),
                ('verification_error', models.TextField(blank=True)),
                ('source_content_hash', models.CharField(blank=True, max_length=64)),
                ('dedupe_key', models.CharField(max_length=64)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('adopted_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('adopted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='adopted_research_findings', to=settings.AUTH_USER_MODEL)),
                ('adopted_inspiration', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='research_finding', to='inspirations.brandinspiration')),
                ('brand', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='research_findings', to='brands.brand')),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='findings', to='inspirations.researchrun')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='creative_research_findings', to='workspaces.marketingworkspace')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(model_name='researchrun', index=models.Index(fields=['workspace', 'brand', '-created_at'], name='inspiration_workspa_38a702_idx')),
        migrations.AddIndex(model_name='researchrun', index=models.Index(fields=['workspace', 'status'], name='inspiration_workspa_481dce_idx')),
        migrations.AddIndex(model_name='researchfinding', index=models.Index(fields=['workspace', 'brand', '-created_at'], name='inspiration_workspa_bd6d3c_idx')),
        migrations.AddIndex(model_name='researchfinding', index=models.Index(fields=['workspace', 'verification_status'], name='inspiration_workspa_113980_idx')),
        migrations.AddConstraint(model_name='researchfinding', constraint=models.UniqueConstraint(fields=('run', 'dedupe_key'), name='uniq_research_finding_per_run')),
    ]
