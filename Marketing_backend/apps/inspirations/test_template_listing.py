"""
Black-box pins for the "Your templates" picker's list query.

Create Studio once showed an empty template list for a brand that held two
BRAND_TEMPLATE rows. Every way that list could come back short is pinned here
through the public endpoint alone, so the picker and the generation-time
rotation cannot drift apart unnoticed:

* the `inspiration_type` filter is applied on the server, over the full row
  set, so the templates arrive on the first page however many other
  inspirations the brand holds and wherever ordering puts them;
* the default (unpaginated) response carries every row, which is what the
  ambassador and product pickers still rely on when they sift client-side
  (the templates picker now asks by type);
* brand scoping comes only from the `brand_id` the caller names; the server
  never narrows to a workspace default brand;
* a template is listed whatever its analysis state; only archiving removes it
  from the eligible set, and that set is exactly what the rotation reads;
* an unauthorised or ambiguous workspace is refused (403), never answered
  with an empty 200 that a client would render as "no templates".
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.workspaces.models import WorkspaceMember

from .models import BrandInspiration

INSPIRATIONS_URL = '/api/marketing/inspirations/'
Type = BrandInspiration.InspirationType
TEMPLATE = Type.BRAND_TEMPLATE
TEMPLATE_QUERY = 'inspiration_type=BRAND_TEMPLATE'

#: More non-template rows than any page a caller would ask for, so a filter
#: that was quietly ignored could not pass by luck.
FILLER_ROWS = 30
FILLER_TYPES = (
    Type.BRAND_AMBASSADOR, Type.BRAND_PRODUCT, Type.IMAGE, Type.POST,
    Type.REFERENCE, Type.TEXT, Type.COMPETITOR, Type.AD,
)
UPLOAD_TYPES = (TEMPLATE, Type.BRAND_AMBASSADOR, Type.BRAND_PRODUCT)


def rows_of(response):
    """The list, whether the server sent a bare array or a page envelope."""
    body = response.json()
    return body['results'] if isinstance(body, dict) else body


def ids_of(response):
    return sorted(str(row['id']) for row in rows_of(response))


def pks_of(rows):
    return sorted(str(row.pk) for row in rows)


class TemplateListingTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Sumaya', 'sumaya')
        self.user, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'sumaya-admin'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Sumaya', is_default=True
        )
        self.other_brand = Brand.objects.create(
            workspace=self.workspace, name='Sumaya Kids'
        )

        # Templates first, then pushed a year into the past: the model orders
        # by '-created_at', so an unfiltered listing puts them LAST, behind
        # every filler row, and a first page that ignored the type filter
        # would never reach them.
        self.templates = [
            self.make_row(self.brand, TEMPLATE, 'Sumaya poster A'),
            self.make_row(self.brand, TEMPLATE, 'Sumaya poster B'),
        ]
        self.other_template = self.make_row(self.other_brand, TEMPLATE, 'Kids poster')
        BrandInspiration.objects.filter(inspiration_type=TEMPLATE).update(
            created_at=timezone.now() - timedelta(days=365)
        )
        for index in range(FILLER_ROWS):
            self.make_row(
                self.brand, FILLER_TYPES[index % len(FILLER_TYPES)], f'Filler {index}'
            )

    def make_row(self, brand, inspiration_type, title, **overrides):
        fields = {
            'workspace': self.workspace,
            'brand': brand,
            'inspiration_type': inspiration_type,
            'title': title,
            'created_by': self.user,
        }
        slug = title.replace(' ', '-').lower()
        if inspiration_type in UPLOAD_TYPES:
            # Uploads: a re-hosted file, no reference URL, no source row.
            fields.update(
                file_url=f'https://storage.test/{self.workspace.pk}/{slug}.png',
                storage_path=f'inspirations/{self.workspace.pk}/{slug}.png',
                mime_type='image/png',
                file_name=f'{slug}.png',
            )
        else:
            fields['reference_url'] = f'https://example.com/{slug}'
        fields.update(overrides)
        return BrandInspiration.objects.create(**fields)

    def get(self, query, client=None, workspace=None):
        return (client or self.api).get(
            f'{INSPIRATIONS_URL}?{query}',
            **workspace_header(workspace or self.workspace),
        )

    # --- the filter ---------------------------------------------------------

    def test_type_filter_is_applied_server_side_and_survives_any_page_size(self):
        template_ids = pks_of(self.templates)

        # The fixture is adversarial on purpose: without the filter the first
        # 25 rows hold no template at all. Whatever the picker gets, it gets
        # because the server filtered, not because the page was big enough.
        unfiltered = self.get(f'brand_id={self.brand.pk}&page_size=25')
        self.assertEqual(unfiltered.status_code, status.HTTP_200_OK, unfiltered.content[:300])
        self.assertEqual(unfiltered.json()['count'], FILLER_ROWS + 2)
        self.assertFalse(set(template_ids) & set(ids_of(unfiltered)))

        listed = self.get(f'brand_id={self.brand.pk}&{TEMPLATE_QUERY}')
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.content[:300])
        self.assertIsInstance(listed.json(), list, 'no page_size: a bare array')
        self.assertEqual(ids_of(listed), template_ids)

        # A caller that does page gets both on page one, and nothing further.
        paged = self.get(f'brand_id={self.brand.pk}&{TEMPLATE_QUERY}&page_size=10')
        body = paged.json()
        self.assertEqual(body['count'], 2)
        self.assertIsNone(body['next'])
        self.assertEqual(ids_of(paged), template_ids)

    def test_unknown_or_compound_type_value_never_falls_back_to_everything(self):
        # The failure that would bury templates behind a page of ambassadors
        # and references is a filter value the server ignores. It must not:
        # a value it does not understand matches nothing, and a compound one
        # matches at most the types it names.
        unknown = self.get(f'brand_id={self.brand.pk}&inspiration_type=NOT_A_TYPE')
        self.assertEqual(unknown.status_code, status.HTTP_200_OK)
        self.assertEqual(rows_of(unknown), [])

        compound = self.get(
            f'brand_id={self.brand.pk}&inspiration_type=BRAND_TEMPLATE,BRAND_AMBASSADOR'
        )
        self.assertEqual(compound.status_code, status.HTTP_200_OK)
        # An exact-match filter: a comma list names no type, so nothing comes
        # back - never the whole brand.
        self.assertEqual(rows_of(compound), [])

    # --- the shipped caller ---------------------------------------------------

    def test_default_response_is_the_whole_brand_so_a_client_side_pick_still_finds_templates(self):
        # What the ambassador and product pickers send: brand only, no type,
        # no page (the templates picker asks by type since PR #58).
        listed = self.get(f'brand_id={self.brand.pk}')
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.content[:300])
        rows = listed.json()
        self.assertIsInstance(rows, list, 'no page_size: a bare array, never an envelope')
        self.assertEqual(len(rows), FILLER_ROWS + 2)
        templates = [row for row in rows if row['inspiration_type'] == TEMPLATE]
        self.assertEqual(sorted(row['id'] for row in templates), pks_of(self.templates))
        # And they are the LAST rows, newest first, which is exactly why a
        # server that paginated by default would have hidden them.
        self.assertEqual([row['inspiration_type'] for row in rows[-2:]], [TEMPLATE, TEMPLATE])

    # --- brand scoping ------------------------------------------------------

    def test_brand_scoping_comes_from_brand_id_not_a_workspace_default(self):
        # The second brand's template is reachable by naming that brand ...
        kids = self.get(f'brand_id={self.other_brand.pk}&{TEMPLATE_QUERY}')
        self.assertEqual(ids_of(kids), [str(self.other_template.pk)])

        # ... and with no brand named the server does not quietly narrow to
        # the default brand: every template in the workspace is returned.
        whole = self.get(TEMPLATE_QUERY)
        self.assertEqual(ids_of(whole), pks_of([*self.templates, self.other_template]))

    # --- lifecycle: picker and rotation agree ---------------------------------

    def test_analysis_state_never_hides_a_template_and_rotation_reads_the_eligible_set(self):
        from apps.context.services.creative_direction import (
            brand_template_rotation_queryset,
        )

        queued = self.make_row(
            self.brand, TEMPLATE, 'Just uploaded',
            analysis_status=BrandInspiration.AnalysisStatus.QUEUED,
        )
        failed = self.make_row(
            self.brand, TEMPLATE, 'Analysis failed',
            analysis_status=BrandInspiration.AnalysisStatus.FAILED,
        )
        archived = self.make_row(
            self.brand, TEMPLATE, 'Retired',
            lifecycle_status=BrandInspiration.LifecycleStatus.ARCHIVED,
            archived_at=timezone.now(),
        )

        listed = self.get(f'brand_id={self.brand.pk}&{TEMPLATE_QUERY}')
        by_id = {row['id']: row for row in rows_of(listed)}
        # A freshly uploaded or failed analysis is still a template ...
        self.assertIn(str(queued.pk), by_id)
        self.assertIn(str(failed.pk), by_id)
        # ... and the archived one is listed but flagged, so a client can
        # hide it (the picker does) without a second request.
        self.assertEqual(by_id[str(archived.pk)]['lifecycle_status'], 'ARCHIVED')
        self.assertFalse(by_id[str(archived.pk)]['retrieval_eligibility']['eligible'])

        eligible = self.get(f'brand_id={self.brand.pk}&{TEMPLATE_QUERY}&eligible_only=true')
        expected = pks_of([*self.templates, queued, failed])
        self.assertEqual(ids_of(eligible), expected)
        # The generation default rotates over exactly this set.
        self.assertEqual(
            pks_of(brand_template_rotation_queryset(self.workspace, self.brand)),
            expected,
        )

    # --- membership: refused, never emptied -----------------------------------

    def test_viewer_gets_the_templates_and_a_foreign_or_ambiguous_workspace_is_refused(self):
        _viewer, viewer_api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.VIEWER, 'sumaya-viewer'
        )
        listed = self.get(f'brand_id={self.brand.pk}&{TEMPLATE_QUERY}', client=viewer_api)
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.content[:300])
        self.assertEqual(ids_of(listed), pks_of(self.templates))

        # Someone outside the workspace, naming it in the header: refused
        # outright. An empty 200 here would render as "no templates" and
        # send the user hunting for a problem in their uploads.
        elsewhere = self.make_workspace('Elsewhere', 'elsewhere')
        _outsider, outsider_api = self.authenticate_as(
            elsewhere, WorkspaceMember.Role.ADMIN, 'outsider'
        )
        refused = self.get(f'brand_id={self.brand.pk}&{TEMPLATE_QUERY}', client=outsider_api)
        self.assertEqual(refused.status_code, status.HTTP_403_FORBIDDEN)

        # Header and query naming different workspaces: refused, not emptied.
        mismatched = self.api.get(
            f'{INSPIRATIONS_URL}?brand_id={self.brand.pk}&{TEMPLATE_QUERY}'
            f'&workspace_id={elsewhere.pk}',
            **workspace_header(self.workspace),
        )
        self.assertEqual(mismatched.status_code, status.HTTP_403_FORBIDDEN)

        # A multi-workspace member whose client forgot the header: the server
        # cannot pick for them, and says so rather than answering with [].
        WorkspaceMember.objects.create(
            workspace=elsewhere, user=self.user, role=WorkspaceMember.Role.ADMIN
        )
        headerless = self.api.get(f'{INSPIRATIONS_URL}?brand_id={self.brand.pk}&{TEMPLATE_QUERY}')
        self.assertEqual(headerless.status_code, status.HTTP_403_FORBIDDEN)
