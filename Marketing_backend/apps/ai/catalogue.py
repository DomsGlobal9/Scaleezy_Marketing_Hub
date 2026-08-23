"""Synchronise installed adapter metadata into the global provider catalogue."""
from decimal import Decimal

from django.db import transaction

from .models import AIProvider
from .registry import all_adapters


def _metadata(adapter_class):
    return {
        'display_name': adapter_class.display_name or adapter_class.key.title(),
        'capabilities': [str(value) for value in (adapter_class.capabilities or ())],
        'default_model': adapter_class.default_model or '',
        'unit_cost': Decimal(str(adapter_class.unit_cost or 0)),
    }


def sync_provider_catalogue(*, apply=True):
    """Create or refresh one catalogue row for every installed adapter.

    The operator-owned global kill switch is deliberately preserved. Adapter
    code owns descriptive/capability metadata; an administrator still owns
    whether that integration is available to tenants.

    Returns a stable list of ``{key, action, fields}`` dictionaries. With
    ``apply=False`` the same diff is reported without writing anything.
    """
    results = []

    with transaction.atomic():
        for key, adapter_class in sorted(all_adapters().items()):
            metadata = _metadata(adapter_class)
            provider = AIProvider.objects.select_for_update().filter(key=key).first()

            if provider is None:
                results.append({'key': key, 'action': 'created', 'fields': sorted(metadata)})
                if apply:
                    AIProvider.objects.create(key=key, is_available=True, **metadata)
                continue

            changed_fields = [
                field
                for field, value in metadata.items()
                if getattr(provider, field) != value
            ]
            if not changed_fields:
                results.append({'key': key, 'action': 'unchanged', 'fields': []})
                continue

            results.append({
                'key': key,
                'action': 'updated',
                'fields': sorted(changed_fields),
            })
            if apply:
                for field in changed_fields:
                    setattr(provider, field, metadata[field])
                provider.save(update_fields=changed_fields)

        if not apply:
            transaction.set_rollback(True)

    return results
