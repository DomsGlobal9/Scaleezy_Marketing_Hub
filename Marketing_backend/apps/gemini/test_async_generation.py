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


REVISED = {
    'payload': {
        'postTitle': 'Sharper teal drop',
        'postDescription': 'Rewritten after your notes.',
        'postHashtags': '#saree',
        'posterImageUrl': 'https://storage.test/generated/take-two.png',
        'metadata': {
            'generated_image': {
                'image_url': 'https://storage.test/generated/take-two.png',
            },
        },
    },
    'provider': 'openai',
    'provider_name': 'OpenAI',
    'brain_version': '',
}


class RevisionRegenerationTests(TenantFixtureMixin, TestCase):
    """'Request edits' queues a regeneration that applies the feedback.

    Before this, the action archived the reviewed version and opened an
    identical copy — the reviewer's note, tags and fix request drove nothing,
    and "nothing happens after I request edits" was literally true.
    """

    def setUp(self):
        from apps.feedback.models import Feedback
        from apps.feedback.services import capture

        self.workspace = self.make_workspace('Acme', 'c1')
        self.manager, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.MANAGER, 'manager@acme.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Sarees', is_default=True,
            status=Brand.Status.ACTIVE,
        )
        self.parent = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand,
            status=ContentItem.Status.NEEDS_EDITS,
            headline='Drape yourself in teal', cta='30% OFF',
            review_note='Logo hides the border work.',
        )
        capture(
            content_item=self.parent, user=self.manager,
            verdict=Feedback.Verdict.NEEDS_EDITS,
            element_keys=['logo_placement'],
            feedback_text='Logo hides the border work.',
            fix_request='Move the logo to the top left.',
            learn=False,
        )
        self.revision = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand,
            status=ContentItem.Status.DRAFT, version=2, parent=self.parent,
            headline='Drape yourself in teal', caption='Original caption.',
            layout_config={'regenerating': True},
        )

    def regenerate(self, *, side_effect=None):
        from apps.gemini.tasks import regenerate_revision

        kwargs = (
            {'side_effect': side_effect}
            if side_effect is not None
            else {'return_value': dict(REVISED)}
        )
        with patch(
            'apps.context.services.generation.generate_marketing_payload', **kwargs
        ) as dispatched:
            regenerate_revision.func(str(self.revision.pk))
        return dispatched

    def test_the_feedback_becomes_the_instruction_and_the_revision_is_rewritten(self):
        from apps.marketing.models import MarketingAsset

        dispatched = self.regenerate()

        instruction = dispatched.call_args.kwargs['instruction']
        self.assertIn('Move the logo to the top left', instruction)
        self.assertIn('Logo placement', instruction)
        self.assertIn('Logo hides the border work', instruction)

        self.revision.refresh_from_db()
        self.assertEqual(self.revision.headline, 'Sharper teal drop')
        self.assertEqual(self.revision.caption, 'Rewritten after your notes.')
        self.assertNotIn('regenerating', self.revision.layout_config)
        # The new photograph was made durable, then composed over: the card
        # shows a poster with the copy on it, and the photo is the source.
        self.assertEqual(self.revision.asset.source, MarketingAsset.Source.COMPOSED)
        self.assertTrue(
            self.revision.preview_url.startswith('https://storage.test/composed/'),
            self.revision.preview_url,
        )
        source = MarketingAsset.objects.get(
            pk=self.revision.layout_config['source_asset']
        )
        self.assertEqual(
            source.file_url, 'https://storage.test/generated/take-two.png'
        )

    def test_a_failed_regeneration_leaves_the_editable_copy(self):
        self.regenerate(side_effect=RuntimeError('provider down'))

        self.revision.refresh_from_db()
        self.assertEqual(self.revision.headline, 'Drape yourself in teal')
        self.assertEqual(self.revision.caption, 'Original caption.')
        # The marker never lingers: a card must not claim to be regenerating
        # after the attempt has already failed.
        self.assertNotIn('regenerating', self.revision.layout_config)

    def test_request_edits_queues_the_regeneration(self):
        from apps.common.testing import workspace_header

        pending = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand,
            status=ContentItem.Status.PENDING_REVIEW,
            headline='Second look', cta='30% OFF',
        )
        # The task object itself is frozen; replace the module attribute the
        # view imports instead.
        with patch('apps.gemini.tasks.regenerate_revision') as task_mock:
            res = self.api.post(
                f'/api/marketing/content/{pending.id}/request-edits/',
                {'note': 'colours are off'},
                format='json',
                **workspace_header(self.workspace),
            )

        self.assertEqual(res.status_code, 200, res.content[:300])
        body = res.json()['data']
        self.assertTrue(body['regeneration_queued'])
        revision = ContentItem.objects.get(parent=pending)
        task_mock.enqueue.assert_called_once_with(str(revision.pk))
        self.assertTrue(revision.layout_config.get('regenerating'))
