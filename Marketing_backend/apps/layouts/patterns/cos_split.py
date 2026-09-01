"""Horizontal split: photograph above, a solid tone block of type below."""
from PIL import ImageDraw

from .base import LayoutPattern


class CosSplit(LayoutPattern):
    key = 'cos_split'
    display_name = 'Split tone'
    description = 'Photograph above, a solid block of type below.'
    industries = ('retail', 'food', 'beauty', 'fashion')

    #: Share of the height the photograph takes.
    SPLIT = 0.58

    def render(self):
        spec = self.spec
        image = self.canvas(spec.ink)

        photo_h = int(spec.height * self.SPLIT)
        image.paste(self.photo_or_placeholder(spec.width, photo_h), (0, 0))

        draw = ImageDraw.Draw(image)
        draw.rectangle([0, photo_h, spec.width, spec.height], fill=spec.ink)

        pad = self.u(72)
        inner = spec.width - pad * 2
        y = photo_h + self.u(56)
        floor = self.floor(56)

        if spec.tagline:
            eyebrow = self.font(20, bold=True)
            draw.text((pad, y), spec.tagline.upper()[:44], font=eyebrow, fill=spec.accent)
            y += self.u(44)

        reserved = self.u(110) if (spec.offer or spec.cta) else 0
        font, lines, line_h = self.fit(
            draw, spec.headline, inner, max(self.u(60), floor - y - reserved),
            start=64, minimum=24,
        )
        y = self.draw_lines(draw, lines, font, pad, y, line_h, spec.paper)

        if spec.subheadline and y + self.u(60) < floor - reserved:
            y += self.u(16)
            sub, sub_lines, sub_h = self.fit(
                draw, spec.subheadline, inner, self.u(96),
                start=24, minimum=13, bold=False, body=True,
            )
            y = self.draw_lines(draw, sub_lines, sub, pad, y, sub_h, spec.paper)

        # Offer and CTA share the last line: offer left, CTA right.
        baseline = floor - self.u(40)
        if spec.offer:
            offer = self.font(38, bold=True)
            draw.text((pad, baseline - self.u(10)), spec.offer[:40], font=offer, fill=spec.accent)
        if spec.cta:
            cta = self.font(20, bold=True)
            text = spec.cta.upper()[:36]
            draw.text(
                (spec.width - pad - draw.textlength(text, font=cta), baseline),
                text, font=cta, fill=spec.paper,
            )

        return image
