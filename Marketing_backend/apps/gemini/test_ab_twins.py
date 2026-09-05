"""A/B twins — the client opts into two deliberately different designs.

The variety LRU is a pure function of history, so two concurrent picks from
the same history converge on the same design. Both briefs are therefore
picked at the view, the twin's with its sibling's keys excluded — the pair
is guaranteed to genuinely differ, and each run bills its own units the
client explicitly opted into.
"""
import json
import uuid

from django.test import TestCase
from rest_framework import status

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.context.services.creative_direction import pick_variety
from apps.gemini.models import GeminiGenerationRequest
from apps.jobs.models import TaskRun
from apps.workspaces.models import WorkspaceMember

GENERATE_ASYNC_URL = '/api/marketing/gemini/generate-async/'


class PickVarietyExclusionTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Twins', 'twins-picks')
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Twins Brand', is_default=True
        )

    def test_a_siblings_picks_are_out_of_the_running(self):
        rid_a, rid_b = uuid.uuid4(), uuid.uuid4()
        first = pick_variety(self.workspace, self.brand, rid_a)
        second = pick_variety(self.workspace, self.brand, rid_b, exclude=first)
        self.assertNotEqual(
            first['composition_archetype'], second['composition_archetype']
        )
        self.assertNotEqual(first['scene_variant'], second['scene_variant'])

    def test_exclusion_never_empties_the_options(self):
        # A junk exclusion dict changes nothing; a real one still returns a
        # pick from the remaining pool.
        rid = uuid.uuid4()
        baseline = pick_variety(self.workspace, self.brand, rid)
        self.assertEqual(
            pick_variety(self.workspace, self.brand, rid, exclude={'x': 'y'}),
            baseline,
        )


class AbTwinEndpointTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Twins client', 'twins-api')
        self.user, self.client = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.ADMIN, 'twins-admin'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Twins Brand', is_default=True
        )

    def post(self, **extra):
        return self.client.post(
            GENERATE_ASYNC_URL,
            {'campaignName': 'Twin launch', 'contentType': 'poster', **extra},
            format='json',
            **workspace_header(self.workspace),
        )

    def test_the_toggle_queues_two_requests_with_disjoint_variety(self):
        response = self.post(abVariants=True)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)
        twin = response.data['data']['twin']
        self.assertIsNotNone(twin)

        rows = {str(r.pk): r for r in GeminiGenerationRequest.objects.all()}
        self.assertEqual(len(rows), 2)
        briefs = [json.loads(r.prompt_data) for r in rows.values()]
        archetypes = {b['composition_archetype'] for b in briefs}
        scenes = {b['scene_variant'] for b in briefs}
        self.assertEqual(len(archetypes), 2, archetypes)
        self.assertEqual(len(scenes), 2, scenes)
        self.assertEqual(
            TaskRun.objects.filter(task_path__endswith='generate_content').count(), 2
        )

    def test_without_the_toggle_nothing_changes(self):
        response = self.post()
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIsNone(response.data['data']['twin'])
        self.assertEqual(GeminiGenerationRequest.objects.count(), 1)
        brief = json.loads(GeminiGenerationRequest.objects.get().prompt_data)
        # The worker still owns the variety pick on a single run.
        self.assertNotIn('composition_archetype', brief)

    def test_a_retry_reusing_the_request_id_finds_the_same_pair(self):
        rid = str(uuid.uuid4())
        first = self.post(abVariants=True, requestId=rid)
        self.assertIsNotNone(first.data['data']['twin'])
        again = self.post(abVariants=True, requestId=rid)
        self.assertEqual(again.status_code, status.HTTP_202_ACCEPTED)
        # The known-request short-circuit re-reads the deterministic twin —
        # a lost HTTP response never loses the pair the client paid for,
        # and nothing new is queued.
        self.assertEqual(
            again.data['data']['twin']['generationId'],
            first.data['data']['twin']['generationId'],
        )
        self.assertEqual(GeminiGenerationRequest.objects.count(), 2)
        self.assertEqual(
            TaskRun.objects.filter(task_path__endswith='generate_content').count(), 2
        )

    def test_the_briefs_name_their_pair_and_slots(self):
        rid = str(uuid.uuid4())
        self.post(abVariants=True, requestId=rid)
        briefs = [
            json.loads(r.prompt_data) for r in GeminiGenerationRequest.objects.all()
        ]
        self.assertEqual({b['ab_group'] for b in briefs}, {rid})
        self.assertEqual({b['ab_slot'] for b in briefs}, {'A', 'B'})

    def test_a_catalogue_template_never_buys_an_identical_twin(self):
        # CATALOG_TEMPLATE posters ignore the variety keys entirely — two
        # runs would be the same poster twice, double-billed.
        response = self.post(
            abVariants=True, creativeMode='CATALOG_TEMPLATE', layout='classic_sale',
        )
        if response.status_code == status.HTTP_202_ACCEPTED:
            self.assertIsNone(response.data['data']['twin'])
            self.assertEqual(GeminiGenerationRequest.objects.count(), 1)
        else:
            # An uninstalled layout refuses before any request row exists —
            # either way, no twin was bought.
            self.assertEqual(GeminiGenerationRequest.objects.count(), 0)

    def test_no_headroom_for_two_means_one_honest_variant(self):
        from unittest.mock import patch

        from apps.billing.quota import Verdict

        with patch(
            'apps.billing.quota.check',
            return_value=Verdict(allowed=True, used=99, limit=100),
        ):
            response = self.post(abVariants=True)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIsNone(response.data['data']['twin'])
        self.assertEqual(GeminiGenerationRequest.objects.count(), 1)

    def test_carousels_and_video_ignore_the_toggle(self):
        response = self.post(abVariants=True, contentType='carousel')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)
        self.assertIsNone(response.data['data']['twin'])
        self.assertEqual(GeminiGenerationRequest.objects.count(), 1)
