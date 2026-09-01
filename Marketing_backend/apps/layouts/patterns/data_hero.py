"""The number is the poster: the offer set enormous, everything else caption."""
import re

from PIL import ImageDraw

from .base import LayoutPattern

# "50% OFF" -> ("50%", "OFF"). The figure carries the layout; the rest labels it.
_FIGURE = re.compile(r'^\s*([\d]+[\d.,]*\s*%?|[£$€₹]\s*[\d][\d.,]*)\s*(.*)$', re.UNICODE)


class DataHero(LayoutPattern):
    key = 'data_hero'
    display_name = 'Data hero'
    description = 'One enormous figure, with the message as caption.'
    uses_photo = False
    industries = ('saas', 'finance', 'retail', 'fitness')

    def split_offer(self):
        """Figure and remainder, falling back to the whole string as figure."""
        match = _FIGURE.match(self.spec.offer or '')
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return (self.spec.offer or '').strip(), ''

    def render(self):
        spec = self.spec
        image = self.canvas(spec.accent)
        draw = ImageDraw.Draw(image)

        pad = self.u(80)
        inner = spec.width - pad * 2

        figure, qualifier = self.split_offer()
        if not figure:
            # Nothing numeric to lead with — the headline takes the hero slot.
            figure, qualifier = spec.headline, ''

        caption = spec.headline if figure != spec.headline else spec.subheadline

        # Measure the whole stack first, then centre it in the space above the
        # CTA. Laying it out from the top instead leaves a large dead band in
        # the middle whenever the figure is short, which is most of the time.
        top_margin = self.u(96)
        cta_block = self.u(140) if spec.cta else self.u(60)
        available = self.floor(96) - top_margin - cta_block

        eyebrow_h = self.u(52) if spec.tagline else 0
        hero, hero_lines, hero_line_h = self.fit(
            draw, figure, inner, self.u(560), start=260, minimum=48, leading=0.98
        )
        hero_h = len(hero_lines) * hero_line_h
        qualifier_h = self.u(76) if qualifier else 0
        rule_h = self.u(70)

        caption_font, caption_lines, caption_line_h = self.fit(
            draw, caption, inner, self.u(220), start=44, minimum=18, bold=False, body=True
        )
        caption_h = len(caption_lines) * caption_line_h

        stack = eyebrow_h + hero_h + qualifier_h + rule_h + caption_h
        y = top_margin + max(0, (available - stack) / 2)

        if spec.tagline:
            eyebrow = self.font(20, bold=True)
            draw.text((pad, y), spec.tagline.upper()[:44], font=eyebrow, fill=spec.ink)
            y += eyebrow_h

        y = self.draw_lines(draw, hero_lines, hero, pad, y, hero_line_h, spec.ink)

        if qualifier:
            qual = self.font(46, bold=True)
            draw.text((pad, y + self.u(6)), qualifier.upper()[:28], font=qual, fill=spec.ink)
            y += qualifier_h

        y += self.u(30)
        draw.line([(pad, y), (spec.width - pad, y)], fill=spec.ink, width=max(1, self.u(4)))
        y += self.u(40)

        self.draw_lines(draw, caption_lines, caption_font, pad, y, caption_line_h, spec.ink)

        if spec.cta:
            cta = self.font(24, bold=True)
            text = spec.cta.upper()[:44]
            width = draw.textlength(text, font=cta) + self.u(52)
            height = self.u(64)
            top = self.floor(96) - height
            draw.rectangle([pad, top, pad + width, top + height], fill=spec.ink)
            draw.text(
                (pad + self.u(26), top + (height - self.u(24)) / 2 - self.u(3)),
                text, font=cta, fill=spec.accent,
            )

        return image
