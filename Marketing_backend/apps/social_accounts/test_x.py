from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.social_accounts.integrations.x import XAdapter


class XEngagementAdapterTests(SimpleTestCase):
    def setUp(self):
        self.adapter = XAdapter()

    @patch('apps.social_accounts.integrations.x.requests.get')
    def test_fetch_mentions_normalizes_users_and_cursor(self, get):
        response = MagicMock(ok=True, status_code=200)
        response.json.return_value = {
            'data': [{
                'id': 'tweet-1',
                'author_id': 'author-1',
                'conversation_id': 'conversation-1',
                'text': 'Can you help?',
                'created_at': '2026-09-01T10:00:00Z',
            }],
            'includes': {'users': [{
                'id': 'author-1', 'name': 'Customer', 'username': 'customer',
            }]},
            'meta': {'next_token': 'next-page'},
        }
        get.return_value = response

        result = self.adapter.fetch_mentions('token', 'user-1', cursor='page-1')

        self.assertEqual(result['cursor'], 'next-page')
        self.assertEqual(result['items'][0]['external_id'], 'tweet-1')
        self.assertEqual(result['items'][0]['author_handle'], 'customer')
        self.assertEqual(result['items'][0]['kind'], 'MENTION')
        self.assertEqual(get.call_args.kwargs['params']['pagination_token'], 'page-1')
        self.assertEqual(get.call_args.kwargs['timeout'], 15)

    @patch('apps.social_accounts.integrations.x.requests.post')
    def test_reply_to_post_returns_external_lineage(self, post):
        response = MagicMock(ok=True, status_code=201)
        response.json.return_value = {'data': {'id': 'reply-1'}}
        post.return_value = response

        result = self.adapter.reply_to_post('token', 'tweet-1', 'Happy to help')

        self.assertEqual(result['id'], 'reply-1')
        self.assertEqual(
            post.call_args.kwargs['json']['reply']['in_reply_to_tweet_id'],
            'tweet-1',
        )
        self.assertEqual(post.call_args.kwargs['timeout'], 15)

    @patch('apps.social_accounts.integrations.x.requests.get')
    def test_fetch_post_metrics_normalizes_public_metrics(self, get):
        response = MagicMock(ok=True, status_code=200)
        response.json.return_value = {'data': [{
            'id': 'tweet-1',
            'created_at': '2026-09-01T10:00:00Z',
            'public_metrics': {
                'impression_count': 100,
                'like_count': 4,
                'reply_count': 2,
                'retweet_count': 3,
                'quote_count': 1,
            },
        }]}
        get.return_value = response

        rows = self.adapter.fetch_post_metrics('token', ['tweet-1'])

        self.assertEqual(rows[0]['reach'], 100)
        self.assertEqual(rows[0]['engagement'], 10)
        self.assertEqual(get.call_args.kwargs['params']['tweet.fields'], 'public_metrics,created_at')
