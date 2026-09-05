"""
A re-bought picture fronts the same face in the same design as the first.

`retry_image` re-buys ONLY the picture of a saved draft - the missing-image
repair and the image-only request-edits pass - and used to build its brief
without the brand ambassador's photo or the matched brand template's pixels
that `generate_copy_and_image` attaches. A repaired or revised poster then
showed a different model and ignored the template design. These tests pin
the retry to the first buy's references: the ambassador by default, off on
`feature_ambassador: False`, the template when one is matched, a reference
the caller already fixed left alone, a face-safe scene seed once the
ambassador rides along, and no crash when a reference cannot be fetched.
"""
import uuid
from unittest.mock import patch

from django.test import TestCase

from apps.ai.models import Capability
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.content.models import ContentItem
from apps.context.services.context_gateway import FACE_VISIBLE_LINE, SCENE_VARIANTS
from apps.context.services.generation import retry_image
from apps.inspirations.models import BrandInspiration

AMBASSADOR = 'data:image/png;base64,AAAA'
TEMPLATE = 'data:image/png;base64,BBBB'
HEADLINE = 'Roasted this week'
FACE_SAFE_KEYS = [row['key'] for row in SCENE_VARIANTS if not row.get('crops_face')]
CLOSE_UP = next(row['key'] for row in SCENE_VARIANTS if row.get('crops_face'))
GENERATION = 'apps.context.services.generation'

FAKE_IMAGE = {
    'image_url': 'https://cdn.example.com/poster.png',
    'provider': 'STABILITY', 'provider_name': 'Stability', 'latency_ms': 20,
}


def recording_router(calls):
    def dispatch(self_router, capability, brief, content_item_id=None):
        calls.append({'capability': capability, 'brief': brief})
        if capability == Capability.IMAGE:
            return dict(FAKE_IMAGE)
        raise AssertionError(f'unexpected {capability}')
    return dispatch


