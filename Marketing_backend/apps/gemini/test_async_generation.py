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
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.content.models import ContentItem
from apps.gemini.models import GeminiGenerationRequest, GeminiGenerationResult
from apps.gemini.tasks import (
    INTERRUPTED_MESSAGE,
    generate_content,
    sweep_stuck_generations,
)
from apps.jobs.models import TaskRun
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

    def test_a_redelivered_task_never_resurrects_a_failed_request(self):
        # A zombie TaskRun reclaimed half an hour after its worker died, or a
        # queue-level retry, must not flip a failure the user was already
        # shown back to GENERATING and spend provider money on it.
        request = self.a_request()
        request.status = GeminiGenerationRequest.Status.FAILED
        request.error_message = 'provider down'
        request.save(update_fields=['status', 'error_message'])

        dispatched = self.run_task(request)

        self.assertEqual(dispatched.call_count, 0)
        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.FAILED)
        self.assertEqual(request.error_message, 'provider down')
        self.assertEqual(ContentItem.objects.filter(workspace=self.workspace).count(), 0)

    def test_a_generating_request_is_not_claimed_by_a_second_delivery(self):
        # Two deliveries for one request (a rescue racing a reclaimed
        # original): only the run that flips PENDING->GENERATING may spend.
        request = self.a_request()
        request.status = GeminiGenerationRequest.Status.GENERATING
        request.save(update_fields=['status'])

        dispatched = self.run_task(request)

        self.assertEqual(dispatched.call_count, 0)
        self.assertEqual(ContentItem.objects.filter(workspace=self.workspace).count(), 0)

    def test_every_status_transition_restarts_the_stuck_clock(self):
        # The sweep measures "stuck" from updated_at, and auto_now does not
        # fire on queryset updates or unlisted update_fields — so the clock
        # only works if every transition stamps it explicitly. A stale clock
        # here is what let the sweep re-buy generations that were merely
        # waiting in a backlogged queue. The mid-run probe is the load-
        # bearing assertion: the clock must already be fresh at CLAIM time,
        # while the provider call is still in flight, or a completion stamp
        # would mask a broken claim stamp and the sweep could rescue a run
        # that had only just begun.
        request = self.a_request()
        GeminiGenerationRequest.objects.filter(pk=request.pk).update(
            updated_at=timezone.now() - timedelta(hours=1)
        )
        before = timezone.now()

        seen = {}

        def probe(workspace, brief, **kwargs):
            row = GeminiGenerationRequest.objects.get(pk=request.pk)
            seen['at_claim'] = row.updated_at
            return dict(ROUTED)

        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            side_effect=probe,
        ):
            generate_content.func(str(request.pk))

        self.assertGreaterEqual(seen['at_claim'], before)
        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.COMPLETED)
        self.assertGreaterEqual(request.updated_at, before)

    def test_a_failed_run_stamps_the_clock_and_records_the_error(self):
        request = self.a_request()
        GeminiGenerationRequest.objects.filter(pk=request.pk).update(
            updated_at=timezone.now() - timedelta(hours=1)
        )
        before = timezone.now()
        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            side_effect=RuntimeError('boom'),
        ):
            with self.assertRaises(RuntimeError):
                generate_content.func(str(request.pk))

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.FAILED)
        self.assertEqual(request.error_message, 'boom')
        self.assertGreaterEqual(request.updated_at, before)

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


