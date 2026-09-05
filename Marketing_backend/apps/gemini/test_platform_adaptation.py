"""One design, every platform — adapting an approved poster to a new canvas.

Generating per platform produces deliberately DIFFERENT designs (the variety
engine's job). A client who approved a creative wants THAT creative as a
story or a LinkedIn banner: the adaptation rides the approved poster's own
pixels through the template-matching machinery, with `format_adaptation`
switching every prompt layer from "make something new" to "change nothing
but the frame".
"""
import base64
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.content.models import ContentItem
from apps.context.services.context_gateway import on_image_text_lines
from apps.gemini.services.generator import GeminiGeneratorService
from apps.jobs.models import TaskRun
from apps.marketing.models import MarketingAsset
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

from .test_template_image_matching import DATA_URL, FakeModels, PNG_BYTES

User = get_user_model()


def poster_brief(**overrides):
    brief = {
        'headline': 'Ruby Radiance is Live!',
        'format_adaptation': True,
        'creative_direction': {
            'mode': 'REFERENCE',
            'selections': [{'kind': 'BRAND_TEMPLATE', 'title': 'Approved creative'}],
        },
    }
    brief.update(overrides)
    return brief


class AdaptationPromptTests(APITestCase):
    def test_the_text_lines_reproduce_rather_than_invent(self):
        lines = '\n'.join(on_image_text_lines(poster_brief(), 'Ruby Radiance is Live!'))
        self.assertIn('"Ruby Radiance is Live!"', lines)
        self.assertIn('Reproduce every text element of the attached creative', lines)
        self.assertIn('Add no text element and drop none', lines)
        # Everything the making-something-new branches push for stays out.
        self.assertNotIn('entirely new', lines)
        self.assertNotIn('vary pose', lines)
        self.assertNotIn('uppercase display typography', lines)

    def test_the_image_call_treats_the_creative_as_the_binding_design(self):
        fake = SimpleNamespace(models=FakeModels())
        with patch.object(GeminiGeneratorService, '_get_client', return_value=fake):
            GeminiGeneratorService.generate_poster_image(
                'The approved creative as it is.', api_key='k',
                template_image_base64=DATA_URL,
                format_adaptation=True,
                aspect_ratio='9:16',
            )
        contents = fake.models.calls[0]['contents']
        self.assertEqual(len(contents), 2)
        self.assertEqual(contents[0].inline_data.data, PNG_BYTES)
        directive = contents[1]
        self.assertIn("IS THE BRAND'S APPROVED CREATIVE", directive)
        self.assertIn('same subject, pose, styling and scene', directive)
        self.assertIn('9:16', directive)
        self.assertNotIn('NEW photograph', directive)

    def test_an_adaptation_draws_no_variety(self):
        from apps.context.services.generation import _variety_seed

        with patch(
            'apps.context.services.creative_direction.pick_variety',
            side_effect=AssertionError('variety must not be drawn'),
        ):
            self.assertEqual(
                _variety_seed(object(), object(), poster_brief()), {}
            )


class AdaptEndpointTests(APITestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='ad1', workspace_name='Adapt')
        self.manager = User.objects.create_user(username='mgr', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.manager, role=WorkspaceMember.Role.MANAGER
        )
        self.asset = MarketingAsset.objects.create(
            workspace=self.ws, file_name='approved.jpg', source='AI_GENERATED',
            file_url='https://storage.test/generated/approved.jpg',
            mime_type='image/jpeg',
        )
        self.item = ContentItem.objects.create(
            workspace=self.ws, headline='Ruby Radiance is Live!',
            caption='The bridal edit.', hashtags='#ruby',
            status=ContentItem.Status.APPROVED, asset=self.asset,
            preview_url='https://storage.test/generated/approved.jpg',
            layout_config={'feature_ambassador': False},
        )
        self.client.force_authenticate(user=self.manager)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str(self.ws.id))

    def adapt(self, item=None, platform='instagram_story'):
        return self.client.post(
            f'/api/marketing/content/{(item or self.item).pk}/adapt/',
            {'platform': platform}, format='json',
        )

    def test_an_approved_poster_adapts_into_a_queued_draft(self):
        res = self.adapt()
        self.assertEqual(res.status_code, 200, res.data)
        adapted = ContentItem.objects.get(pk=res.data['data']['adapted']['id'])
        self.assertEqual(adapted.status, ContentItem.Status.DRAFT)
        self.assertEqual(adapted.parent_id, self.item.pk)
        # The approved copy travels verbatim; only the canvas changes.
        self.assertEqual(adapted.headline, self.item.headline)
        self.assertEqual(adapted.caption, self.item.caption)
        self.assertEqual(adapted.layout_config['adapted_platform'], 'instagram_story')
        self.assertFalse(adapted.layout_config['feature_ambassador'])
        self.assertTrue(adapted.layout_config['regenerating'])
        self.assertTrue(res.data['data']['adaptation_queued'])
        run = TaskRun.objects.filter(task_path__endswith='adapt_platform').first()
        self.assertIsNotNone(run)
        self.assertEqual(run.args, [str(adapted.pk)])

    def test_only_approved_finished_posters_adapt(self):
        draft = ContentItem.objects.create(
            workspace=self.ws, headline='Draft', status=ContentItem.Status.DRAFT,
        )
        self.assertEqual(self.adapt(item=draft).status_code, 409)
        bare = ContentItem.objects.create(
            workspace=self.ws, headline='No picture',
            status=ContentItem.Status.APPROVED,
        )
        self.assertEqual(self.adapt(item=bare).status_code, 409)
        self.assertEqual(self.adapt(platform='tiktok').status_code, 400)


