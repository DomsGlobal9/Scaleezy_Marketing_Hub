"""
The routing provisioning command.

It writes production configuration, so what matters is that it refuses the
configurations that would look correct and behave like a 503, and that running
it twice is not different from running it once.
"""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.ai.models import AIProvider, Capability, Strategy, WorkspaceAIProvider, WorkspaceAIRoute
from apps.workspaces.models import MarketingWorkspace


class ConfigureAIRoutingTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='c1', workspace_name='One'
        )
        self.provider, _ = AIProvider.objects.get_or_create(
            key='gemini',
            defaults={
                'display_name': 'Google Gemini',
                'capabilities': ['TEXT', 'IMAGE', 'IMAGE_ANALYSIS', 'EMBEDDING'],
            },
        )

    def run_command(self, *args):
        out = StringIO()
        call_command('configure_ai_routing', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        output = self.run_command('--dry-run')
        self.assertIn('would be made', output)
        self.assertFalse(WorkspaceAIProvider.objects.exists())
        self.assertFalse(WorkspaceAIRoute.objects.exists())

    def test_apply_creates_enabled_provider_and_both_routes(self):
        self.run_command('--apply')

        wp = WorkspaceAIProvider.objects.get(workspace=self.workspace, provider=self.provider)
        self.assertTrue(wp.enabled)
        # The point of the design: no credential is copied into the database.
        self.assertEqual(wp.credentials_encrypted, '')

        routes = {r.capability: r for r in WorkspaceAIRoute.objects.all()}
        self.assertEqual(set(routes), {Capability.TEXT, Capability.IMAGE})
        for route in routes.values():
            self.assertTrue(route.enabled)
            self.assertEqual(route.priority, 100)
            self.assertEqual(route.strategy, Strategy.FAILOVER)

    def test_running_twice_changes_nothing_further(self):
        self.run_command('--apply')
        before = (WorkspaceAIProvider.objects.count(), WorkspaceAIRoute.objects.count())

        output = self.run_command('--apply')

        self.assertEqual(
            (WorkspaceAIProvider.objects.count(), WorkspaceAIRoute.objects.count()), before
        )
        self.assertIn('already correct', output)

    def test_a_disabled_provider_row_is_re_enabled(self):
        WorkspaceAIProvider.objects.create(
            workspace=self.workspace, provider=self.provider, enabled=False
        )
        self.run_command('--apply')
        self.assertTrue(
            WorkspaceAIProvider.objects.get(workspace=self.workspace).enabled
        )

    def test_refuses_a_capability_the_provider_does_not_support(self):
        with self.assertRaises(CommandError) as caught:
            self.run_command('--apply', '--capability', 'VIDEO')
        self.assertIn('does not genuinely support', str(caught.exception))
        self.assertFalse(WorkspaceAIRoute.objects.exists())

    def test_refuses_a_provider_with_no_installed_adapter(self):
        AIProvider.objects.create(
            key='nonesuch', display_name='Nonesuch', capabilities=['TEXT'],
        )
        with self.assertRaises(CommandError) as caught:
            self.run_command('--apply', '--provider', 'nonesuch')
        self.assertIn('No adapter installed', str(caught.exception))
        self.assertFalse(WorkspaceAIRoute.objects.exists())

    def test_refuses_when_the_global_kill_switch_is_set(self):
        self.provider.is_available = False
        self.provider.save(update_fields=['is_available'])
        with self.assertRaises(CommandError) as caught:
            self.run_command('--apply')
        self.assertIn('switched off globally', str(caught.exception))

    def test_credential_env_must_actually_be_set(self):
        with self.assertRaises(CommandError) as caught:
            self.run_command('--apply', '--credential-env', 'A_KEY_THAT_IS_NOT_SET')
        self.assertIn('is not set in this environment', str(caught.exception))
        self.assertFalse(WorkspaceAIProvider.objects.exists())

    def test_credential_when_supplied_is_stored_encrypted_and_never_printed(self):
        import os
        from apps.social_accounts.utils.encryption import decrypt_token

        secret = 'sk-test-value-never-printed'
        os.environ['SMOKE_TEST_AI_KEY'] = secret
        try:
            output = self.run_command('--apply', '--credential-env', 'SMOKE_TEST_AI_KEY')
        finally:
            del os.environ['SMOKE_TEST_AI_KEY']

        wp = WorkspaceAIProvider.objects.get(workspace=self.workspace)
        self.assertTrue(wp.credentials_encrypted)
        self.assertNotIn(secret, wp.credentials_encrypted)
        self.assertEqual(decrypt_token(wp.credentials_encrypted), secret)
        # The whole point: the operator's console never sees the value.
        self.assertNotIn(secret, output)

    def test_only_the_named_workspace_is_configured(self):
        other = MarketingWorkspace.objects.create(customer_id='c2', workspace_name='Two')
        self.run_command('--apply', '--workspace', str(self.workspace.pk))

        self.assertTrue(WorkspaceAIRoute.objects.filter(workspace=self.workspace).exists())
        self.assertFalse(WorkspaceAIRoute.objects.filter(workspace=other).exists())

    def test_routing_makes_the_router_resolve_a_candidate(self):
        """The defect this command exists to fix: no route means every Create
        gets a 503 because the router has nothing to select."""
        from apps.ai.router import AIRouter

        router = AIRouter(self.workspace)
        self.assertEqual(router._candidates(Capability.TEXT), [])

        self.run_command('--apply')

        candidates = AIRouter(self.workspace)._candidates(Capability.TEXT)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['route'].provider.key, 'gemini')
