"""
Opt-in pagination: nothing changes until a caller asks for a page.

The point being proved is backwards compatibility, not pagination itself —
four screens read list endpoints as bare arrays, and the review queue counts
its tabs client-side over one unfiltered fetch, so a default envelope would
have broken them silently. A request without `?page_size=` must answer
byte-for-byte as it always has; one with it gets the DRF envelope.
"""
from django.test import TestCase

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.content.models import ContentItem
from apps.workspaces.models import WorkspaceMember

CONTENT_URL = '/api/marketing/content/'


class OptInPaginationTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.user, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.EDITOR, 'editor@acme.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', is_default=True,
            status=Brand.Status.ACTIVE,
        )
        self.headers = workspace_header(self.workspace)
        for n in range(7):
            ContentItem.objects.create(
                workspace=self.workspace, brand=self.brand, headline=f'Post {n}',
            )

    def test_without_a_page_size_the_response_is_the_bare_array_it_always_was(self):
        response = self.api.get(CONTENT_URL, **self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsInstance(body, list, 'existing consumers read this as an array')
        self.assertEqual(len(body), 7)

    def test_naming_a_page_size_opts_into_the_standard_envelope(self):
        response = self.api.get(CONTENT_URL, {'page_size': 3}, **self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['count'], 7)
        self.assertEqual(len(body['results']), 3)
        self.assertIsNotNone(body['next'])
        self.assertIsNone(body['previous'])

        last = self.api.get(CONTENT_URL, {'page_size': 3, 'page': 3}, **self.headers)
        self.assertEqual(last.status_code, 200)
        self.assertEqual(len(last.json()['results']), 1)
        self.assertIsNone(last.json()['next'])

    def test_a_page_walk_sees_every_row_exactly_once(self):
        """Stable ordering: duplicates or gaps across pages are the silent
        failure pagination is famous for, so it is asserted, not assumed."""
        seen = []
        page = 1
        while True:
            response = self.api.get(
                CONTENT_URL, {'page_size': 2, 'page': page}, **self.headers
            )
            body = response.json()
            seen.extend(row['id'] for row in body['results'])
            if not body['next']:
                break
            page += 1
        self.assertEqual(len(seen), 7)
        self.assertEqual(len(set(seen)), 7, 'no row may repeat across pages')

    def test_the_page_size_ceiling_holds(self):
        response = self.api.get(CONTENT_URL, {'page_size': 100000}, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(response.json()['results']), 200)