class AdaptTaskTests(APITestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='ad2', workspace_name='AdaptT')
        self.asset = MarketingAsset.objects.create(
            workspace=self.ws, file_name='approved.jpg', source='AI_GENERATED',
            file_url='https://storage.test/generated/approved.jpg',
            mime_type='image/jpeg',
        )
        self.parent = ContentItem.objects.create(
            workspace=self.ws, headline='Ruby Radiance is Live!',
            status=ContentItem.Status.APPROVED, asset=self.asset,
            preview_url='https://storage.test/generated/approved.jpg',
        )
        self.adapted = ContentItem.objects.create(
            workspace=self.ws, headline='Ruby Radiance is Live!',
            status=ContentItem.Status.DRAFT, parent=self.parent,
            layout_config={
                'adapted_platform': 'linkedin', 'feature_ambassador': True,
                'regenerating': True,
            },
        )

    def test_the_task_rides_the_approved_pixels_and_persists_the_new_canvas(self):
        from apps.gemini.tasks import adapt_platform

        bought = {
            'image_url': 'https://storage.test/generated/wide.jpg',
            'file_name': 'wide.jpg', 'mime_type': 'image/jpeg',
        }
        with patch(
            'apps.inspirations.analysis._stored_media_data', return_value=DATA_URL,
        ) as loader, patch(
            'apps.context.services.generation.retry_image', return_value=bought,
        ) as retry:
            result = adapt_platform.func(str(self.adapted.pk))

        self.assertEqual(result['status'], 'DONE')
        # The source shim carries the approved creative itself.
        shim = loader.call_args.args[0]
        self.assertEqual(shim.file_url, 'https://storage.test/generated/approved.jpg')
        brief = retry.call_args.args[2]
        self.assertTrue(brief['format_adaptation'])
        self.assertEqual(brief['template_image_base64'], DATA_URL)
        self.assertEqual(brief['platform'], 'linkedin')
        self.assertEqual(brief['headline'], 'Ruby Radiance is Live!')
        # The creative already carries its logo — never attach a second one.
        self.assertEqual(brief['logo_image_base64'], '')

        self.adapted.refresh_from_db()
        self.assertEqual(
            self.adapted.preview_url, 'https://storage.test/generated/wide.jpg'
        )
        self.assertNotIn('regenerating', self.adapted.layout_config)
        trace = self.adapted.layout_config['generation_trace']
        self.assertEqual(trace['adapted_from'], str(self.parent.pk))
        self.assertEqual(trace['adapted_platform'], 'linkedin')

    def test_a_failed_buy_leaves_an_editable_copy(self):
        from apps.gemini.tasks import adapt_platform

        with patch(
            'apps.inspirations.analysis._stored_media_data', return_value=DATA_URL,
        ), patch(
            'apps.context.services.generation.retry_image',
            side_effect=RuntimeError('provider down'),
        ):
            result = adapt_platform.func(str(self.adapted.pk))

        self.assertEqual(result['status'], 'FAILED')
        self.adapted.refresh_from_db()
        self.assertNotIn('regenerating', self.adapted.layout_config)
        self.assertEqual(self.adapted.preview_url, '')
