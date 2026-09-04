"""
Client lifecycle: one cached google.genai client per key, discardable, and
the extract path retries exactly once when the transport was closed
underneath a cached client.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.ai.adapters.gemini import GeminiAdapter
from apps.gemini.services.generator import GeminiGeneratorService


@override_settings(GEMINI_API_KEY='server-key')
class ClientCacheTests(TestCase):
    def setUp(self):
        GeminiGeneratorService._client_cache.clear()

    def tearDown(self):
        GeminiGeneratorService._client_cache.clear()

    @patch('apps.gemini.services.generator.genai.Client')
    def test_same_key_reuses_one_client(self, client_cls):
        first = GeminiGeneratorService._get_client('key-a')
        second = GeminiGeneratorService._get_client('key-a')
        self.assertIs(first, second)
        self.assertEqual(client_cls.call_count, 1)

    @patch('apps.gemini.services.generator.genai.Client')
    def test_different_keys_get_different_clients(self, client_cls):
        client_cls.side_effect = lambda **kwargs: MagicMock(name=kwargs['api_key'])
        a = GeminiGeneratorService._get_client('key-a')
        b = GeminiGeneratorService._get_client('key-b')
        self.assertIsNot(a, b)

    @patch('apps.gemini.services.generator.genai.Client')
    def test_discard_forces_a_fresh_client(self, client_cls):
        client_cls.side_effect = lambda **kwargs: MagicMock()
        first = GeminiGeneratorService._get_client('key-a')
        GeminiGeneratorService._discard_client('key-a')
        second = GeminiGeneratorService._get_client('key-a')
        self.assertIsNot(first, second)


@override_settings(GEMINI_API_KEY='server-key')
class ExtractRetryTests(TestCase):
    """The production failure: 'Cannot send a request, as the client has been
    closed', deterministic until a worker restart. The extract path must
    discard the cached client and retry exactly once."""

    def setUp(self):
        GeminiGeneratorService._client_cache.clear()
        self.adapter = GeminiAdapter.__new__(GeminiAdapter)
        self.adapter.credentials = ''
        self.adapter.model = ''

    def tearDown(self):
        GeminiGeneratorService._client_cache.clear()

    def _brief(self):
        return {'task': 'EXTRACT', 'instruction': 'Extract.', 'structured': {'a': 1}}

    @patch('apps.gemini.services.generator.genai.Client')
    def test_closed_client_is_discarded_and_retried_once(self, client_cls):
        closed = MagicMock()
        closed.models.generate_content.side_effect = RuntimeError(
            'Cannot send a request, as the client has been closed.'
        )
        fresh = MagicMock()
        fresh.models.generate_content.return_value = MagicMock(text='{"ok": true}')
        client_cls.side_effect = [closed, fresh]

        result = self.adapter.generate_text(self._brief())
        self.assertEqual(result, {'raw': {'ok': True}})
        self.assertEqual(client_cls.call_count, 2)

    @patch('apps.gemini.services.generator.genai.Client')
    def test_other_errors_do_not_burn_a_retry(self, client_cls):
        broken = MagicMock()
        broken.models.generate_content.side_effect = RuntimeError('quota exceeded')
        client_cls.return_value = broken

        with self.assertRaises(Exception) as caught:
            self.adapter.generate_text(self._brief())
        self.assertIn('quota exceeded', str(caught.exception))
        self.assertEqual(client_cls.call_count, 1)

    @patch('apps.gemini.services.generator.genai.Client')
    def test_second_closed_client_fails_honestly(self, client_cls):
        closed = MagicMock()
        closed.models.generate_content.side_effect = RuntimeError(
            'Cannot send a request, as the client has been closed.'
        )
        client_cls.return_value = closed

        with self.assertRaises(Exception) as caught:
            self.adapter.generate_text(self._brief())
        self.assertIn('client has been closed', str(caught.exception))
        # One retry, not an infinite loop.
        self.assertEqual(closed.models.generate_content.call_count, 2)
