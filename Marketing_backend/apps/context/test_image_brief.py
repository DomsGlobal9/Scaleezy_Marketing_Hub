"""
The words on the poster are typography the image model paints.

Since the no-default-dress decision a delegated poster (AI_ORIGINAL or
REFERENCE) ships the provider's image untouched, so a headline the image does
not carry is a headline nobody sees. The founder's directive - "add the
headline text on the image too" - makes the on-image text a brief line every
adapter carries: the exact headline, the CTA/offer when present, and the
classic social-sale composition. Where the compose engine still owns the words
(catalogue templates, carousel slides) the old no-text rule stands, and video
is untouched.
"""
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.ai.models import Capability
from apps.ai.router import NoProviderAvailable
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.context.services.context_gateway import (
    NO_TEXT_LINE,
    TaskType,
    build_generation_context,
    context_as_brief,
    on_image_text_lines,
)
from apps.context.services.generation import (
    generate_carousel_and_copy,
    generate_copy_and_image,
    generate_video_and_copy,
    retry_image,
)

HEADLINE = 'Roasted this week'
HEADLINE_LINE = 'Render this exact headline'
MIRROR_LINE = "Mirror the reference's typographic hierarchy"

FAKE_TEXT = {
    'headline': HEADLINE, 'caption': 'Fresh beans.', 'hashtags': '#coffee',
    'raw': {}, 'provider': 'OPENAI', 'provider_name': 'OpenAI', 'latency_ms': 10,
}
FAKE_IMAGE = {
    'image_url': 'https://cdn.example.com/poster.png',
    'provider': 'STABILITY', 'provider_name': 'Stability', 'latency_ms': 20,
}
FAKE_VIDEO = {
    'video_url': 'https://cdn.example.com/clip.mp4',
    'provider': 'RUNWAY', 'provider_name': 'Runway', 'latency_ms': 30,
}


def poster_brief(**overrides):
    brief = {
        'contentType': 'poster',
        'offer': '30% off this weekend',
        'structured': {'identity': {'cta_keyword': 'MORE INFO'}},
        'creative_direction': {'mode': 'AI_ORIGINAL', 'selections': []},
    }
    brief.update(overrides)
    return brief


def recording_router(calls, text_fails=False):
    def dispatch(self_router, capability, brief, content_item_id=None):
        calls.append({'capability': capability, 'brief': brief})
        if capability == Capability.TEXT:
            if text_fails:
                raise RuntimeError('copy provider exploded')
            return dict(FAKE_TEXT)
        if capability == Capability.IMAGE:
            return dict(FAKE_IMAGE)
        if capability == Capability.VIDEO:
            return dict(FAKE_VIDEO)
        raise NoProviderAvailable(f'no {capability}')
    return dispatch


def lines_with(lines, needle):
    return [line for line in lines if needle in line]


