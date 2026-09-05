"""
Promotes the vocabulary from the provisional stand-in to the authoritative
56-element list (see apps/feedback/vocabulary.py).

Three moves, all idempotent:

1. Upsert every authoritative element — a row whose key already exists keeps
   its identity (so learned rules and recorded feedback keep resolving) but
   is realigned to the production label, group, description and position, and
   promoted to `is_provisional=False`.
2. Retire placeholder rows with no production counterpart by deactivating
   them (`is_active=False`), never deleting: feedback already tagged with a
   placeholder key must keep resolving.
3. Leave untouched any non-provisional row outside the list — that is
   curation added through admin, and a migration has no business editing it.

The reverse re-flags the authoritative rows as provisional and reactivates
deactivated provisional rows outside the list — the exact predicate the
forward pass deactivated on, so the two stay symmetric. It cannot restore
labels the upsert overwrote; roll forward again rather than relying on it
for curation recovery.
"""
from django.db import migrations


def _authoritative_keys():
    from apps.feedback.vocabulary import ELEMENTS

    return {key for _, key, _, _ in ELEMENTS}


def promote(apps, schema_editor):
    FeedbackElement = apps.get_model('feedback', 'FeedbackElement')

    from apps.feedback.vocabulary import ELEMENTS

    authoritative_keys = set()
    position_in_group = {}
    for group, key, label, description in ELEMENTS:
        authoritative_keys.add(key)
        position = position_in_group.get(group, 0)
        position_in_group[group] = position + 1

        element, _ = FeedbackElement.objects.get_or_create(
            key=key, defaults={'label': label, 'group': group}
        )
        element.label = label
        element.group = group
        element.description = description
        element.position = position
        element.is_active = True
        element.is_provisional = False
        element.save()

    FeedbackElement.objects.filter(is_provisional=True).exclude(
        key__in=authoritative_keys
    ).update(is_active=False)


def demote(apps, schema_editor):
    FeedbackElement = apps.get_model('feedback', 'FeedbackElement')

    authoritative_keys = _authoritative_keys()

    FeedbackElement.objects.filter(key__in=authoritative_keys).update(
        is_provisional=True
    )
    FeedbackElement.objects.filter(
        is_provisional=True, is_active=False
    ).exclude(key__in=authoritative_keys).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [('feedback', '0002_seed_vocabulary')]

    operations = [migrations.RunPython(promote, demote)]
