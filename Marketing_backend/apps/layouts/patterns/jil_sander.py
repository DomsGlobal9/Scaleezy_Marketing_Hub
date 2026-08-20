"""Minimal centred: small type, enormous margins, one quiet image."""
from PIL import ImageDraw

from .base import LayoutPattern


class JilSander(LayoutPattern):
    key = 'jil_sander'
    display_name = 'Minimal centred'
    description = 'Small centred type and generous whitespace around one image.'

    def render(self):
        spec = self.spec
        image = self.canvas(spec.paper)
        draw = ImageDraw.Draw(image)

        margin = self.u(130)
        inner = spec.width - margin * 2

        y = self.u(120)

        if spec.tagline:
            eyebrow = self.font(18, bold=True)
            text = spec.tagline.upper()[:40]
            draw.text(
                (margin + (inner - draw.textlength(text, font=eyebrow)) / 2, y),
                text, font=eyebrow, fill=spec.ink,
            )
            y += self.u(56)

        font, lines, line_h = self.fit(
            draw, spec.headline, inner, self.u(280),
            start=54, minimum=22, bold=False, leading=1.24,
        )
        y = self.draw_lines(draw, lines, font, margin, y, line_h, spec.ink, centre_width=inner)

        y += self.u(48)

        # The image sits in the remaining space, leaving room for the footer.
        footer = self.u(190) + self.footer
        frame_h = max(self.u(120), spec.height - y - footer)
        image.paste(self.photo_or_placeholder(inner, frame_h), (margin, int(y)))
        y += frame_h + self.u(46)

        if spec.offer:
            offer = self.font(28, bold=True)
            text = spec.offer[:60]
            draw.text(
                (margin + (inner - draw.textlength(text, font=offer)) / 2, y),
                text, font=offer, fill=spec.ink,
            )
            y += self.u(52)

        if spec.cta:
            cta = self.font(18, bold=True)
            text = spec.cta.upper()[:48]
            width = draw.textlength(text, font=cta)
            x = margin + (inner - width) / 2
            draw.text((x, y), text, font=cta, fill=spec.ink)
            # Hairline rule under the CTA — the only ornament this layout gets.
            rule_y = y + self.u(30)
            draw.line([(x, rule_y), (x + width, rule_y)], fill=spec.ink, width=max(1, self.u(2)))

        return image
