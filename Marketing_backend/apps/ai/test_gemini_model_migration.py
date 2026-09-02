import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from apps.ai.models import AIProvider, WorkspaceAIProvider
from apps.workspaces.models import MarketingWorkspace


class GeminiModelMigrationTests(TestCase):
    def test_retired_defaults_and_overrides_are_refreshed_without_touching_custom_models(self):
        provider, _created = AIProvider.objects.update_or_create(
            key='gemini',
            defaults={
                'display_name': 'Google Gemini',
                'capabilities': ['TEXT'],
                'default_model': 'gemini-1.5-pro',
            },
        )
        retired_workspace = MarketingWorkspace.objects.create(
            customer_id='retired-model', workspace_name='Retired model'
        )
        custom_workspace = MarketingWorkspace.objects.create(
            customer_id='custom-model', workspace_name='Custom model'
        )
        retired = WorkspaceAIProvider.objects.create(
            workspace=retired_workspace,
            provider=provider,
            model_override='gemini-1.5-pro',
        )
        custom = WorkspaceAIProvider.objects.create(
            workspace=custom_workspace,
            provider=provider,
            model_override='gemini-2.5-pro',
        )

        migration = importlib.import_module(
            'apps.ai.migrations.0012_refresh_gemini_model'
        )
        migration.refresh_gemini_model(django_apps, None)
        migration.refresh_gemini_model(django_apps, None)

        provider.refresh_from_db()
        retired.refresh_from_db()
        custom.refresh_from_db()
        self.assertEqual(provider.default_model, 'gemini-2.5-flash')
        self.assertEqual(retired.model_override, 'gemini-2.5-flash')
        self.assertEqual(custom.model_override, 'gemini-2.5-pro')