class OnImageTextDirectiveTests(SimpleTestCase):
    """What the image model is told about the words, per mode."""

    def test_the_exact_headline_and_the_cta_offer_are_demanded(self):
        lines = on_image_text_lines(poster_brief(), HEADLINE)
        self.assertTrue(all(line.startswith('MUST:') for line in lines), lines)
        joined = '\n'.join(lines)
        self.assertIn(f'"{HEADLINE}"', joined)
        self.assertIn('word for word and correctly spelled', joined)
        self.assertIn('"MORE INFO"', joined)
        self.assertIn('"30% off this weekend"', joined)
        self.assertIn('vertically along one edge', joined)
        self.assertIn('high contrast', joined)
        self.assertIn('generous margins', joined)
        self.assertNotIn(NO_TEXT_LINE, lines)

    def test_ai_original_asks_for_the_clean_social_sale_composition(self):
        joined = '\n'.join(on_image_text_lines(poster_brief(), HEADLINE))
        self.assertIn('Compose a clean social-sale poster', joined)
        for element in ('framed border', 'centred photo panel', 'CTA pill',
                        'social icons', 'dotted accents'):
            self.assertIn(element, joined)
        self.assertNotIn(MIRROR_LINE, joined)

    def test_reference_mode_mirrors_the_reference_typography(self):
        brief = poster_brief(creative_direction={'mode': 'REFERENCE', 'selections': []})
        joined = '\n'.join(on_image_text_lines(brief, HEADLINE))
        self.assertIn(MIRROR_LINE, joined)
        self.assertIn("this brand's own colour palette", joined)
        self.assertIn(f'"{HEADLINE}"', joined)
        # The reference lends its typography; the layout is the rotating
        # archetype (the framed panel when none was picked), never a
        # hard-wired framed panel inside the mirror line itself.
        self.assertNotIn('framed border, centred photo panel', joined)
        self.assertIn('Compose a clean social-sale poster', joined)

    def test_a_brand_template_follows_the_templates_own_typography(self):
        # The uppercase-headline/CTA-pill social-sale style is for posters
        # designed from scratch. A template generation must follow the
        # template's own case treatment and add nothing the template lacks —
        # the founder's title-case template came back ALL CAPS with a second
        # CTA button under the template's own one.
        brief = poster_brief(creative_direction={
            'mode': '', 'selections': [{'kind': 'BRAND_TEMPLATE', 'title': 'Diwali'}],
        })
        joined = '\n'.join(on_image_text_lines(brief, HEADLINE))
        self.assertIn(f'"{HEADLINE}"', joined)
        self.assertIn('CAPITALISATION STYLE', joined)
        self.assertIn('do not force uppercase', joined)
        self.assertNotIn('call-to-action pill/button reading', joined)
        self.assertIn('EXACTLY ONE call-to-action element in total', joined)
        # The brand CTA and campaign offer are offered as slot wording, not
        # as new elements.
        self.assertIn('call-to-action wording: "MORE INFO"', joined)
        self.assertIn('offer wording: "30% off this weekend"', joined)
        self.assertNotIn(MIRROR_LINE, joined)
        self.assertNotIn('Compose a clean social-sale poster', joined)

    def test_inspired_fidelity_takes_the_mirror_branch_not_the_template_branch(self):
        # No pixels are attached in INSPIRED mode, so "the template's own
        # slots" would reference a design the model cannot see.
        brief = poster_brief(
            template_fidelity='INSPIRED',
            creative_direction={'mode': 'REFERENCE', 'selections': [
                {'kind': 'BRAND_TEMPLATE', 'title': 'Diwali'},
            ]},
        )
        joined = '\n'.join(on_image_text_lines(brief, HEADLINE))
        self.assertIn(MIRROR_LINE, joined)
        self.assertNotIn('CAPITALISATION STYLE', joined)

    def test_text_stops_at_the_headline_and_one_cta_offer_line(self):
        joined = '\n'.join(on_image_text_lines(poster_brief(), HEADLINE))
        self.assertIn('No other words on the image', joined)
        self.assertIn('no paragraphs', joined)

    def test_an_absent_cta_and_offer_are_not_invented(self):
        brief = poster_brief(offer='', structured={'identity': {'cta_keyword': ''}})
        joined = '\n'.join(on_image_text_lines(brief, HEADLINE))
        self.assertIn(f'"{HEADLINE}"', joined)
        self.assertNotIn('Also render', joined)
        self.assertNotIn('CTA pill', joined)
        self.assertNotIn('offer line', joined)

    def test_a_catalogue_template_leaves_the_words_to_the_compose_engine(self):
        brief = poster_brief(creative_direction={'mode': 'CATALOG_TEMPLATE', 'layout': 'x'})
        self.assertEqual(on_image_text_lines(brief, HEADLINE), [NO_TEXT_LINE])

    def test_no_headline_means_no_text_never_invented_words(self):
        self.assertEqual(on_image_text_lines(poster_brief(), ''), [NO_TEXT_LINE])
        self.assertEqual(on_image_text_lines(poster_brief(), '   '), [NO_TEXT_LINE])
        self.assertEqual(on_image_text_lines(poster_brief(), None), [NO_TEXT_LINE])

    def test_carousel_slides_keep_the_no_text_rule(self):
        for content_type in ('carousel', 'carousel_slide'):
            brief = poster_brief(contentType=content_type)
            self.assertEqual(on_image_text_lines(brief, HEADLINE), [NO_TEXT_LINE])

    def test_the_headline_is_whitespace_normalised_but_otherwise_verbatim(self):
        joined = '\n'.join(on_image_text_lines(poster_brief(), '  Fresh   beans, daily!  '))
        self.assertIn('"Fresh beans, daily!"', joined)


class GatewayBriefTests(TenantFixtureMixin, TestCase):
    """The gateway no longer decides the words: the directive is per dispatch."""

    def setUp(self):
        self.ws = self.make_workspace('Acme', 'c1')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Acme Co', is_default=True,
        )

    def brief_lines(self, task):
        context = build_generation_context(self.ws, self.brand, task)
        return context_as_brief(context)['brand_context']

    def test_the_image_brief_no_longer_forbids_rendered_text(self):
        lines = self.brief_lines(TaskType.IMAGE)
        self.assertNotIn(NO_TEXT_LINE, lines)
        self.assertFalse(any('no text' in line for line in lines), lines)

    def test_the_copy_brief_carries_no_image_constraint(self):
        lines = self.brief_lines(TaskType.COPY)
        self.assertFalse(any('lettering' in line for line in lines), lines)


