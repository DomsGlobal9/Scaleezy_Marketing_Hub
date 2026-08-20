"""
Seeds the provisional feedback vocabulary.

Idempotent, and deliberately conservative on re-run: an element a human has
edited in admin keeps its label and description. Only rows that do not exist
yet are created, so re-running this never overwrites curation.

See apps/feedback/vocabulary.py for why these are provisional.
"""
from django.db import migrations


def seed(apps, schema_editor):
    FeedbackElement = apps.get_model('feedback', 'FeedbackElement')

    from apps.feedback.vocabulary import PROVISIONAL_ELEMENTS

    position_in_group = {}
    for group, key, label, description in PROVISIONAL_ELEMENTS:
        position = position_in_group.get(group, 0)
        position_in_group[group] = position + 1

        FeedbackElement.objects.get_or_create(
            key=key,
            defaults={
                'label': label,
                'group': group,
                'description': description,
                'position': position,
                'is_active': True,
                'is_provisional': True,
            },
        )


def unseed(apps, schema_editor):
    FeedbackElement = apps.get_model('feedback', 'FeedbackElement')

    from apps.feedback.vocabulary import PROVISIONAL_ELEMENTS

    # Only the untouched placeholders. Anything promoted to non-provisional is
    # real vocabulary now and must survive a rollback of this migration.
    FeedbackElement.objects.filter(
        key__in=[key for _, key, _, _ in PROVISIONAL_ELEMENTS], is_provisional=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('feedback', '0001_initial')]

    operations = [migrations.RunPython(seed, unseed)]
