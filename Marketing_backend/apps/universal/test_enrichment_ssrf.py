"""
Enrichment's outbound fetcher, under a hostile website.

The property that matters: this server never issues a request to an address
it has not already vetted — not on the first hop, and not on any redirect.
An earlier version let the HTTP client follow redirects and checked the final
URL afterwards, by which time a "302 Location: http://169.254.169.254/" had
already been requested.
"""
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase

from apps.universal import enrichment

PUBLIC = '93.184.216.34'


def resolving(mapping):
    """Patch DNS so `host -> ip` is whatever the test says."""
    def fake_getaddrinfo(host, *args, **kwargs):
        ip = mapping.get(host)
        if ip is None:
            raise OSError('no such host')
        return [(2, 1, 6, '', (ip, 0))]
    return patch('apps.universal.enrichment.socket.getaddrinfo', side_effect=fake_getaddrinfo)


class RecordingTransport(httpx.MockTransport):
    """Remembers every request it was asked to make."""

    def __init__(self, routes):
        self.requests = []
        self.routes = routes  # (host header, path) -> response
        super().__init__(self.handle)

    def handle(self, request):
        self.requests.append(request)
        key = (request.headers.get('host', ''), request.url.path)
        response = self.routes.get(key)
        if response is None:
            return httpx.Response(404, text='missing')
        return response


class SafeFetchRedirectTests(SimpleTestCase):
    def test_redirect_to_metadata_address_is_refused_before_any_request_to_it(self):
        transport = RecordingTransport({
            ('acme.test', '/'): httpx.Response(
                302, headers={'location': 'http://169.254.169.254/latest/meta-data/'}
            ),
        })
        with resolving({'acme.test': PUBLIC}):
            with self.assertRaises(enrichment.UnsafeURL):
                enrichment.safe_fetch(
                    'https://acme.test/', allowed_host='acme.test', transport=transport
                )
        # Exactly one request was made — to the customer's own site. The
        # metadata address was never contacted.
        hosts = [r.headers.get('host') for r in transport.requests]
        self.assertEqual(hosts, ['acme.test'])

    def test_redirect_off_the_brands_host_is_refused(self):
        transport = RecordingTransport({
            ('acme.test', '/'): httpx.Response(
                301, headers={'location': 'https://competitor.test/pricing'}
            ),
        })
        with resolving({'acme.test': PUBLIC, 'competitor.test': PUBLIC}):
            with self.assertRaises(enrichment.UnsafeURL):
                enrichment.safe_fetch(
                    'https://acme.test/', allowed_host='acme.test', transport=transport
                )
        self.assertEqual([r.headers.get('host') for r in transport.requests], ['acme.test'])

    def test_same_host_redirect_is_followed_and_content_returned(self):
        transport = RecordingTransport({
            ('acme.test', '/'): httpx.Response(302, headers={'location': '/about'}),
            ('acme.test', '/about'): httpx.Response(
                200, headers={'content-type': 'text/html'},
                text='<html><body><h1>About Acme</h1><script>x()</script></body></html>',
            ),
        })
        with resolving({'acme.test': PUBLIC}):
            text, digest = enrichment.safe_fetch(
                'https://acme.test/', allowed_host='acme.test', transport=transport
            )
        self.assertIn('About Acme', text)
        self.assertNotIn('x()', text)
        self.assertTrue(digest)
        self.assertEqual(len(transport.requests), 2)

    def test_dns_rebinding_between_hops_is_refused(self):
        # First lookup public, second lookup private: the second hop must be
        # refused before it is requested.
        answers = iter([PUBLIC, PUBLIC, '10.0.0.5', '10.0.0.5'])

        def rebinding(host, *args, **kwargs):
            return [(2, 1, 6, '', (next(answers), 0))]

        transport = RecordingTransport({
            ('acme.test', '/'): httpx.Response(302, headers={'location': '/internal'}),
        })
        with patch('apps.universal.enrichment.socket.getaddrinfo', side_effect=rebinding):
            with self.assertRaises(enrichment.UnsafeURL):
                enrichment.safe_fetch(
                    'https://acme.test/', allowed_host='acme.test', transport=transport
                )
        self.assertEqual(len(transport.requests), 1)

    def test_the_connection_is_pinned_to_the_vetted_address(self):
        transport = RecordingTransport({
            ('acme.test', '/'): httpx.Response(
                200, headers={'content-type': 'text/html'}, text='<p>hi</p>'
            ),
        })
        with resolving({'acme.test': PUBLIC}):
            enrichment.safe_fetch(
                'https://acme.test/', allowed_host='acme.test', transport=transport
            )
        request = transport.requests[0]
        # The client connected to the IP we checked, not to a name it would
        # have resolved itself; the real hostname rides in Host and SNI.
        self.assertEqual(request.url.host, PUBLIC)
        self.assertEqual(request.headers.get('host'), 'acme.test')
        self.assertEqual(request.extensions.get('sni_hostname'), 'acme.test')

    def test_too_many_redirects_is_an_error_not_a_loop(self):
        transport = RecordingTransport({
            ('acme.test', '/loop'): httpx.Response(302, headers={'location': '/loop'}),
        })
        with resolving({'acme.test': PUBLIC}):
            with self.assertRaises(enrichment.EnrichmentError):
                enrichment.safe_fetch(
                    'https://acme.test/loop', allowed_host='acme.test', transport=transport
                )
        self.assertLessEqual(len(transport.requests), enrichment.MAX_REDIRECTS + 1)

    def test_plain_http_first_hop_is_refused_without_a_request(self):
        transport = RecordingTransport({})
        with resolving({'acme.test': PUBLIC}):
            with self.assertRaises(enrichment.UnsafeURL):
                enrichment.safe_fetch(
                    'http://acme.test/', allowed_host='acme.test', transport=transport
                )
        self.assertEqual(transport.requests, [])
