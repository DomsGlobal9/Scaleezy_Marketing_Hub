from django.db import migrations, models


ENGAGEMENT_CAPABILITY = 'ENGAGEMENT_RESPONSE'
RESEARCH_CAPABILITY = 'RESEARCH'


def add_real_capabilities(apps, schema_editor):
    AIProvider = apps.get_model('ai', 'AIProvider')
    WorkspaceAIProvider = apps.get_model('ai', 'WorkspaceAIProvider')

    text_provider_ids = []
    for provider in AIProvider.objects.iterator():
        capabilities = list(provider.capabilities or [])
        if 'TEXT' not in capabilities:
            continue
        text_provider_ids.append(provider.pk)
        additions = [ENGAGEMENT_CAPABILITY]
        if provider.key == 'openai':
            additions.append(RESEARCH_CAPABILITY)
        provider.capabilities = list(dict.fromkeys([*capabilities, *additions]))
        provider.save(update_fields=['capabilities'])

    for configured in WorkspaceAIProvider.objects.filter(
        provider_id__in=text_provider_ids
    ).iterator():
        if configured.capabilities is None:
            continue
        capabilities = list(configured.capabilities or [])
        if 'TEXT' not in capabilities:
            continue
        additions = [ENGAGEMENT_CAPABILITY]
        if configured.provider.key == 'openai':
            additions.append(RESEARCH_CAPABILITY)
        configured.capabilities = list(dict.fromkeys([*capabilities, *additions]))
        configured.save(update_fields=['capabilities'])


class Migration(migrations.Migration):
    dependencies = [('ai', '0009_workspace_provider_capabilities')]

    operations = [
        migrations.AlterField(
            model_name='aiusagelog',
            name='capability',
            field=models.CharField(
                choices=[
                    ('TEXT', 'Copy (headline, caption, hashtags)'),
                    ('IMAGE', 'Image generation'),
                    ('IMAGE_ANALYSIS', 'Image analysis'),
                    ('IMAGE_CAPTION', 'Image caption generation'),
                    ('VIDEO', 'Video generation'),
                    ('VIDEO_ANALYSIS', 'Video analysis'),
                    ('EMBEDDING', 'Text embedding (feedback similarity)'),
                    ('RESEARCH', 'Public-web research and creative discovery'),
                    ('ENGAGEMENT_RESPONSE', 'Engagement reply drafting and triage'),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name='workspaceairoute',
            name='capability',
            field=models.CharField(
                choices=[
                    ('TEXT', 'Copy (headline, caption, hashtags)'),
                    ('IMAGE', 'Image generation'),
                    ('IMAGE_ANALYSIS', 'Image analysis'),
                    ('IMAGE_CAPTION', 'Image caption generation'),
                    ('VIDEO', 'Video generation'),
                    ('VIDEO_ANALYSIS', 'Video analysis'),
                    ('EMBEDDING', 'Text embedding (feedback similarity)'),
                    ('RESEARCH', 'Public-web research and creative discovery'),
                    ('ENGAGEMENT_RESPONSE', 'Engagement reply drafting and triage'),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(add_real_capabilities, migrations.RunPython.noop),
    ]
