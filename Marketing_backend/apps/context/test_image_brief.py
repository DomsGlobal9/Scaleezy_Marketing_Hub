"""
The image brief forbids provider-rendered text.

The composition engine owns every word on the poster. Without this constraint
the image models render their own headlines — reviewers saw half-cropped
double text and called the posters unfinished. The constraint is injected by
the Context Gateway so every adapter carries it, whichever provider is routed.
"""
from django.test import TestCase

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.context.services.context_gateway import (
    TaskType,
    build_generation_context,
    context_as_brief,
)


class ImageBriefNoTextTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.ws = self.make_workspace('Acme', 'c1')
        self.brand = Brand.objects.create(
            workspace=self.ws, name='Acme Co', is_default=True,
        )

    def brief_lines(self, task):
        context = build_generation_context(self.ws, self.brand, task)
        return context_as_brief(context)['brand_context']

    def test_the_image_brief_forbids_rendered_text(self):
        lines = self.brief_lines(TaskType.IMAGE)
        self.assertTrue(
            any(line.startswith('MUST:') and 'no text' in line for line in lines),
            lines,
        )

    def test_the_copy_brief_carries_no_image_constraint(self):
        lines = self.brief_lines(TaskType.COPY)
        self.assertFalse(any('lettering' in line for line in lines), lines)
