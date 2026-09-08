import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai.models import AIUsageLog, Capability
from apps.ai.router import NoProviderAvailable, billable_units
from apps.brands.models import Brand
from apps.content.models import ContentItem
from apps.context.services.brief_fields import extract_brief_fields
from apps.context.services.generation import generate_marketing_payload
from apps.gemini.models import GeminiGenerationRequest, GeminiGenerationResult
from apps.gemini.views import DEFAULT_IMAGE_QUALITY, MAX_GENERATION_INSTRUCTION_CHARS
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

from .models import AutopilotPolicy, AutopilotRun
from .admin import AutopilotPolicyAdmin
from .services import (
    QUEUED_STALE_AFTER,
    RUNNING_STALE_AFTER,
    WAITING_GENERATION_DEADLINE,
    create_run,
    emergency_stop,
    enqueue_due_autopilot_runs,
    execute_run,
    sweep_stalled_autopilot_runs,
)

User = get_user_model()

DISPATCH = 'apps.ai.router.AIRouter.dispatch'
#: The finished picture's text check would fetch the (fake) image; it is not
#: under test here, so it reads as skipped.
CHECKER = 'apps.context.services.image_text.check_image_text'
SKIPPED = {'verdict': 'skipped', 'found': [], 'expected': '', 'reason': 'not under test'}
COPY = {
    'headline': 'One Useful Principle', 'caption': 'A clear explanation.',
    'hashtags': '#operations', 'raw': {}, 'provider': 'OPENAI',
    'provider_name': 'OpenAI', 'latency_ms': 10,
}
IMAGE = {
    'image_url': 'https://cdn.example.com/poster.png',
    'provider': 'STABILITY', 'provider_name': 'Stability', 'latency_ms': 20,
}


class RecordingRouter:
    """The copy generator answers with COPY and the image provider with
    IMAGE; the copy judge and anything else is unrouted, so the critique
    reads as skipped. Records every brief a provider was handed."""

    def __init__(self):
        self.calls = []

    def dispatch(self, capability, brief, content_item_id=None, *, internal=False):
        self.calls.append({'capability': capability, 'brief': brief})
        if capability == Capability.IMAGE:
            return dict(IMAGE)
        if (
            capability == Capability.TEXT
            and brief.get('schema_name') != 'scaleezy_copy_critique'
            and str(brief.get('task') or '').upper() != 'EXTRACT'
        ):
            return dict(COPY)
        raise NoProviderAvailable(f'No provider routed for {capability}.')

    def briefs(self, capability):
        return [
            call['brief'] for call in self.calls
            if call['capability'] == capability
            and str(call['brief'].get('task') or '').upper() != 'EXTRACT'
            and call['brief'].get('schema_name') != 'scaleezy_copy_critique'
        ]


def lines_with(brief, fragment):
    return [line for line in brief.get('brand_context') or [] if fragment in str(line)]


class AutopilotTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='auto-1', workspace_name='One'
        )
        self.other = MarketingWorkspace.objects.create(
            customer_id='auto-2', workspace_name='Two'
        )
        self.user = User.objects.create_user(username='auto-admin', password='p')
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=self.user, role=WorkspaceMember.Role.ADMIN
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Brand', is_default=True,
            audience='Founders', brand_tone='Clear',
        )
        self.policy = AutopilotPolicy.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            name='Weekly authority',
            objective='Explain one useful operating principle',
            mode=AutopilotPolicy.Mode.APPROVAL_REQUIRED,
            allowed_formats=['POSTER', 'VIDEO'],
            daily_generation_limit=2,
            enabled=True,
            created_by=self.user,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.pk)}

    def test_admin_can_trigger_an_enabled_policy(self):
        response = self.client.post(
            f'/api/marketing/autopilot/policies/{self.policy.pk}/trigger/',
            {}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 202, response.json())
        run = AutopilotRun.objects.get()
        self.assertEqual(run.workspace, self.workspace)
        self.assertTrue(run.task_id)
        self.assertEqual(run.policy_snapshot['objective'], self.policy.objective)

    def test_admin_can_create_then_trigger_a_guided_policy(self):
        created = self.client.post(
            '/api/marketing/autopilot/policies/',
            {
                'brand': str(self.brand.pk),
                'name': 'Brand guided growth',
                'objective': 'Create useful content for founders',
                'campaign_brief': 'Use Brand Master facts and keep the work original.',
                'mode': AutopilotPolicy.Mode.APPROVAL_REQUIRED,
                'allowed_formats': ['POSTER'],
                'daily_generation_limit': 1,
                'monthly_spend_cap': '0',
                'enabled': True,
            },
            format='json', **self.headers,
        )
        self.assertEqual(created.status_code, 201, created.json())

        triggered = self.client.post(
            f"/api/marketing/autopilot/policies/{created.json()['id']}/trigger/",
            {}, format='json', **self.headers,
        )
        self.assertEqual(triggered.status_code, 202, triggered.json())
        run = AutopilotRun.objects.get(policy_id=created.json()['id'])
        self.assertEqual(run.workspace, self.workspace)
        self.assertEqual(run.policy.brand, self.brand)
        self.assertTrue(run.task_id)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_trigger_records_queue_enqueue_failure_honestly(self, task):
        self.policy.daily_generation_limit = 1
        self.policy.save(update_fields=['daily_generation_limit', 'updated_at'])
        task.enqueue.side_effect = RuntimeError('queue unavailable')
        response = self.client.post(
            f'/api/marketing/autopilot/policies/{self.policy.pk}/trigger/',
            {}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 503, response.json())
        self.assertEqual(response.json()['error']['code'], 'QUEUE_ENQUEUE_FAILED')
        run = AutopilotRun.objects.get()
        self.assertEqual(run.status, AutopilotRun.Status.FAILED)
        self.assertEqual(run.error_code, 'QUEUE_ENQUEUE_FAILED')
        self.assertTrue(run.completed_at)
        self.assertEqual(run.task_id, '')
        self.assertEqual(run.steps.get(key='finish').status, 'FAILED')

        task.enqueue.side_effect = None
        task.enqueue.return_value.id = 'retry-task-id'
        retried = self.client.post(
            f'/api/marketing/autopilot/policies/{self.policy.pk}/trigger/',
            {}, format='json', **self.headers,
        )
        self.assertEqual(retried.status_code, 202, retried.json())
        retry_run = AutopilotRun.objects.exclude(pk=run.pk).get()
        self.assertEqual(retry_run.task_id, 'retry-task-id')

    def test_viewer_cannot_create_or_trigger_policy(self):
        membership = WorkspaceMember.objects.get(workspace=self.workspace, user=self.user)
        membership.role = WorkspaceMember.Role.VIEWER
        membership.save(update_fields=['role'])
        response = self.client.post(
            f'/api/marketing/autopilot/policies/{self.policy.pk}/trigger/',
            {}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_cross_tenant_brand_and_channel_are_rejected(self):
        other_brand = Brand.objects.create(workspace=self.other, name='Other')
        other_connection = SocialConnection.objects.create(
            workspace=self.other,
            platform=SocialConnection.Platform.X,
            external_account_id='other-x',
            account_name='Other X',
        )
        response = self.client.post(
            '/api/marketing/autopilot/policies/',
            {
                'brand': str(other_brand.pk),
                'name': 'Bad', 'objective': 'Bad', 'enabled': True,
                'allowed_formats': ['POSTER'],
                'social_connections': [str(other_connection.pk)],
            },
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AutopilotPolicy.objects.count(), 1)

    def test_cross_tenant_channel_is_rejected_on_direct_orm_path(self):
        other_connection = SocialConnection.objects.create(
            workspace=self.other,
            platform=SocialConnection.Platform.X,
            external_account_id='other-direct-x',
            account_name='Other direct X',
        )
        with self.assertRaises(ValidationError), transaction.atomic():
            self.policy.social_connections.add(other_connection)
        self.assertFalse(self.policy.social_connections.exists())

    def test_django_admin_is_observability_only(self):
        model_admin = AutopilotPolicyAdmin(AutopilotPolicy, admin.site)
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None, self.policy))
        self.assertFalse(model_admin.has_delete_permission(None, self.policy))

    def test_auto_publish_is_not_an_available_mode(self):
        response = self.client.post(
            '/api/marketing/autopilot/policies/',
            {
                'brand': str(self.brand.pk),
                'name': 'Unsafe', 'objective': 'Publish without review',
                'mode': 'AUTO_PUBLISH', 'enabled': True,
                'allowed_formats': ['POSTER'],
            },
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_run_queues_existing_generation_then_waits_for_review(self):
        run = create_run(self.policy, initiated_by=self.user)

        first = execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(first['status'], AutopilotRun.Status.WAITING_GENERATION)
        self.assertEqual(run.generation_request.workspace, self.workspace)
        self.assertIn('autopilot', run.generation_request.prompt_data)
        queued_brief = json.loads(run.generation_request.prompt_data)
        self.assertEqual(
            queued_brief['creative_direction']['mode'],
            'AI_ORIGINAL',
        )
        self.assertNotIn('creative_mode', queued_brief)

        content = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand, status=ContentItem.Status.DRAFT
        )
        generation = run.generation_request
        generation.status = GeminiGenerationRequest.Status.COMPLETED
        generation.save(update_fields=['status'])
        GeminiGenerationResult.objects.create(
            generation_request=generation,
            metadata={'contentItemId': str(content.pk)},
        )
        second = execute_run(run.pk)
        run.refresh_from_db()
        content.refresh_from_db()
        self.assertEqual(second['status'], AutopilotRun.Status.WAITING_REVIEW)
        self.assertEqual(content.status, ContentItem.Status.PENDING_REVIEW)
        self.assertIsNone(run.completed_at)

    def test_poster_run_defaults_to_the_brand_template_when_one_exists(self):
        """An autopilot brief follows uploaded brand templates: REFERENCE mode
        with the template as the analysed, locked selection. Non-poster runs
        keep raw AI_ORIGINAL — a poster design is no style reference for
        video."""
        from apps.inspirations.models import BrandInspiration

        template = BrandInspiration.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            title='House poster',
            inspiration_type=BrandInspiration.InspirationType.BRAND_TEMPLATE,
            file_url='https://storage.test/inspirations/house.png',
            storage_path='inspirations/house.png',
            mime_type='image/png',
            file_name='house.png',
        )

        poster_run = create_run(self.policy, initiated_by=self.user)
        result = execute_run(poster_run.pk)
        poster_run.refresh_from_db()
        self.assertEqual(result['status'], AutopilotRun.Status.WAITING_GENERATION)
        brief = json.loads(poster_run.generation_request.prompt_data)
        self.assertEqual(brief['creative_direction']['mode'], 'REFERENCE')
        self.assertEqual(
            [row['id'] for row in brief['creative_direction']['selections']],
            [str(template.pk)],
        )
        self.assertEqual(brief['analyze_before_generation_ids'], [str(template.pk)])
        template.refresh_from_db(fields=['template_last_used_at'])
        self.assertIsNotNone(template.template_last_used_at)

        # Second run of this policy rotates to VIDEO: no template default.
        video_run = create_run(self.policy, initiated_by=self.user)
        execute_run(video_run.pk)
        video_run.refresh_from_db()
        video_brief = json.loads(video_run.generation_request.prompt_data)
        self.assertEqual(video_brief['contentType'], 'video')
        self.assertEqual(video_brief['creative_direction']['mode'], 'AI_ORIGINAL')
        self.assertEqual(video_brief['analyze_before_generation_ids'], [])

    def test_ai_original_delegation_survives_into_the_persisted_draft(self):
        run = create_run(self.policy, initiated_by=self.user)
        execute_run(run.pk)
        run.refresh_from_db()

        routed = {
            'provider': 'TEST',
            'provider_name': 'Test provider',
            'brain_version': '',
            'trace': {},
            'payload': {
                'postTitle': 'A useful operating principle',
                'postDescription': 'A clear explanation for founders.',
                'postHashtags': '#operations',
                'metadata': {},
            },
        }
        from apps.gemini.tasks import generate_content

        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=routed,
        ), patch('apps.autopilot.tasks.execute_autopilot_run'):
            result = generate_content.call(str(run.generation_request_id))

        draft = ContentItem.objects.get(pk=result['content_item'])
        self.assertEqual(
            draft.layout_config['creative_direction']['mode'],
            'AI_ORIGINAL',
        )
        self.assertEqual(draft.layout_config['creative_direction']['layout'], '')

    def test_live_guardrail_blocks_a_queued_run_before_provider_spend(self):
        run = create_run(self.policy, initiated_by=self.user)
        execute_run(run.pk)
        run.refresh_from_db()
        generation = run.generation_request

        # The run was clean when queued. Tightening brand law while it waits
        # must still govern the job the worker eventually receives.
        self.brand.guardrails = {'forbidden_words': ['useful']}
        self.brand.save(update_fields=['guardrails'])

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as routed, patch('apps.autopilot.tasks.execute_autopilot_run'):
            with self.assertRaisesMessage(ValueError, 'Blocked before any AI was paid'):
                generate_content.call(str(generation.pk))

        routed.assert_not_called()
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.FAILED)
        self.assertIn('"useful"', generation.error_message)

    # ── the brief autopilot builds, seen from the provider side ──────────

    def queued_brief(self, policy=None):
        run = create_run(policy or self.policy, initiated_by=self.user)
        result = execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(result['status'], AutopilotRun.Status.WAITING_GENERATION, result)
        return run, json.loads(run.generation_request.prompt_data)

    def generate(self, brief, brand=None):
        """The worker's call - the queued brief, its own instruction, the
        policy's brand - with the providers faked and recorded."""
        router = RecordingRouter()

        def dispatch(_router, capability, brief, content_item_id=None, *, internal=False):
            return router.dispatch(capability, brief, content_item_id, internal=internal)

        with patch(DISPATCH, dispatch), patch(CHECKER, return_value=dict(SKIPPED)):
            result = generate_marketing_payload(
                self.workspace, brief,
                instruction=brief['instruction'], brand=brand or self.brand,
            )
        return router, result

    def second_brand_policy(self, **brand_fields):
        brand = Brand.objects.create(
            workspace=self.workspace, name='Second', status=Brand.Status.ACTIVE,
            audience='Chefs', brand_tone='Warm', **brand_fields,
        )
        policy = AutopilotPolicy.objects.create(
            workspace=self.workspace, brand=brand, name='Second brand',
            objective='Explain knife care', mode=AutopilotPolicy.Mode.APPROVAL_REQUIRED,
            allowed_formats=['POSTER'], enabled=True, created_by=self.user,
        )
        return brand, policy

    def test_the_brand_keyword_is_the_cta_pill_once_never_an_offer_too(self):
        """`offer = cta_keyword` painted the keyword twice - CTA pill and
        vertical offer line - and the image-text audit could not flag it:
        its offer carve-out (`_cta_blocks`) hid the second copy. The CTA
        still comes from the brand identity; the brief carries no offer."""
        self.brand.cta_keyword = 'MORE INFO'
        self.brand.save(update_fields=['cta_keyword'])
        run, brief = self.queued_brief()
        self.assertEqual(brief['offer'], '')
        self.assertEqual(brief['instruction'], '')
        self.assertEqual(run.generation_request.offer, '')
        self.assertNotIn('MORE INFO', run.generation_request.prompt_data)

        router, _ = self.generate(brief)
        (image_brief,) = router.briefs(Capability.IMAGE)
        self.assertEqual(image_brief['offer'], '')
        painted = '\n'.join(image_brief['brand_context'])
        self.assertEqual(painted.count('"MORE INFO"'), 1, painted)
        self.assertTrue(
            lines_with(image_brief, 'a call-to-action pill/button reading "MORE INFO"'),
            painted,
        )
        self.assertFalse(lines_with(image_brief, 'the offer line "'), painted)

    def test_the_campaign_brief_is_the_instruction_the_worker_parses(self):
        """policy.campaign_brief used to land only in brief['autopilot'],
        which nothing reads. As `instruction` - the studio's key - its typed
        fields become the poster's ("Offer: ..." is the offer line) and the
        copy model reads the rest as the creation request."""
        self.policy.campaign_brief = 'Festive   launch.\r\n\r\nOffer:  10% off this week'
        self.policy.save(update_fields=['campaign_brief', 'updated_at'])
        _run, brief = self.queued_brief()
        self.assertEqual(brief['instruction'], 'Festive launch.\nOffer: 10% off this week')
        self.assertEqual(brief['offer'], '')

        router, result = self.generate(brief)
        (image_brief,) = router.briefs(Capability.IMAGE)
        self.assertEqual(image_brief['offer'], '10% off this week')
        self.assertTrue(
            lines_with(image_brief, 'the offer line "10% off this week"'),
            image_brief['brand_context'],
        )
        self.assertEqual(result['trace']['brief_fields'], {'offer': '10% off this week'})
        (text_brief,) = router.briefs(Capability.TEXT)
        self.assertEqual(text_brief['instruction'], 'Festive launch.')
        self.assertEqual(text_brief['offer'], '10% off this week')

    def test_a_legacy_overlong_one_line_brief_is_cut_at_a_sentence_end(self):
        """A row saved before the serializer refused over-long briefs is cut
        at run time, not refused - a scheduled run has nobody to show an
        error to. One long line has no line boundary to keep, so it ends at
        its last full sentence under the cap, and the brief says so."""
        self.policy.campaign_brief = 'Explain the principle. ' * 100
        self.policy.save(update_fields=['campaign_brief', 'updated_at'])
        run, brief = self.queued_brief()
        self.assertLessEqual(len(brief['instruction']), MAX_GENERATION_INSTRUCTION_CHARS)
        self.assertTrue(brief['instruction'].endswith('Explain the principle.'))
        self.assertIs(brief['instruction_truncated'], True)
        self.assertIs(run.steps.get(key='generate').detail['instruction_truncated'], True)

    def test_the_brief_cap_never_cuts_a_labelled_line_in_half(self):
        """The cap used to slice mid-line, so a straddling "Offer: ..." line
        yielded a partial offer ("Flat 30% off orders above" - above what?)
        that was painted and paid for. A line is now whole or dropped."""
        cap = MAX_GENERATION_INSTRUCTION_CHARS
        offer = 'Offer: Flat 30% off orders above Rs 2,999'
        filler = ['Winter launch line %02d for the festive edit.' % n for n in range(1, 23)]
        text = '\n'.join(filler + [offer, 'CTA: Shop now'])
        self.assertGreater(len(text), cap)
        naive = text[:cap].splitlines()[-1]
        self.assertTrue(naive.startswith('Offer:') and naive != offer, naive)

        self.policy.campaign_brief = text
        self.policy.save(update_fields=['campaign_brief', 'updated_at'])
        run, brief = self.queued_brief()
        self.assertEqual(brief['instruction'], '\n'.join(filler))
        self.assertIs(brief['instruction_truncated'], True)
        self.assertIs(run.steps.get(key='generate').detail['instruction_truncated'], True)
        self.assertEqual(extract_brief_fields(brief['instruction']), {})
        router, result = self.generate(brief)
        self.assertNotIn('offer', result['trace'].get('brief_fields') or {})
        (image_brief,) = router.briefs(Capability.IMAGE)
        self.assertEqual(image_brief['offer'], '')

        # A labelled line that fits is kept whole, only the straddling
        # closing line goes.
        text = '\n'.join(filler[:21] + [offer, 'Closing line ' + 'x' * 60])
        self.assertGreater(len(text), cap)
        self.assertLess(text.index(offer) + len(offer), cap)
        self.policy.campaign_brief = text
        self.policy.save(update_fields=['campaign_brief', 'updated_at'])
        _run, brief = self.queued_brief()
        self.assertTrue(brief['instruction'].endswith('\n' + offer))
        self.assertIs(brief['instruction_truncated'], True)
        self.assertEqual(
            extract_brief_fields(brief['instruction']),
            {'offer': 'Flat 30% off orders above Rs 2,999'},
        )

    def test_a_brief_under_the_cap_is_not_marked_truncated(self):
        self.policy.campaign_brief = 'Festive launch.\nOffer: 10% off this week'
        self.policy.save(update_fields=['campaign_brief', 'updated_at'])
        run, brief = self.queued_brief()
        self.assertNotIn('instruction_truncated', brief)
        self.assertNotIn('instruction_truncated', run.steps.get(key='generate').detail)

    def test_an_overlong_campaign_brief_is_refused_at_save_time(self):
        url = f'/api/marketing/autopilot/policies/{self.policy.pk}/'
        response = self.client.patch(
            url, {'campaign_brief': 'Explain the principle. ' * 50}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        message = f'The campaign brief must be {MAX_GENERATION_INSTRUCTION_CHARS} characters or fewer.'
        self.assertEqual(body['error'], {'code': 'CAMPAIGN_BRIEF_TOO_LONG', 'message': message})
        self.assertEqual(body['campaign_brief'], [message])
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.campaign_brief, '')

        # The cap is the studio's, judged on the tidied text: whitespace and
        # blank lines do not count.
        fits = '   Explain the principle.  \r\n\r\n' * 35
        self.assertGreater(len(fits), MAX_GENERATION_INSTRUCTION_CHARS)
        response = self.client.patch(url, {'campaign_brief': fits}, format='json', **self.headers)
        self.assertEqual(response.status_code, 200, response.content)

    def test_a_policy_on_a_second_brand_generates_and_stamps_that_brand(self):
        """The worker used to resolve the workspace default and pass
        brand=None, so a second brand's policy generated with the default's
        context, ambassador and logo and stamped the draft with it."""
        second, policy = self.second_brand_policy()
        run, brief = self.queued_brief(policy)
        self.assertEqual(brief['brand_id'], str(second.pk))
        self.assertEqual(brief['target_audience'], 'Chefs')

        routed = {
            'provider': 'TEST', 'provider_name': 'Test provider', 'brain_version': '',
            'trace': {},
            'payload': {
                'postTitle': 'Keep the edge', 'postDescription': 'Hone weekly.',
                'postHashtags': '#knives', 'metadata': {},
            },
        }
        from apps.gemini.tasks import generate_content

        with patch(
            'apps.context.services.generation.generate_marketing_payload',
            return_value=routed,
        ) as dispatched, patch('apps.autopilot.tasks.execute_autopilot_run'):
            result = generate_content.call(str(run.generation_request_id))

        self.assertEqual(dispatched.call_args.kwargs['brand'], second)
        self.assertEqual(dispatched.call_args.kwargs['instruction'], brief['instruction'])
        draft = ContentItem.objects.get(pk=result['content_item'])
        self.assertEqual(draft.brand, second)

    def test_a_second_brand_policy_follows_its_own_templates(self):
        """Templates were defaulted only for the workspace's default brand,
        because the worker validated references against that brand. With
        the policy's brand resolved in the worker, a second brand's uploaded
        template is the REFERENCE its posters follow."""
        from apps.inspirations.models import BrandInspiration

        second, policy = self.second_brand_policy()
        template = BrandInspiration.objects.create(
            workspace=self.workspace, brand=second, title='Second house poster',
            inspiration_type=BrandInspiration.InspirationType.BRAND_TEMPLATE,
            file_url='https://storage.test/inspirations/second.png',
            storage_path='inspirations/second.png', mime_type='image/png',
            file_name='second.png',
        )
        _run, brief = self.queued_brief(policy)
        self.assertEqual(brief['creative_direction']['mode'], 'REFERENCE')
        self.assertEqual(
            [row['id'] for row in brief['creative_direction']['selections']],
            [str(template.pk)],
        )
        self.assertEqual(brief['analyze_before_generation_ids'], [str(template.pk)])

    def test_an_autopilot_poster_renders_and_bills_like_a_default_studio_poster(self):
        """With no image_quality the generator rendered its 4K default while
        billable_units billed 1; the studio sends its default and pays for
        it. Autopilot now sends the same default - posters only, as the
        studio does."""
        from apps.gemini.services.generator import GeminiGeneratorService

        _run, brief = self.queued_brief()
        self.assertEqual(brief['contentType'], 'poster')
        self.assertEqual(brief['image_quality'], DEFAULT_IMAGE_QUALITY)
        studio_default = {'contentType': 'poster', 'image_quality': DEFAULT_IMAGE_QUALITY}
        self.assertEqual(
            billable_units(Capability.IMAGE, None, brief),
            billable_units(Capability.IMAGE, None, studio_default),
        )
        self.assertEqual(
            GeminiGeneratorService.poster_render_options(brief),
            GeminiGeneratorService.poster_render_options(studio_default),
        )

        # The rotation's video turn carries no tier, like a studio video.
        _video_run, video_brief = self.queued_brief()
        self.assertEqual(video_brief['contentType'], 'video')
        self.assertEqual(video_brief['image_quality'], '')
        self.assertEqual(billable_units(Capability.IMAGE, None, video_brief), 1)

    def test_a_carousel_turn_fails_honestly_before_any_spend(self):
        """Autopilot builds no slides, so a CAROUSEL brief failed in the
        worker after the copy was bought (OutputRejected, slides=[]). The
        run now fails before a generation row exists, names the format, and
        the next run rotates past it."""
        self.policy.allowed_formats = ['CAROUSEL', 'POSTER']
        self.policy.save(update_fields=['allowed_formats', 'updated_at'])
        run = create_run(self.policy, initiated_by=self.user)
        result = execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(result['status'], AutopilotRun.Status.FAILED)
        self.assertEqual(run.error_code, 'FORMAT_UNSUPPORTED')
        self.assertIn('CAROUSEL', run.error)
        self.assertIsNone(run.generation_request)
        self.assertFalse(GeminiGenerationRequest.objects.exists())
        self.assertEqual(run.steps.get(key='finish').status, 'FAILED')

        _next_run, brief = self.queued_brief()
        self.assertEqual(brief['contentType'], 'poster')

    def test_a_format_autopilot_cannot_produce_is_refused_at_save_time(self):
        """A carousel-only policy failed every turn and a ['POSTER',
        'CAROUSEL'] one every other day. The API now refuses the format with
        the message the Missions panel shows (error.message)."""
        message = 'Autopilot cannot produce CAROUSEL yet. Choose from: POSTER, VIDEO.'
        response = self.client.post(
            '/api/marketing/autopilot/policies/',
            {
                'brand': str(self.brand.pk), 'name': 'Slides', 'objective': 'Explain',
                'enabled': True, 'allowed_formats': ['POSTER', 'CAROUSEL'],
            },
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body['error'], {'code': 'FORMAT_UNSUPPORTED', 'message': message})
        self.assertEqual(body['allowed_formats'], [message])
        self.assertEqual(AutopilotPolicy.objects.count(), 1)

        response = self.client.patch(
            f'/api/marketing/autopilot/policies/{self.policy.pk}/',
            {'allowed_formats': ['carousel']}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()['error']['code'], 'FORMAT_UNSUPPORTED')
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.allowed_formats, ['POSTER', 'VIDEO'])

    def test_a_legacy_carousel_policy_stays_editable_and_fails_its_turns_honestly(self):
        """Rows saved with CAROUSEL before the API refused it: an unrelated
        edit (pausing, say) still lands, and the runtime guard still fails
        the turn before any spend."""
        AutopilotPolicy.objects.filter(pk=self.policy.pk).update(allowed_formats=['CAROUSEL'])
        response = self.client.patch(
            f'/api/marketing/autopilot/policies/{self.policy.pk}/',
            {'paused': True}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.policy.refresh_from_db()
        self.assertTrue(self.policy.paused)
        self.assertEqual(self.policy.allowed_formats, ['CAROUSEL'])

        AutopilotPolicy.objects.filter(pk=self.policy.pk).update(paused=False)
        run = create_run(self.policy, initiated_by=self.user)
        execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.error_code, 'FORMAT_UNSUPPORTED')
        self.assertFalse(GeminiGenerationRequest.objects.exists())

    def test_an_unsupported_turn_does_not_count_against_the_daily_limit(self):
        """A ['CAROUSEL', 'POSTER'] policy with a limit of 1 spent its whole
        daily allowance on the carousel turn that bought nothing, so its
        poster turn came every other day."""
        self.policy.allowed_formats = ['CAROUSEL', 'POSTER']
        self.policy.daily_generation_limit = 1
        self.policy.save(update_fields=['allowed_formats', 'daily_generation_limit', 'updated_at'])
        run = create_run(self.policy, initiated_by=self.user)
        execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.error_code, 'FORMAT_UNSUPPORTED')

        _poster_run, brief = self.queued_brief()
        self.assertEqual(brief['contentType'], 'poster')

        # The poster turn did spend, so the limit now holds.
        third = create_run(self.policy, initiated_by=self.user)
        execute_run(third.pk)
        third.refresh_from_db()
        self.assertEqual(third.error_code, 'DAILY_AUTOPILOT_LIMIT')

    def test_a_policy_on_an_archived_brand_fails_before_any_spend(self):
        """The worker used to substitute the workspace default for a brief
        naming a brand that is not active, so an archived second brand's
        policy generated - and spent - on the default brand's identity. The
        run now stops before a generation row exists."""
        second, policy = self.second_brand_policy()
        Brand.objects.filter(pk=second.pk).update(status=Brand.Status.ARCHIVED)
        run = create_run(policy, initiated_by=self.user)
        result = execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(result['status'], AutopilotRun.Status.FAILED)
        self.assertEqual(run.error_code, 'BRAND_INACTIVE')
        self.assertIn('archived', run.error)
        self.assertIsNone(run.generation_request)
        self.assertFalse(GeminiGenerationRequest.objects.exists())
        self.assertFalse(AIUsageLog.objects.exists())
        self.assertEqual(run.steps.get(key='finish').status, 'FAILED')

        # It bought nothing, so it does not count against the daily limit
        # (1 on this policy): the brand restored, the next run generates.
        Brand.objects.filter(pk=second.pk).update(status=Brand.Status.ACTIVE)
        _run, brief = self.queued_brief(policy)
        self.assertEqual(brief['brand_id'], str(second.pk))

    def test_a_brand_archived_while_the_run_waited_fails_the_generation_not_the_default(self):
        """The queued brief names the policy's brand; if that brand is
        archived before the worker reaches it, the worker used to generate
        on the workspace default. Now the request fails before any provider
        is called and the run records the failure."""
        second, policy = self.second_brand_policy()
        run, _brief = self.queued_brief(policy)
        Brand.objects.filter(pk=second.pk).update(status=Brand.Status.ARCHIVED)

        from apps.gemini.tasks import generate_content

        with patch(
            'apps.context.services.generation.generate_marketing_payload'
        ) as routed, patch('apps.autopilot.tasks.execute_autopilot_run'):
            with self.assertRaisesMessage(ValueError, 'The selected brand is inactive'):
                generate_content.call(str(run.generation_request_id))

        routed.assert_not_called()
        generation = run.generation_request
        generation.refresh_from_db()
        self.assertEqual(generation.status, GeminiGenerationRequest.Status.FAILED)
        self.assertEqual(
            generation.error_message,
            'The selected brand is inactive. Generation was not started.',
        )
        self.assertFalse(AIUsageLog.objects.exists())
        self.assertFalse(ContentItem.objects.exists())

        execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.FAILED)
        self.assertEqual(run.error_code, 'GENERATION_FAILED')
        self.assertIn('inactive', run.error)

    def test_emergency_stop_stops_pending_work(self):
        run = create_run(self.policy, initiated_by=self.user)
        policy = emergency_stop(self.policy, by=self.user)
        run.refresh_from_db()
        self.assertTrue(policy.emergency_stop)
        self.assertTrue(policy.paused)
        self.assertEqual(run.status, AutopilotRun.Status.STOPPED)
        self.assertEqual(run.error_code, 'EMERGENCY_STOP')

    def test_run_is_linked_and_waiting_before_generation_enqueues(self):
        """The follow-up race: a generation finishing before the run row
        carries its FK and WAITING_GENERATION status loses the follow-up
        forever. The link must therefore be durable before enqueue."""
        run = create_run(self.policy, initiated_by=self.user)
        seen = {}

        def capture(generation_id):
            row = AutopilotRun.objects.get(pk=run.pk)
            seen['status'] = row.status
            seen['generation_id'] = str(row.generation_request_id)

            class _Result:
                id = 'task-under-test'

            return _Result()

        with patch('apps.gemini.tasks.generate_content') as task:
            task.enqueue.side_effect = capture
            execute_run(run.pk)

        self.assertEqual(seen['status'], AutopilotRun.Status.WAITING_GENERATION)
        run.refresh_from_db()
        self.assertEqual(seen['generation_id'], str(run.generation_request_id))
        self.assertEqual(run.task_id, 'task-under-test')


class AutopilotSweepTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='sweep-1', workspace_name='Sweep'
        )
        self.user = User.objects.create_user(username='sweep-admin', password='p')
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=self.user, role=WorkspaceMember.Role.ADMIN
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Brand', is_default=True,
            audience='Founders', brand_tone='Clear',
        )
        self.policy = AutopilotPolicy.objects.create(
            workspace=self.workspace, brand=self.brand, name='Sweep policy',
            objective='Objective', enabled=True, created_by=self.user,
            allowed_formats=['POSTER'],
        )

    def _waiting_run(self, *, checked_ago_seconds=120, started_ago_seconds=300):
        now = timezone.now()
        generation = GeminiGenerationRequest.objects.create(
            workspace=self.workspace, user=self.user, prompt_data='{}',
            status=GeminiGenerationRequest.Status.GENERATING,
        )
        run = create_run(self.policy, initiated_by=self.user)
        AutopilotRun.objects.filter(pk=run.pk).update(
            status=AutopilotRun.Status.WAITING_GENERATION,
            generation_request=generation,
            started_at=now - timedelta(seconds=started_ago_seconds),
            next_check_at=now - timedelta(seconds=checked_ago_seconds),
        )
        run.refresh_from_db()
        return run

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_sweep_redrives_a_due_waiting_run_exactly_once(self, task):
        run = self._waiting_run()
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        task.enqueue.assert_called_once_with(str(run.pk))
        run.refresh_from_db()
        # Still WAITING_GENERATION — the sweep re-drives, it never advances
        # state itself — with next_check_at pushed into the future as the claim.
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_GENERATION)
        self.assertGreater(run.next_check_at, timezone.now())
        # The pushed next_check_at is the CAS: an immediate second sweep
        # (a second worker on the same tick) claims nothing.
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        task.enqueue.assert_called_once()

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_sweep_ignores_runs_not_yet_due(self, task):
        run = self._waiting_run(checked_ago_seconds=-300)
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        task.enqueue.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_GENERATION)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_deadline_never_discards_a_finished_generation(self, task):
        """A >2h wait whose generation actually COMPLETED (worker outage ate
        the follow-up) must be re-driven so the paid draft lands — failing it
        would tell the user to buy the same work twice."""
        run = self._waiting_run(
            started_ago_seconds=int(WAITING_GENERATION_DEADLINE.total_seconds()) + 60
        )
        generation = run.generation_request
        generation.status = GeminiGenerationRequest.Status.COMPLETED
        generation.save(update_fields=['status'])
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        task.enqueue.assert_called_once_with(str(run.pk))
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_GENERATION)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_redrive_advances_even_when_a_cap_was_crossed_mid_wait(self, task):
        """Caps gate new spend. A re-driven run whose generation is already
        paid for must link its draft even if the daily limit filled up while
        it waited."""
        run = self._waiting_run()
        self.policy.daily_generation_limit = 1
        self.policy.save(update_fields=['daily_generation_limit', 'updated_at'])
        # A sibling run consumes the whole daily limit while run #1 waits.
        create_run(self.policy, initiated_by=self.user)
        generation = run.generation_request
        content = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand,
            status=ContentItem.Status.DRAFT,
        )
        generation.status = GeminiGenerationRequest.Status.COMPLETED
        generation.save(update_fields=['status'])
        GeminiGenerationResult.objects.create(
            generation_request=generation,
            metadata={'contentItemId': str(content.pk)},
        )
        execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_REVIEW)
        self.assertEqual(run.content_item, content)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_sweep_fails_a_wait_past_the_deadline_without_respend(self, task):
        run = self._waiting_run(
            started_ago_seconds=int(WAITING_GENERATION_DEADLINE.total_seconds()) + 60
        )
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        task.enqueue.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.FAILED)
        self.assertEqual(run.error_code, 'GENERATION_STUCK')
        self.assertTrue(run.completed_at)
        self.assertEqual(run.steps.get(key='finish').status, 'FAILED')

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_lost_enqueue_leaves_the_retry_timer_armed(self, task):
        run = self._waiting_run()
        task.enqueue.side_effect = RuntimeError('queue unavailable')
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_GENERATION)
        # next_check_at was pushed by the claim, so the next pass retries.
        self.assertGreater(run.next_check_at, timezone.now())

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_sweep_redrives_a_queued_run_whose_task_died(self, task):
        """The stranding found live in production: the durable task crashed
        out of all its attempts (a Postgres-only locking bug) leaving the run
        QUEUED forever. QUEUED proves nothing was spent, so re-driving is
        free; the CAS on updated_at re-drives once per interval."""
        run = create_run(self.policy, initiated_by=self.user)
        stale = timezone.now() - QUEUED_STALE_AFTER - timedelta(minutes=1)
        AutopilotRun.objects.filter(pk=run.pk).update(updated_at=stale)
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        task.enqueue.assert_called_once_with(str(run.pk))
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.QUEUED)
        # Claimed: updated_at moved, so an immediate second sweep is a no-op.
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        task.enqueue.assert_called_once()

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_sweep_leaves_a_fresh_queued_run_alone(self, task):
        create_run(self.policy, initiated_by=self.user)
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        task.enqueue.assert_not_called()

    def test_sweep_fails_a_run_abandoned_mid_execute(self):
        run = create_run(self.policy, initiated_by=self.user)
        stale = timezone.now() - RUNNING_STALE_AFTER - timedelta(minutes=1)
        AutopilotRun.objects.filter(pk=run.pk).update(
            status=AutopilotRun.Status.RUNNING, started_at=stale, updated_at=stale
        )
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.FAILED)
        self.assertEqual(run.error_code, 'RUN_INTERRUPTED')
        self.assertIsNone(run.next_check_at)

    def test_sweep_leaves_a_live_running_run_alone(self):
        run = create_run(self.policy, initiated_by=self.user)
        AutopilotRun.objects.filter(pk=run.pk).update(
            status=AutopilotRun.Status.RUNNING
        )
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.RUNNING)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_swept_run_advances_when_its_generation_actually_finished(self, task):
        """End to end: follow-up lost, sweep re-drives, execute advances."""
        run = self._waiting_run()
        generation = run.generation_request
        content = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand,
            status=ContentItem.Status.DRAFT,
        )
        generation.status = GeminiGenerationRequest.Status.COMPLETED
        generation.save(update_fields=['status'])
        GeminiGenerationResult.objects.create(
            generation_request=generation,
            metadata={'contentItemId': str(content.pk)},
        )
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        # The sweep only enqueues; running the queued work is execute_run.
        execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_REVIEW)
        self.assertEqual(run.content_item, content)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_generation_sweep_terminal_branches_queue_the_followup(self, task):
        """A generation completed or finally failed by gemini's own sweep must
        still wake the run waiting on it."""
        from apps.gemini.tasks import sweep_stuck_generations

        run = self._waiting_run()
        generation = run.generation_request
        GeminiGenerationResult.objects.create(
            generation_request=generation, metadata={}
        )
        stale = timezone.now() - timedelta(hours=1)
        GeminiGenerationRequest.objects.filter(pk=generation.pk).update(updated_at=stale)
        self.assertEqual(sweep_stuck_generations(), 1)
        task.enqueue.assert_called_once_with(str(run.pk))


