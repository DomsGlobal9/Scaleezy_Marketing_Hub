import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('universal', '0002_platforminspiration_entry_kinds'),
        ('workspaces', '0005_workspace_kind'),
    ]

    operations = [
        migrations.CreateModel(
            name='LearnedPattern',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('category', models.CharField(max_length=64)),
                ('attribute', models.CharField(max_length=255)),
                ('value', models.TextField()),
                ('normalized_value', models.TextField()),
                ('industry', models.CharField(blank=True, max_length=100)),
                ('channel', models.CharField(blank=True, max_length=64)),
                ('contributor_count', models.PositiveIntegerField(default=0)),
                ('supporting_brand_count', models.PositiveIntegerField(default=0)),
                ('confidence', models.FloatField(default=0.0)),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('PUBLISHED', 'Published'), ('RETIRED', 'Retired')], default='DRAFT', max_length=20)),
                ('compiled_at', models.DateTimeField()),
                ('pattern_version', models.CharField(db_index=True, max_length=64)),
                ('contributing_workspace_ids', models.JSONField(blank=True, default=list)),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('retired_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'universal_learned_patterns',
                'ordering': ['-contributor_count', 'category', 'attribute', 'normalized_value'],
                'indexes': [
                    models.Index(fields=['status', '-contributor_count'], name='universal_l_status_19702c_idx'),
                    models.Index(fields=['category', 'attribute'], name='universal_l_categor_0c0a94_idx'),
                ],
            },
        ),
    ]
