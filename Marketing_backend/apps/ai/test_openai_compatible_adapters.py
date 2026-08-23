"""Contract tests for the shared chat-completions provider family."""
import importlib
import json
from unittest.mock import Mock, patch

import httpx
from django.apps import apps as django_apps
from django.test import SimpleTestCase, TestCase, override_settings

from apps.ai.adapters.base import AIProviderError
from apps.ai.adapters.openai_compatible import (
    DeepSeekAdapter,
    GroqAdapter,
    MistralAdapter,
    OpenRouterAdapter,
    TogetherAdapter,
)
from apps.ai.models import AIProvider, Capability
from apps.ai.registry import get_adapter_class


def response(payload, status_code=200):
    result = Mock(status_code=status_code)
    result.json.return_value = payload
    return result


class OpenAICompatibleAdapterTests(SimpleTestCase):
    def test_all_installed_providers_are_discoverable_and_text_only(self):
        adapters = {
            'groq': GroqAdapter,
            'mistral': MistralAdapter,
            'deepseek': DeepSeekAdapter,
            'openrouter': OpenRouterAdapter,
            'together': TogetherAdapter,
        }

        for key, adapter_class in adapters.items():
            with self.subTest(key=key):
                self.assertIs(get_adapter_class(key), adapter_class)
                self.assertEqual(tuple(adapter_class.capabilities), (Capability.TEXT,))
                self.assertTrue(adapter_class.base_url.startswith('https://'))
                self.assertNotIn('{', adapter_class.base_url)

    @override_settings(AI_PROVIDER_REQUEST_TIMEOUT=7.0)
    @patch('apps.ai.adapters.openai_compatible.httpx.post')
    def test_generation_normalizes_chat_completion_without_leaking_key(self, post):
        post.return_value = response({
            'id': 'completion-test',
            'model': 'mistral-small-latest',
            'choices': [{
                'message': {
                    'content': json.dumps({
                        'headline': 'Fresh today',
                        'caption': 'Roasted for your morning.',
                        'hashtags': '#fresh #coffee',
                    }),
                },
            }],
        })
        adapter = MistralAdapter(credentials='workspace-test-key')

        result = adapter.generate_text({'hard_rules': ['Never call it instant coffee.']})

        self.assertEqual(result['headline'], 'Fresh today')
        self.assertEqual(result['caption'], 'Roasted for your morning.')
        self.assertEqual(result['hashtags'], '#fresh #coffee')
        self.assertEqual(post.call_args.args[0], 'https://api.mistral.ai/v1/chat/completions')
        self.assertEqual(
            post.call_args.kwargs['headers']['Authorization'],
            'Bearer workspace-test-key',
        )
        self.assertEqual(post.call_args.kwargs['timeout'], 7.0)
        self.assertNotIn('workspace-test-key', json.dumps(post.call_args.kwargs['json']))
        self.assertNotIn('workspace-test-key', json.dumps(result))

    @patch('apps.ai.adapters.openai_compatible.httpx.get')
    def test_health_check_is_authenticated_and_read_only(self, get):
        get.return_value = response({'data': []})

        result = GroqAdapter(credentials='workspace-test-key').health_check()

        self.assertTrue(result['ok'])
        self.assertEqual(get.call_args.args[0], 'https://api.groq.com/openai/v1/models')
        self.assertEqual(
            get.call_args.kwargs['headers']['Authorization'],
            'Bearer workspace-test-key',
        )

    @patch('apps.ai.adapters.openai_compatible.httpx.get')
    @patch('apps.ai.adapters.openai_compatible.httpx.post')
    def test_missing_key_stops_before_network(self, post, get):
        adapter = OpenRouterAdapter()

        with self.assertRaisesMessage(
            AIProviderError,
            'OpenRouter API key is not configured.',
        ):
            adapter.generate_text({})

        self.assertEqual(
            adapter.health_check(),
            {'ok': False, 'detail': 'OpenRouter API key is not configured.'},
        )
        post.assert_not_called()
        get.assert_not_called()

    @patch('apps.ai.adapters.openai_compatible.httpx.post')
    def test_upstream_auth_error_is_sanitized(self, post):
        upstream_secret = 'provider-echoed-private-prompt'
        failed = response({'error': upstream_secret}, status_code=401)
        failed.text = upstream_secret
        post.return_value = failed

        with self.assertRaises(AIProviderError) as caught:
            TogetherAdapter(credentials='workspace-test-key').generate_text({
                'private': upstream_secret,
            })

        self.assertEqual(str(caught.exception), 'Together AI authentication failed.')
        self.assertNotIn(upstream_secret, str(caught.exception))
        self.assertNotIn('workspace-test-key', str(caught.exception))

    @patch('apps.ai.adapters.openai_compatible.httpx.post')
    def test_transport_error_is_sanitized(self, post):
        post.side_effect = httpx.ReadTimeout('contains-network-detail')

        with self.assertRaisesMessage(AIProviderError, 'DeepSeek request timed out.'):
            DeepSeekAdapter(credentials='workspace-test-key').generate_text({})


class OpenAICompatibleCatalogueMigrationTests(TestCase):
    def test_seed_is_idempotent_and_preserves_global_kill_switch(self):
        AIProvider.objects.update_or_create(
            key='groq',
            defaults={
                'display_name': 'Old Groq',
                'capabilities': [],
                'default_model': 'old-model',
                'unit_cost': 0,
                'is_available': False,
            },
        )
        migration = importlib.import_module(
            'apps.ai.migrations.0007_seed_openai_compatible_providers'
        )

        migration.seed_openai_compatible_providers(django_apps, None)
        migration.seed_openai_compatible_providers(django_apps, None)

        expected = {'groq', 'mistral', 'deepseek', 'openrouter', 'together'}
        self.assertTrue(expected.issubset(
            set(AIProvider.objects.values_list('key', flat=True))
        ))
        groq = AIProvider.objects.get(key='groq')
        self.assertEqual(groq.display_name, 'Groq')
        self.assertEqual(groq.capabilities, ['TEXT'])
        self.assertEqual(groq.default_model, 'openai/gpt-oss-20b')
        self.assertFalse(groq.is_available)
