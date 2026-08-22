"""OpenAI adapter contract tests. Every upstream HTTP request is mocked."""
import importlib
import json
from unittest.mock import Mock, patch

import httpx
from django.apps import apps as django_apps
from django.test import SimpleTestCase, TestCase, override_settings

from apps.ai.adapters.base import AIProviderError
from apps.ai.adapters.openai import OpenAIAdapter
from apps.ai.models import (
    AIProvider,
    Capability,
    WorkspaceAIProvider,
    WorkspaceAIRoute,
)
from apps.ai.registry import get_adapter_class
from apps.workspaces.models import MarketingWorkspace


def response(payload, status_code=200):
    result = Mock(status_code=status_code)
    result.json.return_value = payload
    return result


def responses_json(payload, *, response_id='resp_test'):
    return response({
        'id': response_id,
        'model': 'gpt-4.1-mini',
        'output': [{
            'type': 'message',
            'content': [{
                'type': 'output_text',
                'text': json.dumps(payload),
            }],
        }],
    })


@override_settings(
    OPENAI_API_KEY='',
    OPENAI_API_BASE_URL='https://api.openai.test/v1',
    OPENAI_REQUEST_TIMEOUT=7.0,
)
class OpenAIAdapterTests(SimpleTestCase):
    def test_registry_discovers_the_adapter_and_declares_supported_capabilities(self):
        self.assertIs(get_adapter_class('openai'), OpenAIAdapter)
        self.assertEqual(
            set(OpenAIAdapter.capabilities),
            {
                Capability.TEXT,
                Capability.IMAGE,
                Capability.IMAGE_ANALYSIS,
                Capability.IMAGE_CAPTION,
                Capability.EMBEDDING,
            },
        )

    @override_settings(OPENAI_API_KEY='server-should-not-win')
    @patch('apps.ai.adapters.openai.httpx.post')
    def test_text_uses_responses_api_and_workspace_credential_first(self, post):
        post.return_value = responses_json({
            'headline': 'Fresh today',
            'caption': 'Roasted for your morning.',
            'hashtags': '#fresh #coffee',
        })
        adapter = OpenAIAdapter(credentials='workspace-test-key')

        result = adapter.generate_text({'hard_rules': ['Never call it instant coffee.']})

        self.assertEqual(result['headline'], 'Fresh today')
        self.assertEqual(result['caption'], 'Roasted for your morning.')
        self.assertEqual(result['hashtags'], '#fresh #coffee')
        url, kwargs = post.call_args
        self.assertEqual(url[0], 'https://api.openai.test/v1/responses')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer workspace-test-key')
        self.assertEqual(kwargs['timeout'], 7.0)
        self.assertFalse(kwargs['json']['store'])
        self.assertEqual(
            kwargs['json']['text']['format']['type'],
            'json_schema',
        )
        self.assertNotIn('workspace-test-key', json.dumps(kwargs['json']))
        self.assertNotIn('workspace-test-key', json.dumps(result))

    @override_settings(OPENAI_API_KEY='server-test-key')
    @patch('apps.ai.adapters.openai.httpx.post')
    def test_server_credential_is_used_only_when_workspace_has_none(self, post):
        post.return_value = response({
            'model': 'text-embedding-3-small',
            'data': [{'embedding': [0.25, -0.5, 0.75]}],
        })

        result = OpenAIAdapter().generate_embedding({'text': 'clear product feedback'})

        self.assertEqual(result['embedding'], [0.25, -0.5, 0.75])
        self.assertEqual(result['model'], 'text-embedding-3-small')
        url, kwargs = post.call_args
        self.assertEqual(url[0], 'https://api.openai.test/v1/embeddings')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer server-test-key')
        self.assertEqual(kwargs['json']['encoding_format'], 'float')

    @patch('apps.ai.adapters.openai.httpx.post')
    def test_images_api_normalizes_a_hosted_url(self, post):
        post.return_value = response({
            'id': 'img_test',
            'data': [{'url': 'https://images.test/generated.png'}],
        })

        result = OpenAIAdapter(
            credentials='workspace-test-key',
            config={'image_model': 'gpt-image-1', 'image_quality': 'high'},
        ).generate_image({'visual_direction': 'restrained editorial'})

        self.assertEqual(result['image_url'], 'https://images.test/generated.png')
        self.assertTrue(result['image_url_ephemeral'])
        url, kwargs = post.call_args
        self.assertEqual(url[0], 'https://api.openai.test/v1/images/generations')
        self.assertEqual(kwargs['json']['model'], 'gpt-image-1')
        self.assertEqual(kwargs['json']['quality'], 'high')

    @patch('apps.ai.adapters.openai.httpx.post')
    def test_images_api_normalizes_gpt_image_base64_to_a_data_url(self, post):
        post.return_value = response({
            'data': [{'b64_json': 'aW1hZ2UtYnl0ZXM='}],
        })

        result = OpenAIAdapter(credentials='workspace-test-key').generate_image({})

        self.assertEqual(
            result['image_url'],
            'data:image/png;base64,aW1hZ2UtYnl0ZXM=',
        )
        self.assertEqual(result['image_base64'], 'aW1hZ2UtYnl0ZXM=')
        self.assertEqual(result['mime_type'], 'image/png')
        self.assertFalse(result['image_url_ephemeral'])

    @patch('apps.ai.adapters.openai.httpx.post')
    def test_image_analysis_uses_a_responses_multimodal_input(self, post):
        post.return_value = responses_json({
            'campaignName': 'Morning Ritual',
            'product': 'Coffee beans',
            'occasion': 'Everyday',
            'brandTone': 'Minimal',
        })

        result = OpenAIAdapter(credentials='workspace-test-key').analyze_image({
            'reference_image_base64': 'aW1hZ2UtYnl0ZXM=',
            'reference_image_mime_type': 'image/png',
        })

        self.assertEqual(result['analysis']['brandTone'], 'Minimal')
        _url, kwargs = post.call_args
        content = kwargs['json']['input'][0]['content']
        self.assertEqual(content[1]['type'], 'input_image')
        self.assertEqual(
            content[1]['image_url'],
            'data:image/png;base64,aW1hZ2UtYnl0ZXM=',
        )

    @patch('apps.ai.adapters.openai.httpx.post')
    def test_image_caption_uses_responses_and_returns_existing_shape(self, post):
        post.return_value = responses_json({
            'postTitle': 'Start Fresh',
            'postDescription': 'Small-batch coffee for a better morning.',
            'postHashtags': '#coffee #fresh',
        })

        result = OpenAIAdapter(credentials='workspace-test-key').generate_image_captions({
            'referenceImageUrl': 'https://images.test/poster.png',
        })

        self.assertEqual(result['captions']['postTitle'], 'Start Fresh')
        self.assertEqual(post.call_args.args[0], 'https://api.openai.test/v1/responses')

    @patch('apps.ai.adapters.openai.httpx.post')
    def test_missing_key_fails_before_http_and_health_check_is_not_paid(self, post):
        adapter = OpenAIAdapter()

        with self.assertRaisesMessage(AIProviderError, 'No OpenAI API key configured.'):
            adapter.generate_text({})
        self.assertEqual(
            adapter.health_check(),
            {'ok': False, 'detail': 'No OpenAI API key configured.'},
        )
        post.assert_not_called()

    @patch('apps.ai.adapters.openai.httpx.post')
    def test_health_check_reports_configuration_not_connection_success(self, post):
        result = OpenAIAdapter(credentials='workspace-test-key').health_check()

        self.assertTrue(result['ok'])
        self.assertIn('Credential configured', result['detail'])
        self.assertIn('connection not tested', result['detail'])
        post.assert_not_called()

    @patch('apps.ai.adapters.openai.httpx.post')
    def test_provider_errors_are_sanitized(self, post):
        upstream_secret = 'upstream-echoed-private-prompt'
        failed = response({'error': {'message': upstream_secret}}, status_code=401)
        failed.text = upstream_secret
        post.return_value = failed

        with self.assertRaises(AIProviderError) as caught:
            OpenAIAdapter(credentials='workspace-test-key').generate_text({
                'private': upstream_secret,
            })

        self.assertEqual(str(caught.exception), 'OpenAI authentication failed.')
        self.assertNotIn(upstream_secret, str(caught.exception))
        self.assertNotIn('workspace-test-key', str(caught.exception))

    @patch('apps.ai.adapters.openai.httpx.post')
    def test_transport_errors_are_sanitized(self, post):
        post.side_effect = httpx.ReadTimeout('contains-network-detail')

        with self.assertRaisesMessage(AIProviderError, 'OpenAI request timed out.'):
            OpenAIAdapter(credentials='workspace-test-key').generate_text({})


class OpenAICatalogueMigrationTests(TestCase):
    def test_seed_adds_catalogue_only_and_keeps_gemini_cheapest(self):
        workspace = MarketingWorkspace.objects.create(
            customer_id='existing', workspace_name='Existing tenant'
        )
        AIProvider.objects.filter(key='openai').delete()
        migration = importlib.import_module(
            'apps.ai.migrations.0006_seed_openai_provider'
        )

        migration.seed_openai_provider(django_apps, None)

        openai = AIProvider.objects.get(key='openai')
        gemini = AIProvider.objects.get(key='gemini')
        self.assertGreater(openai.unit_cost, gemini.unit_cost)
        self.assertEqual(set(openai.capabilities), set(OpenAIAdapter.capabilities))
        self.assertFalse(
            WorkspaceAIProvider.objects.filter(
                workspace=workspace, provider=openai
            ).exists()
        )
        self.assertFalse(
            WorkspaceAIRoute.objects.filter(
                workspace=workspace, provider=openai
            ).exists()
        )
