"""
The queued generation path, end to end and honestly.

Every poster now generates on the queue, so this path stopped being the
long-tail fallback and became the product. Three things are proved:

* The task can actually write its result. The result row's foreign key is
  `generation_request`, and the task called `update_or_create(request=...)` —
  a FieldError on every run, raised AFTER the provider had been paid and the
  draft persisted. The worker then retried up to three times, paying and
  persisting again each round, and the request ended FAILED. Queued carousel
  and video generation had never completed successfully.
* A completed task is not re-run. Task queues re-deliver; without the guard a
  re-delivery would spend provider money again and leave a duplicate draft.
* The queued draft carries the same generation_trace as a synchronous one,
  because the learning-usage report reads exactly that key — a poster made on
  the queue must not vanish from "is this rule reaching the work?".
"""
import json
from unittest.mock import patch

from django.test import TestCase

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.content.models import ContentItem
from apps.gemini.models import GeminiGenerationRequest, GeminiGenerationResult
from apps.gemini.tasks import generate_content
from apps.workspaces.models import WorkspaceMember

ROUTED = {
    'payload': {
        'postTitle': 'Roasted this week',
        'postDescription': 'Beans that were green on Monday.',
        'postHashtags': '#coffee',
        'posterImageUrl': 'https://storage.test/generated/poster.png',
    },
    'provider': 'gemini',
    'provider_name': 'Gemini',
    'brain_version': '',
}


class AsyncGenerationTaskTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.user, _ = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.EDITOR, 'editor@acme.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', is_default=True,
            status=Brand.Status.ACTIVE,
        )

    def a_request(self):
        return GeminiGenerationRequest.objects.create(
            workspace=self.workspace,
            user=self.user,
            prompt_data=json.dumps({'campaign_name': 'Launch', 'contentType': 'poster'}),
            status=GeminiGenerationRequest.Status.PENDING,
        )

    def run_task(self, request, routed=None):
        payload = dict(routed or ROUTED)
        payload.setdefault('brain_version', self.brand.brain_version or '')
        # Patched at its source: the task imports it lazily inside the
        # function body, so the module attribute does not exist to patch.
        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=payload,
        ) as dispatched:
            # The task function is wrapped by the queue decorator; call the
            # underlying callable the worker would call.
            generate_content.func(str(request.pk))
        return dispatched

    def test_the_result_is_written_and_the_request_completes(self):
        request = self.a_request()
        self.run_task(request)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.COMPLETED)

        # The line that used to raise FieldError: the row exists, under the
        # field's real name, carrying what the poll endpoint serves.
        result = GeminiGenerationResult.objects.get(generation_request=request)
        self.assertEqual(result.generated_text, 'Beans that were green on Monday.')
        self.assertEqual(
            result.generated_asset_url, 'https://storage.test/generated/poster.png'
        )
        self.assertEqual(result.metadata['postTitle'], 'Roasted this week')
        self.assertTrue(result.metadata['contentItemId'])

    def test_a_completed_request_is_never_generated_twice(self):
        request = self.a_request()
        first = self.run_task(request)
        self.assertEqual(first.call_count, 1)

        # Re-delivery of the same task id: no second provider call, no
        # second draft, and the result row is untouched.
        second = self.run_task(request)
        self.assertEqual(second.call_count, 0)
        self.assertEqual(ContentItem.objects.filter(workspace=self.workspace).count(), 1)
        self.assertEqual(
            GeminiGenerationResult.objects.filter(generation_request=request).count(), 1
        )

    def test_the_queued_draft_is_attributable_like_a_synchronous_one(self):
        from apps.brands.services.brand_brain import rebuild_brand_brain
        from apps.learning.models import LearningScope
        from apps.learning.services import create_explicit_rule

        create_explicit_rule(
            workspace=self.workspace, brand=self.brand,
            text='Never call the coffee cheap.', scope=LearningScope.BRAND,
            created_by=self.user,
        )
        rebuild_brand_brain(self.brand)
        self.brand.refresh_from_db()

        request = self.a_request()
        self.run_task(
            request, routed={**ROUTED, 'brain_version': self.brand.brain_version}
        )

        item = ContentItem.objects.get(workspace=self.workspace)
        trace = (item.layout_config or {}).get('generation_trace') or {}
        self.assertEqual(trace.get('brain_version'), self.brand.brain_version)
        self.assertTrue(
            trace.get('rule_ids'),
            'a queued generation must name the rules it read, or the '
            'learning-usage report undercounts everything made on the queue',
        )