class StuckGenerationSweepTests(TenantFixtureMixin, TestCase):
    """A killed worker's generation is rescued once, then failed honestly.

    Observed in production: a Render deploy SIGKILLed the old worker after
    its grace period, mid-generation. The request row sat GENERATING forever
    while a healthy new worker polled past it — the frontend showed "AI is
    working…" indefinitely and nothing was. The sweep runs on every worker
    pass: one re-queue, then an honest FAILED the poller can show.
    """

    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.user, _ = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.EDITOR, 'editor@acme.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', is_default=True,
            status=Brand.Status.ACTIVE,
        )

    def stuck_request(self, *, minutes_ago=11, retry_count=0):
        request = GeminiGenerationRequest.objects.create(
            workspace=self.workspace,
            user=self.user,
            prompt_data=json.dumps({'campaign_name': 'Launch', 'contentType': 'poster'}),
            status=GeminiGenerationRequest.Status.GENERATING,
            retry_count=retry_count,
        )
        # updated_at is auto_now, so only a queryset update can backdate it.
        GeminiGenerationRequest.objects.filter(pk=request.pk).update(
            updated_at=timezone.now() - timedelta(minutes=minutes_ago)
        )
        request.refresh_from_db()
        return request

    def test_an_abandoned_generation_is_requeued_once(self):
        request = self.stuck_request()

        self.assertEqual(sweep_stuck_generations(), 1)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.PENDING)
        self.assertEqual(request.retry_count, 1)
        run = TaskRun.objects.get()
        self.assertEqual(run.task_path, 'apps.gemini.tasks.generate_content')
        self.assertEqual(run.args, [str(request.pk)])

    def test_the_rescue_is_bounded_then_fails_honestly(self):
        request = self.stuck_request(retry_count=1)

        self.assertEqual(sweep_stuck_generations(), 1)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.FAILED)
        # The message the poller surfaces: the truth, not a spinner.
        self.assertEqual(request.error_message, INTERRUPTED_MESSAGE)
        self.assertEqual(TaskRun.objects.count(), 0)

    def test_a_request_still_actively_generating_is_left_alone(self):
        request = self.stuck_request(minutes_ago=5)

        self.assertEqual(sweep_stuck_generations(), 0)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.GENERATING)
        self.assertEqual(TaskRun.objects.count(), 0)

    def test_a_legacy_row_with_null_updated_at_is_still_swept(self):
        # Rows inserted by old-code instances during a deploy overlap know
        # nothing of updated_at; stranded, they must not be invisible to
        # every future sweep.
        request = self.stuck_request()
        GeminiGenerationRequest.objects.filter(pk=request.pk).update(
            updated_at=None, created_at=timezone.now() - timedelta(minutes=20)
        )

        self.assertEqual(sweep_stuck_generations(), 1)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.PENDING)
        self.assertEqual(TaskRun.objects.count(), 1)

    def test_an_orphaned_pending_row_is_requeued(self):
        # A crash between the view's create and its enqueue (or a task that
        # burned its attempts during a deploy's schema window) leaves a
        # PENDING row no TaskRun will ever serve; the sweep must give it the
        # same one rescue a stranded GENERATING row gets.
        request = GeminiGenerationRequest.objects.create(
            workspace=self.workspace, user=self.user,
            prompt_data=json.dumps({'campaign_name': 'Launch'}),
            status=GeminiGenerationRequest.Status.PENDING,
        )
        GeminiGenerationRequest.objects.filter(pk=request.pk).update(
            updated_at=timezone.now() - timedelta(minutes=11)
        )

        self.assertEqual(sweep_stuck_generations(), 1)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.PENDING)
        self.assertEqual(request.retry_count, 1)
        run = TaskRun.objects.get()
        self.assertEqual(run.args, [str(request.pk)])

    def test_a_backlogged_pending_row_is_left_alone(self):
        # An aged PENDING row whose TaskRun is still queued is a backlog,
        # not an orphan: re-queuing it would spam the queue and burn its
        # rescue budget on a false alarm.
        request = GeminiGenerationRequest.objects.create(
            workspace=self.workspace, user=self.user,
            prompt_data=json.dumps({'campaign_name': 'Launch'}),
            status=GeminiGenerationRequest.Status.PENDING,
        )
        generate_content.enqueue(str(request.pk))
        GeminiGenerationRequest.objects.filter(pk=request.pk).update(
            updated_at=timezone.now() - timedelta(minutes=11)
        )

        self.assertEqual(sweep_stuck_generations(), 0)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.PENDING)
        self.assertEqual(request.retry_count, 0)
        self.assertEqual(TaskRun.objects.count(), 1)

    def test_a_row_stuck_beyond_the_rescue_horizon_fails_without_spend(self):
        # Matters most on the first pass after deploy, which meets every row
        # the pre-sweep era ever stranded: those get an honest FAILED, not a
        # burst of paid re-runs nobody is polling for.
        request = self.stuck_request(minutes_ago=25 * 60)

        self.assertEqual(sweep_stuck_generations(), 1)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.FAILED)
        self.assertEqual(request.error_message, INTERRUPTED_MESSAGE)
        self.assertEqual(TaskRun.objects.count(), 0)

    def test_a_suspended_workspaces_stuck_row_fails_without_spend(self):
        # Suspension pauses spend and writes platform-wide; the rescue must
        # not be the one scheduled mechanism that ignores it. The row still
        # reaches an honest terminal state instead of spinning.
        from apps.workspaces.models import MarketingWorkspace

        self.workspace.status = MarketingWorkspace.Status.SUSPENDED
        self.workspace.save(update_fields=['status'])
        request = self.stuck_request()

        self.assertEqual(sweep_stuck_generations(), 1)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.FAILED)
        self.assertEqual(TaskRun.objects.count(), 0)

    def test_a_finished_generation_whose_final_save_was_lost_is_completed(self):
        request = self.stuck_request()
        GeminiGenerationRequest.objects.filter(pk=request.pk).update(
            error_message='half-written error from the killed run'
        )
        GeminiGenerationResult.objects.create(
            generation_request=request, generated_text='Already made.',
            metadata={'provider': 'gemini'},
        )

        self.assertEqual(sweep_stuck_generations(), 1)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.COMPLETED)
        self.assertIsNotNone(request.completed_at)
        # Completion carries the same bookkeeping the normal path writes:
        # the provider from the result's metadata, and no leftover error.
        self.assertEqual(request.provider, 'gemini')
        self.assertIsNone(request.error_message)
        # The work already exists; re-buying it is exactly what must not
        # happen here.
        self.assertEqual(TaskRun.objects.count(), 0)

    def test_the_worker_pass_rescues_and_finishes_a_killed_generation(self):
        """A single worker pass sweeps the rescue in and runs it to done."""
        from apps.jobs import runner

        request = self.stuck_request()

        # run_once drains everything claimable and only the generation call
        # is patched, so pin the enrichment sweep shut too — otherwise a
        # future fixture edit (a brand website, say) would silently run real
        # enrichment code inside this drain loop.
        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=dict(ROUTED),
        ), patch('apps.universal.tasks.enqueue_due_enrichment', return_value=0):
            runner.run_once()

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.COMPLETED)
        self.assertEqual(request.retry_count, 1)
        self.assertTrue(
            GeminiGenerationResult.objects.filter(generation_request=request).exists()
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
