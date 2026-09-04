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
                Capability.RESEARCH,
                Capability.ENGAGEMENT_RESPONSE,
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
    def test_subject_focus_goes_through_the_structured_schema_path(self, post):
        """SUBJECT_FOCUS must honour the supplied response schema — routed to
        the generic campaign-analysis branch it would be a paid call whose
        shape the caller permanently caches as a MALFORMED skip."""
        payload = {
            'focal': {'x': 0.4, 'y': 0.3},
            'subject_bbox': [0.1, 0.1, 0.8, 0.9],
            'has_face': True,
        }
        post.return_value = responses_json(payload)
        schema = {
            'type': 'object',
            'properties': {'focal': {'type': 'object'}},
            'required': ['focal'],
        }

        result = OpenAIAdapter(credentials='workspace-test-key').analyze_image({
            'task': 'SUBJECT_FOCUS',
            'instruction': 'Locate the main subject.',
            'response_schema': schema,
            'reference_image_base64': 'aW1hZ2UtYnl0ZXM=',
            'reference_image_mime_type': 'image/jpeg',
        })

        self.assertEqual(result['analysis'], payload)
        _url, kwargs = post.call_args
        fmt = kwargs['json']['text']['format']
        self.assertEqual(fmt['type'], 'json_schema')
        self.assertEqual(fmt['name'], 'scaleezy_subject_focus')
        self.assertEqual(fmt['schema'], schema)
        content = kwargs['json']['input'][0]['content']
        self.assertEqual(content[0]['text'], 'Locate the main subject.')
        self.assertEqual(content[1]['type'], 'input_image')

        # Without a schema the call is refused BEFORE any spend.
        post.reset_mock()
        with self.assertRaises(AIProviderError):
            OpenAIAdapter(credentials='workspace-test-key').analyze_image({
                'task': 'SUBJECT_FOCUS',
                'reference_image_base64': 'aW1hZ2UtYnl0ZXM=',
            })
        post.assert_not_called()

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
    def test_research_requires_and_records_a_real_web_search_call(self, post):
        upstream = responses_json({
            'findings': [{
                'title': 'Retail launch',
                'source_url': 'https://example.test/campaign',
                'preview_url': '',
                'source_name': 'Example',
                'platform': 'Web',
                'kind': 'CAMPAIGN',
                'excerpt': 'A public campaign reference.',
                'observed_at': '',
            }],
        })
        upstream.json.return_value['output'].insert(0, {
            'type': 'web_search_call', 'id': 'ws_test', 'status': 'completed',
        })
        post.return_value = upstream

        result = OpenAIAdapter(credentials='workspace-test-key').research({
            'query': 'premium retail launch posters',
        })

        self.assertTrue(result['raw']['web_search_used'])
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['tools'][0]['type'], 'web_search')
        self.assertFalse(payload['store'])
        self.assertEqual(payload['text']['format']['type'], 'json_schema')

    @patch('apps.ai.adapters.openai.httpx.post')
    def test_research_refuses_model_memory_without_web_search(self, post):
        post.return_value = responses_json({'findings': []})

        with self.assertRaisesMessage(
            AIProviderError,
            'OpenAI returned research without using live web search.',
        ):
            OpenAIAdapter(credentials='workspace-test-key').research({'query': 'current'})

    @patch('apps.ai.adapters.openai.httpx.post')
    def test_engagement_draft_is_structured_and_never_sent(self, post):
        post.return_value = responses_json({
            'reply': 'Thanks for reaching out — we will check this with the team.',
            'sentiment': 'NEGATIVE',
            'urgency': 'HIGH',
            'risk_flags': ['refund_request'],
        })

        result = OpenAIAdapter(credentials='workspace-test-key').draft_engagement_response({
            'message': 'Where is my refund?',
        })

        self.assertEqual(result['urgency'], 'HIGH')
        self.assertEqual(result['risk_flags'], ['refund_request'])
        self.assertEqual(post.call_args.args[0], 'https://api.openai.test/v1/responses')

    @patch('apps.ai.adapters.openai.httpx.get')
    @patch('apps.ai.adapters.openai.httpx.post')
    def test_missing_key_fails_before_http_and_health_check_is_not_paid(self, post, get):
        adapter = OpenAIAdapter()

        with self.assertRaisesMessage(AIProviderError, 'No OpenAI API key configured.'):
            adapter.generate_text({})
        self.assertEqual(
            adapter.health_check(),
            {'ok': False, 'detail': 'No OpenAI API key configured.'},
        )
        post.assert_not_called()
        get.assert_not_called()

    @patch('apps.ai.adapters.openai.httpx.get')
    def test_health_check_authenticates_without_running_a_generation(self, get):
        get.return_value = response({'data': []})
        result = OpenAIAdapter(credentials='workspace-test-key').health_check()

        self.assertTrue(result['ok'])
        self.assertIn('Connected', result['detail'])
        url, kwargs = get.call_args
        self.assertEqual(url[0], 'https://api.openai.test/v1/models')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer workspace-test-key')
        self.assertNotIn('workspace-test-key', result['detail'])

    @patch('apps.ai.adapters.openai.httpx.get')
    def test_health_check_sanitizes_invalid_credentials(self, get):
        upstream_secret = 'upstream-echoed-secret'
        failed = response({'error': {'message': upstream_secret}}, status_code=401)
        failed.text = upstream_secret
        get.return_value = failed

        result = OpenAIAdapter(credentials='bad-key').health_check()

        self.assertFalse(result['ok'])
        self.assertEqual(result['detail'], 'OpenAI authentication failed.')
        self.assertNotIn(upstream_secret, str(result))
        self.assertNotIn('bad-key', str(result))

    @patch('apps.ai.adapters.openai.httpx.get')
    def test_health_check_reports_timeout_without_raising(self, get):
        get.side_effect = httpx.TimeoutException('private timeout detail')

        result = OpenAIAdapter(credentials='workspace-test-key').health_check()

        self.assertEqual(result, {'ok': False, 'detail': 'OpenAI health check timed out.'})

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
        self.assertEqual(
            set(openai.capabilities),
            {
                Capability.TEXT,
                Capability.IMAGE,
                Capability.IMAGE_ANALYSIS,
                Capability.IMAGE_CAPTION,
                Capability.EMBEDDING,
            },
        )
        self.assertFalse(
            WorkspaceAIProvider.objects.filter(
                workspace=workspace, provider=openai
            ).exists()
        )

    def test_capability_migration_adds_only_real_live_web_research(self):
        workspace = MarketingWorkspace.objects.create(
            customer_id='capability-existing', workspace_name='Capability tenant'
        )
        openai = AIProvider.objects.get(key='openai')
        gemini = AIProvider.objects.get(key='gemini')
        configured_openai = WorkspaceAIProvider.objects.create(
            workspace=workspace,
            provider=openai,
            capabilities=[Capability.TEXT],
        )
        configured_gemini = WorkspaceAIProvider.objects.create(
            workspace=workspace,
            provider=gemini,
            capabilities=[Capability.TEXT],
        )
        migration = importlib.import_module(
            'apps.ai.migrations.0010_research_engagement_capabilities'
        )

        migration.add_real_capabilities(django_apps, None)

        openai.refresh_from_db()
        gemini.refresh_from_db()
        configured_openai.refresh_from_db()
        configured_gemini.refresh_from_db()
        self.assertIn(Capability.RESEARCH, openai.capabilities)
        self.assertNotIn(Capability.RESEARCH, gemini.capabilities)
        self.assertIn(Capability.ENGAGEMENT_RESPONSE, gemini.capabilities)
        self.assertIn(Capability.RESEARCH, configured_openai.capabilities)
        self.assertNotIn(Capability.RESEARCH, configured_gemini.capabilities)
        self.assertFalse(
            WorkspaceAIRoute.objects.filter(
                workspace=workspace, provider=openai
            ).exists()
        )
