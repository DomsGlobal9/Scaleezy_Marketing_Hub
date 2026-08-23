"""
Default AI routing for a new tenant.

The defect this exists to close: a workspace created through the API had no
provider and no route, so its first Create returned 503 and stayed that way
until a developer ran a management command. So what matters here is that the
service produces a routable workspace, that running it again is not different
from running it once, and that it copies no secret into the database. The
strict client bootstrap is tested separately; this file also proves the repair
helper reports failure without raising.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.ai.adapters.base import AIProviderAdapter
from apps.ai.models import (
    AIProvider,
    Capability,
    Strategy,
    WorkspaceAIProvider,
    WorkspaceAIRoute,
)
from apps.ai.provisioning import (
    ensure_default_ai_routing,
    provision_default_ai,
    resolve_default_provider,
    resolve_default_providers,
)
from apps.workspaces.models import MarketingWorkspace


class DefaultTestAdapter(AIProviderAdapter):
    """A vendor-neutral adapter used to prove the provisioning contract."""

    key = 'test-default'
    display_name = 'Test Default'
    capabilities = (Capability.TEXT, Capability.IMAGE)

    def health_check(self):
        return {'ok': True, 'detail': 'test adapter ready'}


class TextOnlyTestAdapter(DefaultTestAdapter):
    key = 'test-text-only'
    display_name = 'Test Text Only'
    capabilities = (Capability.TEXT,)


class ImageOnlyTestAdapter(DefaultTestAdapter):
    key = 'test-image-only'
    display_name = 'Test Image Only'
    capabilities = (Capability.IMAGE,)


class EnsureDefaultAIRoutingTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='c1', workspace_name='One'
        )
        self.provider, _ = AIProvider.objects.update_or_create(
            key=DefaultTestAdapter.key,
            defaults={
                'display_name': DefaultTestAdapter.display_name,
                'capabilities': [Capability.TEXT, Capability.IMAGE],
                'unit_cost': 0,
                'is_available': True,
            },
        )
        AIProvider.objects.exclude(pk=self.provider.pk).update(is_available=False)

        provisioning_registry = patch(
            'apps.ai.provisioning.all_adapters',
            return_value={self.provider.key: DefaultTestAdapter},
        )
        router_registry = patch(
            'apps.ai.registry.get_adapter_class',
            side_effect=lambda key: (
                DefaultTestAdapter if key == self.provider.key else None
            ),
        )
        provisioning_registry.start()
        router_registry.start()
        self.addCleanup(provisioning_registry.stop)
        self.addCleanup(router_registry.stop)

    def test_it_creates_an_enabled_provider_and_both_routes(self):
        self.assertTrue(ensure_default_ai_routing(self.workspace))

        workspace_provider = WorkspaceAIProvider.objects.get(
            workspace=self.workspace, provider=self.provider
        )
        self.assertTrue(workspace_provider.enabled)

        routes = {
            route.capability: route
            for route in WorkspaceAIRoute.objects.filter(workspace=self.workspace)
        }
        self.assertEqual(set(routes), {Capability.TEXT, Capability.IMAGE})
        for route in routes.values():
            self.assertTrue(route.enabled)
            self.assertEqual(route.priority, 100)
            self.assertEqual(route.strategy, Strategy.FAILOVER)

    def test_no_credential_is_copied_into_the_database(self):
        """The adapter falls back to the server key. A key per tenant is one
        more copy of the secret and one more thing to rotate."""
        ensure_default_ai_routing(self.workspace)
        self.assertEqual(
            WorkspaceAIProvider.objects.get(workspace=self.workspace).credentials_encrypted,
            '',
        )

    def test_running_it_again_changes_nothing(self):
        ensure_default_ai_routing(self.workspace)
        before = sorted(
            WorkspaceAIRoute.objects.filter(workspace=self.workspace).values_list(
                'pk', 'capability', 'priority', 'enabled'
            )
        )

        self.assertTrue(ensure_default_ai_routing(self.workspace))

        self.assertEqual(
            WorkspaceAIProvider.objects.filter(workspace=self.workspace).count(), 1
        )
        self.assertEqual(
            sorted(
                WorkspaceAIRoute.objects.filter(workspace=self.workspace).values_list(
                    'pk', 'capability', 'priority', 'enabled'
                )
            ),
            before,
        )

    def test_a_provider_row_someone_switched_off_is_re_enabled(self):
        WorkspaceAIProvider.objects.create(
            workspace=self.workspace, provider=self.provider, enabled=False
        )
        ensure_default_ai_routing(self.workspace)
        self.assertTrue(
            WorkspaceAIProvider.objects.get(workspace=self.workspace).enabled
        )

    def test_it_touches_only_the_workspace_it_was_given(self):
        neighbour = MarketingWorkspace.objects.create(
            customer_id='c2', workspace_name='Two'
        )
        ensure_default_ai_routing(self.workspace)

        self.assertFalse(WorkspaceAIRoute.objects.filter(workspace=neighbour).exists())
        self.assertFalse(WorkspaceAIProvider.objects.filter(workspace=neighbour).exists())

    def test_a_catalogue_row_with_no_adapter_is_never_routed(self):
        """Routing it would look configured and behave like a 503, because
        `registry.build()` drops a candidate it has no code for."""
        AIProvider.objects.update_or_create(
            key='nonesuch',
            defaults={
                'display_name': 'Nonesuch',
                'capabilities': [Capability.TEXT, Capability.IMAGE],
                'unit_cost': 0,
                'is_available': True,
            },
        )
        self.assertEqual(resolve_default_provider().key, self.provider.key)

        ensure_default_ai_routing(self.workspace)
        self.assertEqual(
            set(
                WorkspaceAIRoute.objects.filter(workspace=self.workspace).values_list(
                    'provider__key', flat=True
                )
            ),
            {self.provider.key},
        )

    def test_the_global_kill_switch_is_respected(self):
        AIProvider.objects.update(is_available=False)

        self.assertIsNone(resolve_default_provider())
        self.assertFalse(ensure_default_ai_routing(self.workspace))
        self.assertFalse(WorkspaceAIRoute.objects.exists())

    def test_a_provisioning_failure_is_reported_and_not_raised(self):
        with patch(
            'apps.ai.provisioning.provision_ai_routing', side_effect=RuntimeError('boom')
        ):
            self.assertFalse(ensure_default_ai_routing(self.workspace))
        self.assertFalse(WorkspaceAIRoute.objects.exists())

    def test_the_router_can_then_actually_resolve_a_candidate(self):
        from apps.ai.router import AIRouter

        self.assertEqual(AIRouter(self.workspace)._candidates(Capability.TEXT), [])

        ensure_default_ai_routing(self.workspace)

        for capability in (Capability.TEXT, Capability.IMAGE):
            with self.subTest(capability=capability):
                candidates = AIRouter(self.workspace)._candidates(capability)
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0]['route'].provider.key, self.provider.key)

    def test_default_bootstrap_composes_different_providers_by_capability(self):
        self.provider.is_available = False
        self.provider.save(update_fields=['is_available'])
        text_provider, _ = AIProvider.objects.update_or_create(
            key=TextOnlyTestAdapter.key,
            defaults={
                'display_name': TextOnlyTestAdapter.display_name,
                'capabilities': [Capability.TEXT],
                'unit_cost': 0.01,
                'is_available': True,
            },
        )
        image_provider, _ = AIProvider.objects.update_or_create(
            key=ImageOnlyTestAdapter.key,
            defaults={
                'display_name': ImageOnlyTestAdapter.display_name,
                'capabilities': [Capability.IMAGE],
                'unit_cost': 0.02,
                'is_available': True,
            },
        )
        adapters = {
            TextOnlyTestAdapter.key: TextOnlyTestAdapter,
            ImageOnlyTestAdapter.key: ImageOnlyTestAdapter,
        }

        with patch('apps.ai.provisioning.all_adapters', return_value=adapters):
            resolved = resolve_default_providers()
            workspace_providers, routes = provision_default_ai(self.workspace)

        self.assertEqual(resolved[Capability.TEXT], text_provider)
        self.assertEqual(resolved[Capability.IMAGE], image_provider)
        self.assertEqual(
            {workspace_provider.provider for workspace_provider in workspace_providers},
            {text_provider, image_provider},
        )
        self.assertEqual(
            {(route.capability, route.provider) for route in routes},
            {
                (Capability.TEXT, text_provider),
                (Capability.IMAGE, image_provider),
            },
        )
