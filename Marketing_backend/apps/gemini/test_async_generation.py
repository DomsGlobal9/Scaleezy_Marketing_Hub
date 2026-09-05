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

    def test_selected_template_render_failure_returns_honest_partial_without_repeating_ai(self):
        from apps.layouts.services import PosterCompositionError

        request = GeminiGenerationRequest.objects.create(
            workspace=self.workspace,
            user=self.user,
            prompt_data=json.dumps({
                'campaign_name': 'Launch',
                'contentType': 'poster',
                'layout': 'cos_split',
                'creative_direction': {
                    'mode': 'CATALOG_TEMPLATE',
                    'layout': 'cos_split',
                    'selection_count': 0,
                    'selections': [],
                },
            }),
            status=GeminiGenerationRequest.Status.PENDING,
        )
        routed = {
            **ROUTED,
            'payload': {
                **ROUTED['payload'],
                'metadata': {
                    'generated_image': {
                        'image_url': 'https://storage.test/generated/poster.png',
                        'file_name': 'poster.png',
                    }
                },
            },
        }
        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=routed,
        ), patch(
            'apps.layouts.services.compose_generated_poster',
            side_effect=PosterCompositionError('Template render failed.'),
        ):
            outcome = generate_content.func(str(request.pk))

        request.refresh_from_db()
        self.assertEqual(outcome['content_item'], str(ContentItem.objects.get().pk))
        self.assertEqual(request.status, GeminiGenerationRequest.Status.COMPLETED)
        self.assertEqual(request.error_message, '')
        item = ContentItem.objects.get(workspace=self.workspace)
        self.assertEqual(item.status, ContentItem.Status.DRAFT)
        self.assertEqual(
            item.layout_config['composition']['status'], 'FAILED'
        )
        result = GeminiGenerationResult.objects.get(generation_request=request)
        self.assertEqual(result.metadata['composition']['status'], 'FAILED')

        # A task redelivery must not buy providers again or leave a second
        # draft after this completed-but-needs-attention composition result.
        with patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as dispatched:
            redelivery = generate_content.func(str(request.pk))
        self.assertEqual(redelivery['status'], 'ALREADY_COMPLETED')
        dispatched.assert_not_called()
        self.assertEqual(ContentItem.objects.filter(workspace=self.workspace).count(), 1)

    def test_the_variety_picks_land_in_the_persisted_trace(self):
        # What the next generation's least-recently-used pick reads back:
        # the archetype and scene the router reported, under the trace key
        # _persist writes - the same key the sync view and request-edits use.
        routed = {
            **ROUTED,
            'trace': {
                'composition_archetype': 'polaroid_card',
                'scene_variant': 'street_golden_hour',
                'capabilities': {},
            },
        }
        self.run_task(self.a_request(), routed)

        item = ContentItem.objects.get(workspace=self.workspace)
        trace = item.layout_config['generation_trace']
        self.assertEqual(
            trace['composition_archetype'], routed['trace']['composition_archetype'],
        )
        self.assertEqual(trace['scene_variant'], routed['trace']['scene_variant'])

    def test_a_repair_reuses_the_drafts_own_composition_and_scene(self):
        # A saved partial poster already says which archetype and seed it
        # is. Repairing its missing image must shoot THAT poster, not draw a
        # fresh pair the record would then misreport.
        draft = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand,
            status=ContentItem.Status.DRAFT, content_format=ContentItem.Format.POSTER,
            headline='Roasted this week',
            layout_config={'generation_trace': {
                'composition_archetype': 'diagonal_cut',
                'scene_variant': 'interior_lounge_seated',
                'capabilities': {'IMAGE': {'status': 'FAILED'}},
            }},
        )
        request = GeminiGenerationRequest.objects.create(
            workspace=self.workspace, user=self.user,
            prompt_data=json.dumps({
                'campaign_name': 'Launch', 'contentType': 'poster',
                'retry_image_only': True, 'retry_brand_id': str(self.brand.pk),
            }),
            status=GeminiGenerationRequest.Status.PENDING,
        )
        GeminiGenerationResult.objects.create(
            generation_request=request, metadata={'contentItemId': str(draft.pk)},
        )
        with patch(
            'apps.context.services.generation.retry_image',
            return_value={
                'image_url': 'https://storage.test/generated/repaired.png',
                'file_name': 'repaired.png',
            },
        ) as retried, patch('apps.layouts.services.compose_generated_poster'):
            generate_content.func(str(request.pk))

        brief = retried.call_args.args[2]
        self.assertEqual(brief['composition_archetype'], 'diagonal_cut')
        self.assertEqual(brief['scene_variant'], 'interior_lounge_seated')
        self.assertEqual(brief['headline'], 'Roasted this week')
        # And the repair is as deterministic as the job: seeded on its id.
        self.assertEqual(brief['request_id'], str(request.pk))
        draft.refresh_from_db()
        trace = draft.layout_config['generation_trace']
        self.assertEqual(trace['composition_archetype'], 'diagonal_cut')
        self.assertEqual(trace['scene_variant'], 'interior_lounge_seated')
        self.assertEqual(trace['capabilities']['IMAGE']['status'], 'OK')


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

    def test_a_row_from_before_the_updated_at_field_is_swept_by_created_at(self):
        request = self.stuck_request()
        GeminiGenerationRequest.objects.filter(pk=request.pk).update(
            updated_at=None, created_at=timezone.now() - timedelta(minutes=20)
        )

        self.assertEqual(sweep_stuck_generations(), 1)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.PENDING)

    def test_a_finished_generation_whose_final_save_was_lost_is_completed(self):
        request = self.stuck_request()
        GeminiGenerationResult.objects.create(
            generation_request=request, generated_text='Already made.'
        )

        self.assertEqual(sweep_stuck_generations(), 1)

        request.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.COMPLETED)
        self.assertIsNotNone(request.completed_at)
        # The work already exists; re-buying it is exactly what must not
        # happen here.
        self.assertEqual(TaskRun.objects.count(), 0)

    def test_interrupted_selected_template_completes_with_an_honest_warning(self):
        request = self.stuck_request()
        item = ContentItem.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            status=ContentItem.Status.DRAFT,
            layout_plugin='cos_split',
            layout_config={
                'creative_direction': {
                    'mode': 'CATALOG_TEMPLATE',
                    'layout': 'cos_split',
                }
            },
        )
        GeminiGenerationResult.objects.create(
            generation_request=request,
            generated_text='The paid copy survived.',
            metadata={
                'contentItemId': str(item.pk),
                'composition': {
                    'status': 'PENDING',
                    'layout': 'cos_split',
                },
            },
        )

        self.assertEqual(sweep_stuck_generations(), 1)

        request.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(request.status, GeminiGenerationRequest.Status.COMPLETED)
        self.assertEqual(request.error_message, '')
        request.result.refresh_from_db()
        self.assertEqual(request.result.metadata['composition']['status'], 'FAILED')
        self.assertIn(
            'template render was interrupted',
            request.result.metadata['composition']['error'],
        )
        self.assertEqual(item.layout_config['composition']['status'], 'FAILED')
        self.assertEqual(TaskRun.objects.count(), 0)

    def test_the_worker_pass_rescues_and_finishes_a_killed_generation(self):
        """A single worker pass sweeps the rescue in and runs it to done."""
        from apps.jobs import runner

        request = self.stuck_request()

        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=dict(ROUTED),
        ):
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
            layout_config={
                'creative_direction': {
                    'mode': 'AI_ORIGINAL', 'layout': '', 'selections': [],
                },
            },
        )
        # Copy AND visual elements flagged, so the default fixture exercises
        # the full-regeneration path; the scoped tests below narrow it.
        capture(
            content_item=self.parent, user=self.manager,
            verdict=Feedback.Verdict.NEEDS_EDITS,
            element_keys=['imagery_subject', 'headline'],
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

    def regenerate(self, *, side_effect=None, routed=None):
        from apps.gemini.tasks import regenerate_revision

        kwargs = (
            {'side_effect': side_effect}
            if side_effect is not None
            else {'return_value': dict(routed or REVISED)}
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
        self.assertIn('Imagery subject', instruction)
        self.assertIn('Logo hides the border work', instruction)
        # The revision's OWN brand rides along — resolving by workspace
        # default would apply another brand's guardrails to this content.
        self.assertEqual(dispatched.call_args.kwargs.get('brand'), self.brand)

        self.revision.refresh_from_db()
        self.assertEqual(self.revision.headline, 'Sharper teal drop')
        self.assertEqual(self.revision.caption, 'Rewritten after your notes.')
        self.assertNotIn('regenerating', self.revision.layout_config)
        # The new photograph was made durable and — this parent being an
        # AI_ORIGINAL delegation — ships raw: the provider's poster IS the
        # draft, with no built-in template composed over it.
        self.assertEqual(
            self.revision.asset.source, MarketingAsset.Source.AI_GENERATED
        )
        self.assertEqual(
            self.revision.asset.file_url,
            'https://storage.test/generated/take-two.png',
        )
        self.assertEqual(
            self.revision.preview_url,
            'https://storage.test/generated/take-two.png',
        )
        self.assertEqual(self.revision.layout_plugin, '')
        self.assertNotIn('source_asset', self.revision.layout_config)

    def test_the_regenerated_revision_is_attributable_like_a_fresh_one(self):
        from apps.brands.services.brand_brain import rebuild_brand_brain
        from apps.learning.models import LearningScope
        from apps.learning.services import create_explicit_rule

        create_explicit_rule(
            workspace=self.workspace, brand=self.brand,
            text='Never crop the border work.', scope=LearningScope.BRAND,
            created_by=self.manager,
        )
        rebuild_brand_brain(self.brand)
        self.brand.refresh_from_db()

        self.regenerate(
            routed={**REVISED, 'brain_version': self.brand.brain_version}
        )

        self.revision.refresh_from_db()
        trace = (self.revision.layout_config or {}).get('generation_trace') or {}
        self.assertEqual(trace.get('brain_version'), self.brand.brain_version)
        self.assertTrue(
            trace.get('rule_ids'),
            'a regenerated revision must name the rules it read, or the '
            'learning-usage report undercounts every request-edits pass',
        )
        # Stamping the trace did not clobber the rest of the config: the
        # inherited creative direction is still alongside it. (No composer
        # source record exists any more — an AI_ORIGINAL revision ships raw.)
        self.assertIn('creative_direction', self.revision.layout_config)

    def test_a_failed_regeneration_leaves_the_editable_copy(self):
        self.regenerate(side_effect=RuntimeError('provider down'))

        self.revision.refresh_from_db()
        self.assertEqual(self.revision.headline, 'Drape yourself in teal')
        self.assertEqual(self.revision.caption, 'Original caption.')
        # The marker never lingers: a card must not claim to be regenerating
        # after the attempt has already failed.
        self.assertNotIn('regenerating', self.revision.layout_config)

    def test_revoked_references_stop_regeneration_before_provider_spend(self):
        from apps.context.services.creative_direction import resolve_creative_direction
        from apps.inspirations.models import BrandInspiration
        from apps.universal.models import LifecycleStatus, PlatformInspiration
        from apps.gemini.tasks import regenerate_revision

        brand_reference = BrandInspiration.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            title='Client reference',
            reference_url='https://example.com/client-reference',
        )
        platform_reference = PlatformInspiration.objects.create(
            title='Platform reference',
            reference_url='https://example.com/platform-reference',
            status=LifecycleStatus.PUBLISHED,
        )
        cases = []
        for source_type, reference in (
            ('BRAND', brand_reference),
            ('PLATFORM', platform_reference),
        ):
            direction = resolve_creative_direction(
                self.workspace,
                self.brand,
                [{
                    'source_type': source_type,
                    'id': str(reference.pk),
                    'role': 'PRIMARY',
                    'direction': 'USE',
                    'focus_areas': [],
                }],
                creative_mode='REFERENCE',
            )
            cases.append((source_type, reference, direction))

        brand_reference.lifecycle_status = BrandInspiration.LifecycleStatus.ARCHIVED
        brand_reference.save(update_fields=['lifecycle_status', 'updated_at'])
        platform_reference.status = LifecycleStatus.RETIRED
        platform_reference.save(update_fields=['status', 'updated_at'])

        for source_type, _reference, direction in cases:
            with self.subTest(source_type=source_type):
                self.revision.layout_config = {
                    'regenerating': True,
                    'creative_direction': direction,
                }
                self.revision.save(update_fields=['layout_config', 'updated_at'])
                with patch(
                    'apps.context.services.generation.generate_marketing_payload'
                ) as full, patch(
                    'apps.context.services.generation.generate_copy_only'
                ) as copy_call, patch(
                    'apps.context.services.generation.retry_image'
                ) as image_call:
                    outcome = regenerate_revision.func(str(self.revision.pk))

                self.assertEqual(outcome['status'], 'REFERENCE_UNAVAILABLE')
                full.assert_not_called()
                copy_call.assert_not_called()
                image_call.assert_not_called()
                self.revision.refresh_from_db()
                self.assertNotIn('regenerating', self.revision.layout_config)
                self.assertEqual(
                    self.revision.layout_config['regeneration_error']['code'],
                    'REFERENCE_UNAVAILABLE',
                )

    # -- surgical scope: only what the reviewer flagged changes -------------

    PLANTED_VARIANT = {
        'palette': 'inverted', 'photo': 'bw', 'paper': 'pure',
        'casing': 'asis', 'pairing': 'asis',
    }

    def with_inherited_look(self):
        """Mirrors what request-edits copies onto a revision in production."""
        from apps.marketing.models import MarketingAsset

        photo = MarketingAsset.objects.create(
            workspace=self.workspace,
            asset_type=MarketingAsset.AssetType.IMAGE,
            file_name='original.png',
            file_url='https://storage.test/generated/original.png',
            source=MarketingAsset.Source.AI_GENERATED,
        )
        self.revision.asset = photo
        self.revision.layout_plugin = 'agency_column'
        self.revision.layout_config = {
            'regenerating': True,
            'source_asset': str(photo.pk),
            'style_variant': dict(self.PLANTED_VARIANT),
        }
        self.revision.save()
        return photo

    def scoped_feedback(self, elements, note='Fix exactly this.'):
        from apps.feedback.models import Feedback
        from apps.feedback.services import capture

        capture(
            content_item=self.parent, user=self.manager,
            verdict=Feedback.Verdict.NEEDS_EDITS, element_keys=elements,
            feedback_text=note, fix_request='', learn=False,
        )

    def run_scoped(self, copy_payload=None, image_result=None):
        from apps.gemini.tasks import regenerate_revision

        with patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as full, patch(
            'apps.context.services.generation.generate_copy_only',
            return_value=copy_payload or {},
        ) as copy_call, patch(
            'apps.context.services.generation.retry_image',
            return_value=image_result or {},
        ) as image_call:
            regenerate_revision.func(str(self.revision.pk))
        return full, copy_call, image_call

    def test_copy_only_feedback_keeps_the_photograph_and_the_look(self):
        photo = self.with_inherited_look()
        self.scoped_feedback(['headline', 'tone_of_voice'], 'Headline is flat.')

        full, copy_call, image_call = self.run_scoped(
            copy_payload={'postTitle': 'Sharper words', 'postDescription': 'New caption.'}
        )

        full.assert_not_called()
        image_call.assert_not_called()
        copy_call.assert_called_once()
        self.revision.refresh_from_db()
        config = self.revision.layout_config
        self.assertEqual(self.revision.headline, 'Sharper words')
        # The photograph the reviewer liked is still the composition source.
        self.assertEqual(config.get('source_asset'), str(photo.pk))
        # And so is the look.
        self.assertEqual(config.get('style_variant'), self.PLANTED_VARIANT)
        self.assertEqual(self.revision.layout_plugin, 'agency_column')
        self.assertNotIn('regenerating', config)

    def test_visual_only_feedback_keeps_the_words(self):
        self.with_inherited_look()
        self.scoped_feedback(['imagery_subject', 'lighting'], 'Wrong product entirely.')

        full, copy_call, image_call = self.run_scoped(
            image_result={
                'image_url': 'https://storage.test/generated/new-photo.png',
                'file_name': 'new-photo.png',
            }
        )

        full.assert_not_called()
        copy_call.assert_not_called()
        image_call.assert_called_once()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.headline, 'Drape yourself in teal')
        self.assertEqual(self.revision.caption, 'Original caption.')
        # The composition source moved to the new photograph.
        from apps.marketing.models import MarketingAsset

        source = MarketingAsset.objects.get(
            pk=self.revision.layout_config['source_asset']
        )
        self.assertEqual(
            source.file_url, 'https://storage.test/generated/new-photo.png'
        )
        # The look the reviewer did not complain about survives.
        self.assertEqual(
            self.revision.layout_config.get('style_variant'), self.PLANTED_VARIANT
        )

    def test_a_full_regeneration_drops_the_old_photographs_focus(self):
        """A new photograph replaces the parent's, so the old focal point is
        popped alongside source_asset — neither may go on describing pixels
        that no longer exist."""
        self.revision.layout_config = {
            'regenerating': True,
            'source_asset': '00000000-0000-0000-0000-000000000001',
            'photo_focus': {'x': 0.3, 'y': 0.4, 'bbox': None,
                            'has_face': True, 'provider': 'gemini'},
        }
        self.revision.save(update_fields=['layout_config'])

        self.regenerate()

        self.revision.refresh_from_db()
        config = self.revision.layout_config
        self.assertNotIn('photo_focus', config)
        # The stale source record is gone too — and since an AI_ORIGINAL
        # revision ships raw, no compose writes a new one.
        self.assertNotIn('source_asset', config)

    def test_image_only_feedback_drops_the_focus_and_copy_only_keeps_it(self):
        focus_dict = {'x': 0.3, 'y': 0.4, 'bbox': None,
                      'has_face': True, 'provider': 'gemini'}

        # Image flagged: the photograph changes, its focus must go with it.
        self.with_inherited_look()
        self.revision.layout_config = {
            **self.revision.layout_config, 'photo_focus': dict(focus_dict),
        }
        self.revision.save(update_fields=['layout_config'])
        self.scoped_feedback(['imagery_subject'], 'Wrong product entirely.')
        self.run_scoped(image_result={
            'image_url': 'https://storage.test/generated/new-photo.png',
            'file_name': 'new-photo.png',
        })
        self.revision.refresh_from_db()
        self.assertNotIn('photo_focus', self.revision.layout_config)

        # Copy flagged on a fresh revision: the kept photograph never re-pays
        # its vision call.
        kept = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand,
            status=ContentItem.Status.DRAFT, version=3, parent=self.parent,
            headline='Drape yourself in teal',
            layout_config={'regenerating': True, 'photo_focus': dict(focus_dict)},
        )
        self.revision = kept
        self.scoped_feedback(['headline'], 'Headline is flat.')
        self.run_scoped(copy_payload={'postTitle': 'Sharper words'})
        kept.refresh_from_db()
        self.assertEqual(kept.layout_config.get('photo_focus'), focus_dict)

    def test_image_only_edits_record_the_new_pictures_composition_and_scene(self):
        from apps.gemini.tasks import regenerate_revision

        self.with_inherited_look()
        self.scoped_feedback(['imagery_subject'], 'Wrong product entirely.')

        def rebought(workspace, brand, brief, *, instruction='', trace=None):
            # What retry_image does for real: the picks it rode on, handed
            # back to whoever persists the picture.
            trace.update({
                'composition_archetype': 'polaroid_card',
                'scene_variant': 'street_golden_hour',
            })
            return {
                'image_url': 'https://storage.test/generated/new-photo.png',
                'file_name': 'new-photo.png',
            }

        with patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as full, patch(
            'apps.context.services.generation.generate_copy_only',
        ) as copy_call, patch(
            'apps.context.services.generation.retry_image', side_effect=rebought,
        ) as image_call:
            regenerate_revision.func(str(self.revision.pk))

        full.assert_not_called()
        copy_call.assert_not_called()
        image_call.assert_called_once()
        self.revision.refresh_from_db()
        trace = self.revision.layout_config['generation_trace']
        self.assertEqual(trace['composition_archetype'], 'polaroid_card')
        self.assertEqual(trace['scene_variant'], 'street_golden_hour')

    def rebuy_brief(self):
        """Runs an image-scope edit and returns the brief retry_image got."""
        from apps.gemini.tasks import regenerate_revision

        self.scoped_feedback(['imagery_subject'], 'Wrong product entirely.')
        seen = {}

        def rebought(workspace, brand, brief, *, instruction='', trace=None):
            seen.update(brief)
            return {
                'image_url': 'https://storage.test/generated/new-photo.png',
                'file_name': 'new-photo.png',
            }

        with patch(
            'apps.context.services.generation.generate_marketing_payload'
        ), patch(
            'apps.context.services.generation.generate_copy_only',
        ), patch(
            'apps.context.services.generation.retry_image', side_effect=rebought,
        ):
            regenerate_revision.func(str(self.revision.pk))
        return seen

    def test_image_edits_honour_the_recorded_choice_to_leave_the_model_out(self):
        # The studio's toggle is a per-generation choice the item records;
        # the re-bought picture must not front a face the poster was made
        # without.
        # Recorded on the parent by _persist; request_edits does not copy it,
        # so the edit must look it up there.
        self.with_inherited_look()
        self.parent.layout_config = {
            **(self.parent.layout_config or {}), 'feature_ambassador': False,
        }
        self.parent.save(update_fields=['layout_config'])

        self.assertIs(self.rebuy_brief()['feature_ambassador'], False)

    def test_image_edits_default_to_the_brand_model_when_nothing_was_recorded(self):
        # Items saved before the choice was recorded were bought with the
        # model, so their edits are too.
        self.with_inherited_look()

        self.assertIs(self.rebuy_brief()['feature_ambassador'], True)

    def with_inherited_trace(self, **trace):
        """The generation_trace the parent's persisted poster recorded.

        request_edits deliberately leaves it on the parent, so the revision
        under edit carries none of its own - exactly what production hands
        regenerate_revision."""
        self.with_inherited_look()
        self.parent.layout_config = {
            **(self.parent.layout_config or {}),
            'generation_trace': {'brain_version': '', 'capabilities': {}, **trace},
        }
        self.parent.save(update_fields=['layout_config'])
        self.revision.refresh_from_db()
        self.assertNotIn('generation_trace', self.revision.layout_config or {})

    def test_copy_only_edits_keep_the_kept_photographs_composition_and_scene(self):
        # The photograph did not change, so its composition did not either.
        # Dropping the pair here is how the per-brand rotation forgot which
        # composition a copy-edited poster was, and served it again.
        self.with_inherited_trace(
            composition_archetype='split_vertical', scene_variant='motion_mid_frame',
        )
        self.scoped_feedback(['headline'], 'Headline is flat.')

        full, copy_call, image_call = self.run_scoped(
            copy_payload={'postTitle': 'Sharper words'}
        )

        full.assert_not_called()
        image_call.assert_not_called()
        copy_call.assert_called_once()
        self.revision.refresh_from_db()
        trace = self.revision.layout_config['generation_trace']
        self.assertEqual(trace['composition_archetype'], 'split_vertical')
        self.assertEqual(trace['scene_variant'], 'motion_mid_frame')
        self.assertIn('brain_version', trace)

    def test_image_edits_replace_the_inherited_composition_and_scene(self):
        from apps.gemini.tasks import regenerate_revision

        # A new photograph is a new poster: its own picks win over the pair
        # the parent's picture rode on.
        self.with_inherited_trace(
            composition_archetype='split_vertical', scene_variant='motion_mid_frame',
        )
        self.scoped_feedback(['imagery_subject'], 'Wrong product entirely.')

        def rebought(workspace, brand, brief, *, instruction='', trace=None):
            trace.update({
                'composition_archetype': 'type_first',
                'scene_variant': 'studio_three_quarter',
            })
            return {
                'image_url': 'https://storage.test/generated/new-photo.png',
                'file_name': 'new-photo.png',
            }

        with patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as full, patch(
            'apps.context.services.generation.generate_copy_only',
        ) as copy_call, patch(
            'apps.context.services.generation.retry_image', side_effect=rebought,
        ) as image_call:
            regenerate_revision.func(str(self.revision.pk))

        full.assert_not_called()
        copy_call.assert_not_called()
        image_call.assert_called_once()
        self.revision.refresh_from_db()
        trace = self.revision.layout_config['generation_trace']
        self.assertEqual(trace['composition_archetype'], 'type_first')
        self.assertEqual(trace['scene_variant'], 'studio_three_quarter')

    def test_copy_only_edits_invent_no_composition_for_an_untraced_photograph(self):
        # A poster made before the picks were recorded has no pair to keep:
        # the trace simply carries none, rather than a made-up one.
        self.with_inherited_trace()
        self.scoped_feedback(['headline'], 'Headline is flat.')

        full, copy_call, image_call = self.run_scoped(
            copy_payload={'postTitle': 'Sharper words'}
        )

        full.assert_not_called()
        image_call.assert_not_called()
        copy_call.assert_called_once()
        self.revision.refresh_from_db()
        trace = self.revision.layout_config['generation_trace']
        self.assertNotIn('composition_archetype', trace)
        self.assertNotIn('scene_variant', trace)
        self.assertIn('brain_version', trace)

    def test_style_only_feedback_on_a_delegated_design_ships_the_raw_image(self):
        photo = self.with_inherited_look()
        self.scoped_feedback(['logo_placement', 'composition_balance'], 'Layout feels off.')

        full, copy_call, image_call = self.run_scoped()

        full.assert_not_called()
        copy_call.assert_not_called()
        image_call.assert_not_called()
        self.revision.refresh_from_db()
        config = self.revision.layout_config
        # An AI_ORIGINAL design has no built-in dress to change any more:
        # the restyle clears the inherited legacy plugin and the provider's
        # raw photograph stands as the draft. Words and photograph untouched,
        # no provider spend, and no fresh dress is recorded for a poster
        # that will never wear one.
        self.assertEqual(self.revision.headline, 'Drape yourself in teal')
        self.assertEqual(self.revision.asset_id, photo.pk)
        self.assertEqual(self.revision.layout_plugin, '')
        self.assertEqual(config.get('style_variant'), self.PLANTED_VARIANT)

    def test_style_feedback_preserves_an_explicit_catalogue_template(self):
        photo = self.with_inherited_look()
        self.revision.layout_config = {
            **self.revision.layout_config,
            'creative_direction': {
                'mode': 'CATALOG_TEMPLATE',
                'layout': 'agency_column',
                'selections': [],
            },
        }
        self.revision.save(update_fields=['layout_config'])
        self.scoped_feedback(
            ['logo_placement', 'composition_balance'], 'Keep my template; fix its styling.'
        )

        full, copy_call, image_call = self.run_scoped()

        full.assert_not_called()
        copy_call.assert_not_called()
        image_call.assert_not_called()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.layout_plugin, 'agency_column')
        self.assertEqual(
            self.revision.layout_config.get('source_asset'), str(photo.pk)
        )
        self.assertEqual(
            self.revision.layout_config['creative_direction']['layout'],
            'agency_column',
        )

    def test_legacy_revision_preserves_its_stored_layout_without_choosing_one(self):
        self.with_inherited_look()
        self.parent.layout_config = {}
        self.parent.save(update_fields=['layout_config'])
        self.scoped_feedback(['logo_placement'], 'Tidy the logo.')

        full, copy_call, image_call = self.run_scoped()

        full.assert_not_called()
        copy_call.assert_not_called()
        image_call.assert_not_called()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.layout_plugin, 'agency_column')
        self.assertNotIn('creative_direction', self.revision.layout_config)

    def test_colour_feedback_changes_the_photo_but_not_the_words(self):
        self.with_inherited_look()
        self.scoped_feedback(['brand_colours'], 'Colours are off palette.')

        full, copy_call, image_call = self.run_scoped(
            image_result={
                'image_url': 'https://storage.test/generated/recoloured.png',
                'file_name': 'recoloured.png',
            }
        )

        full.assert_not_called()
        copy_call.assert_not_called()
        image_call.assert_called_once()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.headline, 'Drape yourself in teal')
        # On a delegated design the provider owns the look: the colour
        # complaint bought a fresh photograph, and it ships raw — no
        # built-in dress is re-picked over it.
        self.assertEqual(
            self.revision.asset.file_url,
            'https://storage.test/generated/recoloured.png',
        )
        self.assertEqual(self.revision.layout_plugin, '')

    def test_the_revision_inherits_the_parents_style_variant(self):
        from apps.common.testing import workspace_header

        pending = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand,
            status=ContentItem.Status.PENDING_REVIEW,
            headline='Second look', cta='30% OFF',
            layout_plugin='agency_column',
            layout_config={
                'style_variant': dict(self.PLANTED_VARIANT),
                'creative_direction': {
                    'mode': 'CATALOG_TEMPLATE',
                    'layout': 'agency_column',
                    'selections': [],
                },
            },
        )
        with patch('apps.gemini.tasks.regenerate_revision'):
            res = self.api.post(
                f'/api/marketing/content/{pending.id}/request-edits/',
                {'note': 'headline is flat', 'elements': ['headline']},
                format='json',
                **workspace_header(self.workspace),
            )
        self.assertEqual(res.status_code, 200, res.content[:300])
        revision = ContentItem.objects.get(parent=pending)
        self.assertEqual(
            revision.layout_config.get('style_variant'), self.PLANTED_VARIANT
        )
        self.assertEqual(
            revision.layout_config.get('creative_direction'),
            pending.layout_config.get('creative_direction'),
        )

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
                {'note': 'colours are off', 'elements': ['brand_colours']},
                format='json',
                **workspace_header(self.workspace),
            )

        self.assertEqual(res.status_code, 200, res.content[:300])
        body = res.json()['data']
        self.assertTrue(body['regeneration_queued'])
        revision = ContentItem.objects.get(parent=pending)
        task_mock.enqueue.assert_called_once_with(str(revision.pk))
        self.assertTrue(revision.layout_config.get('regenerating'))
