from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.ai.adapters.base import AIProviderAdapter
from apps.ai.catalogue import sync_provider_catalogue
from apps.ai.models import AIProvider, Capability
from apps.ai.registry import _adapter_subclasses


class CatalogueTestAdapter(AIProviderAdapter):
    key = 'catalogue-test'
    display_name = 'Catalogue Test'
    capabilities = (Capability.TEXT, Capability.EMBEDDING)
    default_model = 'test-model'
    unit_cost = 0.0123

    def health_check(self):
        return {'ok': True, 'detail': 'ready'}


class RegistryDiscoveryTests(SimpleTestCase):
    def test_nested_protocol_adapter_is_discovered(self):
        class SharedProtocolAdapter(AIProviderAdapter):
            def health_check(self):
                return {'ok': True, 'detail': 'ready'}

        class NestedProviderAdapter(SharedProtocolAdapter):
            key = 'nested-provider-test'

        self.assertIn(NestedProviderAdapter, set(_adapter_subclasses()))


class CatalogueSyncTests(TestCase):
    def adapters(self):
        return {CatalogueTestAdapter.key: CatalogueTestAdapter}

    def test_sync_creates_every_installed_adapter_and_is_idempotent(self):
        AIProvider.objects.filter(key=CatalogueTestAdapter.key).delete()

        with patch('apps.ai.catalogue.all_adapters', return_value=self.adapters()):
            first = sync_provider_catalogue()
            second = sync_provider_catalogue()

        provider = AIProvider.objects.get(key=CatalogueTestAdapter.key)
        self.assertEqual(first[0]['action'], 'created')
        self.assertEqual(second[0]['action'], 'unchanged')
        self.assertEqual(provider.display_name, CatalogueTestAdapter.display_name)
        self.assertEqual(provider.capabilities, [Capability.TEXT, Capability.EMBEDDING])
        self.assertEqual(provider.default_model, CatalogueTestAdapter.default_model)
        self.assertEqual(provider.unit_cost, Decimal('0.0123'))

    def test_sync_refreshes_metadata_but_preserves_operator_kill_switch(self):
        provider, _ = AIProvider.objects.update_or_create(
            key=CatalogueTestAdapter.key,
            defaults={
                'display_name': 'Old name',
                'capabilities': [],
                'default_model': '',
                'unit_cost': 0,
                'is_available': False,
            },
        )

        with patch('apps.ai.catalogue.all_adapters', return_value=self.adapters()):
            result = sync_provider_catalogue()

        provider.refresh_from_db()
        self.assertEqual(result[0]['action'], 'updated')
        self.assertEqual(provider.display_name, CatalogueTestAdapter.display_name)
        self.assertFalse(provider.is_available)

    def test_management_command_runs_the_same_idempotent_service(self):
        AIProvider.objects.filter(key=CatalogueTestAdapter.key).delete()
        out = StringIO()

        with patch('apps.ai.catalogue.all_adapters', return_value=self.adapters()):
            call_command('sync_ai_catalogue', stdout=out)
            call_command('sync_ai_catalogue', '--check', stdout=out)

        self.assertTrue(AIProvider.objects.filter(key=CatalogueTestAdapter.key).exists())
        self.assertIn('already in sync', out.getvalue())