class PosterImageBriefTests(TenantFixtureMixin, TestCase):
    """The headline the copy call wrote reaches the image call, verbatim."""

    def setUp(self):
        self.ws = self.make_workspace('Acme', 'c1')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Acme Co', is_default=True,
            cta_keyword='MORE INFO',
        )

    def poster_extra(self, **overrides):
        extra = {
            'contentType': 'poster', 'offer': '30% off',
            'creative_direction': {'mode': 'AI_ORIGINAL', 'selections': []},
        }
        extra.update(overrides)
        return extra

    def test_the_image_is_asked_for_after_the_copy_and_carries_its_headline(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', recording_router(calls)):
            outcome = generate_copy_and_image(
                self.ws, self.brand, self.poster_extra(), instruction='Launch',
            )
        self.assertEqual(
            [c['capability'] for c in calls], [Capability.TEXT, Capability.IMAGE],
        )
        image_lines = calls[1]['brief']['brand_context']
        self.assertTrue(lines_with(image_lines, f'"{HEADLINE}"'), image_lines)
        self.assertTrue(lines_with(image_lines, '"30% off"'), image_lines)
        self.assertTrue(lines_with(image_lines, '"MORE INFO"'), image_lines)
        self.assertNotIn(NO_TEXT_LINE, image_lines)
        # The copy brief carries none of it - the words are the copy's job.
        self.assertFalse(lines_with(calls[0]['brief']['brand_context'], HEADLINE_LINE))
        self.assertEqual(outcome['text']['headline'], HEADLINE)
        self.assertEqual(outcome['image']['image_url'], FAKE_IMAGE['image_url'])

    def test_reference_mode_reaches_the_image_provider_as_a_mirror_instruction(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', recording_router(calls)):
            generate_copy_and_image(
                self.ws, self.brand,
                self.poster_extra(creative_direction={'mode': 'REFERENCE', 'selections': []}),
                instruction='Launch',
            )
        image_lines = calls[1]['brief']['brand_context']
        self.assertTrue(lines_with(image_lines, MIRROR_LINE), image_lines)
        self.assertTrue(lines_with(image_lines, f'"{HEADLINE}"'), image_lines)

    def test_a_catalogue_template_poster_still_ships_a_textless_photo(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', recording_router(calls)):
            generate_copy_and_image(
                self.ws, self.brand,
                self.poster_extra(creative_direction={'mode': 'CATALOG_TEMPLATE', 'layout': 'x'}),
                instruction='Launch',
            )
        image_lines = calls[1]['brief']['brand_context']
        self.assertIn(NO_TEXT_LINE, image_lines)
        self.assertFalse(lines_with(image_lines, HEADLINE_LINE), image_lines)

    def test_a_failed_copy_call_leaves_the_image_textless_rather_than_invented(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', recording_router(calls, text_fails=True)):
            outcome = generate_copy_and_image(
                self.ws, self.brand, self.poster_extra(), instruction='Launch',
            )
        self.assertIsNone(outcome['text'])
        self.assertIsNotNone(outcome['image'])
        self.assertIn(NO_TEXT_LINE, calls[1]['brief']['brand_context'])

    def test_an_image_retry_carries_the_saved_headline(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', recording_router(calls)):
            retry_image(
                self.ws, self.brand, self.poster_extra(headline=HEADLINE),
                instruction='Launch',
            )
        self.assertEqual([c['capability'] for c in calls], [Capability.IMAGE])
        image_lines = calls[0]['brief']['brand_context']
        self.assertTrue(lines_with(image_lines, f'"{HEADLINE}"'), image_lines)

    def test_an_image_only_revision_keeps_the_previous_headline_on_the_poster(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', recording_router(calls)):
            retry_image(
                self.ws, self.brand, self.poster_extra(previous_headline='Kept words'),
                instruction='Revise',
            )
        self.assertTrue(lines_with(calls[0]['brief']['brand_context'], '"Kept words"'))

    def test_carousel_slides_are_unchanged_the_words_stay_off_the_slide(self):
        calls = []
        with patch('apps.ai.router.AIRouter.dispatch', recording_router(calls)):
            generate_carousel_and_copy(
                self.ws, self.brand,
                {'contentType': 'carousel', 'slides': [{'position': 1, 'description': 'Hook'}]},
                instruction='Launch',
            )
        slide = next(c for c in calls if c['capability'] == Capability.IMAGE)
        slide_lines = slide['brief']['brand_context']
        self.assertIn(NO_TEXT_LINE, slide_lines)
        self.assertFalse(lines_with(slide_lines, HEADLINE_LINE), slide_lines)

    def test_video_briefs_are_untouched(self):
        calls = []
        with (
            patch('apps.ai.router.AIRouter.dispatch', recording_router(calls)),
            patch('apps.context.services.generation.persist_generated_video',
                  lambda workspace, result: result),
        ):
            generate_video_and_copy(
                self.ws, self.brand, {'contentType': 'video'}, instruction='Launch',
            )
        video = next(c for c in calls if c['capability'] == Capability.VIDEO)
        video_lines = video['brief']['brand_context']
        self.assertNotIn(NO_TEXT_LINE, video_lines)
        self.assertFalse(lines_with(video_lines, HEADLINE_LINE), video_lines)
        self.assertFalse(lines_with(video_lines, MIRROR_LINE), video_lines)