class AutopilotScheduleTests(TestCase):
    """The due-policy sweep: cadence, slot math, CAS claims and honesty."""

    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='sched-1', workspace_name='Sched'
        )
        self.user = User.objects.create_user(username='sched-admin', password='p')
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=self.user, role=WorkspaceMember.Role.ADMIN
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Brand', is_default=True,
            audience='Founders', brand_tone='Clear',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.pk)}

    def _policy(self, *, name, cadence=AutopilotPolicy.Cadence.DAILY, due=None,
                enabled=True, **overrides):
        policy = AutopilotPolicy.objects.create(
            workspace=self.workspace, brand=self.brand, name=name,
            objective='Objective', enabled=enabled, created_by=self.user,
            allowed_formats=['POSTER'], cadence=cadence, **overrides,
        )
        if due is not None:
            # Backdate through the queryset: save() would re-arm a past slot.
            AutopilotPolicy.objects.filter(pk=policy.pk).update(next_run_at=due)
            policy.refresh_from_db()
        return policy

    def test_saving_a_scheduled_policy_arms_next_run_one_interval_out(self):
        before = timezone.now()
        policy = self._policy(name='Armed daily')
        after = timezone.now()
        self.assertIsNotNone(policy.next_run_at)
        self.assertGreaterEqual(policy.next_run_at, before + timedelta(days=1))
        self.assertLessEqual(policy.next_run_at, after + timedelta(days=1))
        # Creating a schedule never creates a run by itself.
        self.assertEqual(AutopilotRun.objects.count(), 0)

    def test_switching_back_to_manual_disarms_the_schedule(self):
        policy = self._policy(name='Back to manual')
        policy.cadence = AutopilotPolicy.Cadence.MANUAL
        # update_fields without next_run_at is the repo's save idiom; save()
        # must widen it or the disarm would silently not persist.
        policy.save(update_fields=['cadence', 'updated_at'])
        policy.refresh_from_db()
        self.assertIsNone(policy.next_run_at)

    def test_due_daily_policy_creates_exactly_one_scheduled_run(self):
        due = timezone.now() - timedelta(hours=1)
        policy = self._policy(name='Due daily', due=due)
        self.assertEqual(enqueue_due_autopilot_runs(), 1)
        run = AutopilotRun.objects.get(policy=policy)
        self.assertEqual(run.dedupe_key, f'sched:{policy.pk}:{due.isoformat()}')
        self.assertEqual(run.scheduled_for, due)
        self.assertEqual(run.status, AutopilotRun.Status.QUEUED)
        self.assertTrue(run.task_id)
        self.assertIsNone(run.initiated_by)
        policy.refresh_from_db()
        self.assertEqual(policy.next_run_at, due + timedelta(days=1))
        self.assertGreater(policy.next_run_at, timezone.now())

    def test_overdue_policy_catches_up_without_a_backfill_burst(self):
        due = timezone.now() - timedelta(days=3, hours=1)
        policy = self._policy(name='Overdue daily', due=due)
        self.assertEqual(enqueue_due_autopilot_runs(), 1)
        self.assertEqual(AutopilotRun.objects.filter(policy=policy).count(), 1)
        policy.refresh_from_db()
        # Missed slots are skipped, never replayed: the schedule lands on the
        # first slot in the future.
        self.assertEqual(policy.next_run_at, due + 4 * timedelta(days=1))
        self.assertGreater(policy.next_run_at, timezone.now())

    def test_weekly_interval_math(self):
        due = timezone.now() - timedelta(hours=2)
        policy = self._policy(
            name='Due weekly', cadence=AutopilotPolicy.Cadence.WEEKLY, due=due
        )
        self.assertEqual(enqueue_due_autopilot_runs(), 1)
        policy.refresh_from_db()
        self.assertEqual(policy.next_run_at, due + timedelta(days=7))
        run = AutopilotRun.objects.get(policy=policy)
        self.assertEqual(run.dedupe_key, f'sched:{policy.pk}:{due.isoformat()}')

    def test_manual_disabled_paused_and_stopped_policies_are_untouched(self):
        due = timezone.now() - timedelta(hours=1)
        untouched = [
            self._policy(name='Manual', cadence=AutopilotPolicy.Cadence.MANUAL, due=due),
            self._policy(name='Disabled', enabled=False, due=due),
            self._policy(name='Paused', paused=True, due=due),
            self._policy(name='Stopped', emergency_stop=True, due=due),
        ]
        self.assertEqual(enqueue_due_autopilot_runs(), 0)
        self.assertEqual(AutopilotRun.objects.count(), 0)
        for policy in untouched:
            policy.refresh_from_db()
            self.assertEqual(policy.next_run_at, due, policy.name)

    def test_double_sweep_same_instant_creates_one_run(self):
        due = timezone.now() - timedelta(minutes=30)
        policy = self._policy(name='Raced daily', due=due)
        now = timezone.now()
        self.assertEqual(enqueue_due_autopilot_runs(now=now), 1)
        self.assertEqual(enqueue_due_autopilot_runs(now=now), 0)
        self.assertEqual(AutopilotRun.objects.filter(policy=policy).count(), 1)

    def test_cas_claim_blocks_a_stale_worker(self):
        """Pins the PRODUCTION claim, not a reimplementation: _claim_due_slot
        must refuse a slot whose next_run_at another worker already moved.
        Losing the conditional filter fails this test even though the dedupe
        constraint would still protect the money."""
        from .services import _claim_due_slot

        due = timezone.now() - timedelta(minutes=30)
        policy = self._policy(name='CAS daily', due=due)
        now = timezone.now()
        # Winner claims with the value it read.
        self.assertEqual(
            _claim_due_slot(policy.pk, due, due + timedelta(days=1), now), 1
        )
        # Loser read the same due slot but the row has moved on: zero rows.
        self.assertEqual(
            _claim_due_slot(policy.pk, due, due + timedelta(days=1), now), 0
        )
        policy.refresh_from_db()
        self.assertEqual(policy.next_run_at, due + timedelta(days=1))

    def test_a_crash_after_the_claim_rolls_the_slot_back(self):
        """Claim and create commit together: a failure between them must not
        advance the schedule with no run to show for it — the next tick
        retries the slot instead of losing it silently."""
        due = timezone.now() - timedelta(minutes=30)
        policy = self._policy(name='Crashy daily', due=due)
        with patch(
            'apps.autopilot.services.create_run',
            side_effect=RuntimeError('db blip'),
        ):
            self.assertEqual(enqueue_due_autopilot_runs(), 0)
        policy.refresh_from_db()
        self.assertEqual(policy.next_run_at, due)  # claim rolled back
        self.assertEqual(AutopilotRun.objects.count(), 0)
        # The next pass succeeds normally.
        self.assertEqual(enqueue_due_autopilot_runs(), 1)

    def test_changing_cadence_rearms_a_future_slot(self):
        """DAILY→WEEKLY must not leave tomorrow's daily slot armed to buy a
        generation on the schedule the user just slowed down."""
        policy = self._policy(name='Slowed down')
        daily_slot = policy.next_run_at
        policy.cadence = AutopilotPolicy.Cadence.WEEKLY
        policy.save(update_fields=['cadence', 'updated_at'])
        policy.refresh_from_db()
        self.assertGreater(policy.next_run_at, daily_slot + timedelta(days=5))

    def test_unrelated_edit_rearms_a_past_due_slot_by_design(self):
        """Accepted semantics, pinned: any save of a policy whose slot is
        already past re-arms one interval out — editing a policy never spends
        immediately, even when the edit was only a rename during a worker
        outage. The missed slot is skipped, not queued."""
        due = timezone.now() - timedelta(hours=2)
        policy = self._policy(name='Renamed while due', due=due)
        policy.name = 'Renamed while due (v2)'
        policy.save(update_fields=['name', 'updated_at'])
        policy.refresh_from_db()
        self.assertGreater(policy.next_run_at, timezone.now())
        self.assertEqual(AutopilotRun.objects.count(), 0)

    def test_duplicate_dedupe_key_is_treated_as_already_created(self):
        due = timezone.now() - timedelta(minutes=30)
        policy = self._policy(name='Deduped daily', due=due)
        AutopilotRun.objects.create(
            workspace=self.workspace, policy=policy, scheduled_for=due,
            dedupe_key=f'sched:{policy.pk}:{due.isoformat()}',
        )
        # No exception, nothing new created, and the schedule still advances
        # so the slot is not retried forever.
        self.assertEqual(enqueue_due_autopilot_runs(), 0)
        self.assertEqual(AutopilotRun.objects.filter(policy=policy).count(), 1)
        policy.refresh_from_db()
        self.assertEqual(policy.next_run_at, due + timedelta(days=1))

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_enqueue_failure_marks_scheduled_run_failed_honestly(self, task):
        task.enqueue.side_effect = RuntimeError('queue unavailable')
        due = timezone.now() - timedelta(minutes=30)
        policy = self._policy(name='Queueless daily', due=due)
        self.assertEqual(enqueue_due_autopilot_runs(), 1)
        run = AutopilotRun.objects.get(policy=policy)
        self.assertEqual(run.status, AutopilotRun.Status.FAILED)
        self.assertEqual(run.error_code, 'QUEUE_ENQUEUE_FAILED')
        self.assertTrue(run.completed_at)
        self.assertEqual(run.task_id, '')
        self.assertEqual(run.steps.get(key='finish').status, 'FAILED')
        # The schedule advanced regardless: no unbounded retry storm against
        # a queue that is down.
        self.assertEqual(enqueue_due_autopilot_runs(), 0)

    def test_api_sets_cadence_but_never_next_run_at(self):
        before = timezone.now()
        created = self.client.post(
            '/api/marketing/autopilot/policies/',
            {
                'brand': str(self.brand.pk),
                'name': 'API daily', 'objective': 'Ship one useful draft',
                'allowed_formats': ['POSTER'], 'enabled': True,
                'cadence': 'DAILY',
                # A client must not be able to schedule immediate spend.
                'next_run_at': before.isoformat(),
            },
            format='json', **self.headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        payload = created.json()
        self.assertEqual(payload['cadence'], 'DAILY')
        policy = AutopilotPolicy.objects.get(pk=payload['id'])
        self.assertGreaterEqual(policy.next_run_at, before + timedelta(days=1))

        patched = self.client.patch(
            f'/api/marketing/autopilot/policies/{policy.pk}/',
            {'cadence': 'MANUAL'}, format='json', **self.headers,
        )
        self.assertEqual(patched.status_code, 200, patched.json())
        self.assertIsNone(patched.json()['next_run_at'])

        rejected = self.client.patch(
            f'/api/marketing/autopilot/policies/{policy.pk}/',
            {'cadence': 'HOURLY'}, format='json', **self.headers,
        )
        self.assertEqual(rejected.status_code, 400)
