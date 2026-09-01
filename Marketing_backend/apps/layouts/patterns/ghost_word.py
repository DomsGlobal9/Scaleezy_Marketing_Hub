"""One oversized word ghosted behind the photograph, headline on top."""
from PIL import Image, ImageDraw

from .base import LayoutPattern


class GhostWord(LayoutPattern):
    key = 'ghost_word'
    display_name = 'Ghost word'
    description = 'An oversized word ghosted behind the image.'
    industries = ('fashion', 'events', 'fitness', 'lifestyle')

    def ghost_text(self) -> str:
        """The single word to blow up: the occasion, else the longest word."""
        source = self.spec.config.get('ghost_word') or self.spec.tagline
        if not source:
            words = (self.spec.headline or '').split()
            source = max(words, key=len) if words else ''
        return (source or '').split()[0].upper()[:12] if source else ''

    def render(self):
        spec = self.spec
        image = self.canvas(spec.ink)
        draw = ImageDraw.Draw(image)

        word = self.ghost_text()
        if word:
            # Sized to the canvas width rather than to a fixed point size, so
            # a short word fills the poster and a long one still fits.
            size = 300.0
            while size > 60:
                font = self.font(size, bold=True)
                if draw.textlength(word, font=font) <= spec.width * 0.98:
                    break
                size -= 10
            font = self.font(size, bold=True)
            width = draw.textlength(word, font=font)
            draw.text(
                ((spec.width - width) / 2, spec.height * 0.16),
                word, font=font, fill=spec.accent,
            )

        # The photo sits over the ghost word as an inset panel, so the word
        # reads as bleeding out from behind it.
        pad = self.u(96)
        panel_w = spec.width - pad * 2
        panel_h = int(spec.height * 0.44)
        panel_y = int(spec.height * 0.28)
        image.paste(self.photo_or_placeholder(panel_w, panel_h), (pad, panel_y))

        y = panel_y + panel_h + self.u(52)
        floor = self.floor(72)
        inner = panel_w

        font, lines, line_h = self.fit(
            draw, spec.headline, inner, max(self.u(60), floor - y - self.u(80)),
            start=58, minimum=22,
        )
        y = self.draw_lines(draw, lines, font, pad, y, line_h, spec.paper)

        baseline = floor - self.u(34)
        if spec.offer:
            offer = self.font(30, bold=True)
            draw.text((pad, baseline), spec.offer[:40], font=offer, fill=spec.accent)
        if spec.cta:
            cta = self.font(20, bold=True)
            text = spec.cta.upper()[:36]
            draw.text(
                (spec.width - pad - draw.textlength(text, font=cta), baseline + self.u(8)),
                text, font=cta, fill=spec.paper,
            )

        return image