class RetryImageReferenceTests(TenantFixtureMixin, TestCase):
    """The retry's brief carries what the first buy's image brief carried."""

    def setUp(self):
        self.ws = self.make_workspace('Acme', 'c1')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Acme Co', is_default=True, cta_keyword='MORE INFO',
        )

    def retry(self, trace=None, **overrides):
        """One image-only retry; returns the brief the IMAGE dispatch got."""
        extra = {
            'contentType': 'poster', 'offer': '30% off', 'headline': HEADLINE,
            'creative_direction': {'mode': 'AI_ORIGINAL', 'selections': []},
            'request_id': str(uuid.uuid4()),
        }
        extra.update(overrides)
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', recording_router(calls)):
            result = retry_image(
                self.ws, self.brand, extra, instruction='Launch', trace=trace,
            )
        self.assertEqual([c['capability'] for c in calls], [Capability.IMAGE])
        self.assertEqual(result['image_url'], FAKE_IMAGE['image_url'])
        return calls[0]['brief']

    def test_the_ambassador_fronts_the_retry_by_default(self):
        with patch(f'{GENERATION}._ambassador_image', return_value=AMBASSADOR) as photo:
            brief = self.retry()
        photo.assert_called_once_with(self.brand)
        self.assertEqual(brief['ambassador_image_base64'], AMBASSADOR)
        # And the picture is still told the words the copy won.
        self.assertIn(f'"{HEADLINE}"', '\n'.join(brief['brand_context']))

    def test_feature_ambassador_false_keeps_the_face_off_and_the_photo_unread(self):
        with patch(f'{GENERATION}._ambassador_image', return_value=AMBASSADOR) as photo:
            brief = self.retry(feature_ambassador=False)
        photo.assert_not_called()
        self.assertNotIn('ambassador_image_base64', brief)

    def test_a_carousel_slide_is_rebought_bare_like_its_siblings(self):
        # generate_carousel_and_copy attaches neither reference, so one
        # re-bought slide must not be the only slide fronting the model.
        direction = {
            'mode': 'REFERENCE',
            'selections': [{'kind': 'BRAND_TEMPLATE', 'id': 'tpl-1', 'direction': 'USE'}],
        }
        with (
            patch(f'{GENERATION}._ambassador_image', return_value=AMBASSADOR) as photo,
            patch(f'{GENERATION}._template_image', return_value=TEMPLATE) as template,
        ):
            brief = self.retry(
                contentType='carousel_slide', creative_direction=direction,
                slide={'position': 2, 'count': 3, 'description': 'Beans'},
            )
        photo.assert_not_called()
        template.assert_not_called()
        self.assertNotIn('ambassador_image_base64', brief)
        self.assertNotIn('template_image_base64', brief)

    def test_the_matched_template_pixels_ride_in_the_retry(self):
        direction = {
            'mode': 'REFERENCE',
            'selections': [{'kind': 'BRAND_TEMPLATE', 'id': 'tpl-1', 'direction': 'USE'}],
        }
        with patch(f'{GENERATION}._template_image', return_value=TEMPLATE) as template:
            brief = self.retry(creative_direction=direction)
        template.assert_called_once_with(direction)
        self.assertEqual(brief['template_image_base64'], TEMPLATE)

    def test_a_reference_the_caller_already_fixed_is_kept_not_refetched(self):
        mine, also = 'data:image/png;base64,MINE', 'data:image/png;base64,ALSO'
        with (
            patch(f'{GENERATION}._ambassador_image', return_value=AMBASSADOR) as photo,
            patch(f'{GENERATION}._template_image', return_value=TEMPLATE) as template,
        ):
            brief = self.retry(ambassador_image_base64=mine, template_image_base64=also)
        photo.assert_not_called()
        template.assert_not_called()
        self.assertEqual(brief['ambassador_image_base64'], mine)
        self.assertEqual(brief['template_image_base64'], also)

    def test_the_scene_seed_is_face_safe_once_the_ambassador_rides_along(self):
        from apps.context.services import creative_direction as module

        # Every face-safe seed just used: without the ambassador the rotation
        # sends the close-up out; with it the close-up is never the answer.
        for key in FACE_SAFE_KEYS:
            ContentItem.objects.create(
                workspace=self.ws, brand=self.brand,
                layout_config={'generation_trace': {'scene_variant': key}},
            )
        trace = {}
        with (
            patch(f'{GENERATION}._ambassador_image', return_value=AMBASSADOR),
            patch.object(module, 'pick_variety', wraps=module.pick_variety) as pick,
        ):
            brief = self.retry(trace=trace)
        self.assertTrue(pick.call_args.kwargs['face_safe'])
        self.assertIn(trace['scene_variant'], FACE_SAFE_KEYS)
        self.assertEqual(brief['scene_variant'], trace['scene_variant'])
        self.assertIn(FACE_VISIBLE_LINE, '\n'.join(brief['brand_context']))

        trace = {}
        with patch.object(module, 'pick_variety', wraps=module.pick_variety) as pick:
            brief = self.retry(trace=trace)
        self.assertFalse(pick.call_args.kwargs['face_safe'])
        self.assertEqual(trace['scene_variant'], CLOSE_UP)
        self.assertNotIn(FACE_VISIBLE_LINE, '\n'.join(brief['brand_context']))

    def test_an_unreachable_reference_never_blocks_the_retry(self):
        # A real ambassador row whose file storage is down: the photo is
        # left out and the picture is still bought.
        BrandInspiration.objects.create(
            workspace=self.ws, brand=self.brand, title='Model',
            inspiration_type=BrandInspiration.InspirationType.BRAND_AMBASSADOR,
            file_url='https://storage.test/amb/model.jpg', mime_type='image/jpeg',
        )
        with patch(
            'apps.inspirations.analysis._stored_media_data',
            side_effect=RuntimeError('storage down'),
        ):
            brief = self.retry()
        self.assertNotIn('ambassador_image_base64', brief)
        # And with nothing to attach at all - no photo, no template - the
        # brief carries neither key rather than an empty one.
        with (
            patch(f'{GENERATION}._ambassador_image', return_value=''),
            patch(f'{GENERATION}._template_image', return_value=''),
        ):
            brief = self.retry()
        self.assertNotIn('ambassador_image_base64', brief)
        self.assertNotIn('template_image_base64', brief)
