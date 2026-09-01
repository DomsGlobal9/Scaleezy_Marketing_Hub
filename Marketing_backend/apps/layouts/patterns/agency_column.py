"""Editorial two-column: a solid ink column of type against a full-bleed photo."""
from PIL import ImageDraw

from .base import LayoutPattern


class AgencyColumn(LayoutPattern):
    key = 'agency_column'
    display_name = 'Agency column'
    description = 'Ink column of type beside a full-bleed photograph.'
    industries = ('fashion', 'retail', 'agency', 'hospitality')

    #: Share of the width the type column takes.
    COLUMN = 0.46

    def render(self):
        spec = self.spec
        image = self.canvas(spec.paper)

        column_w = int(spec.width * self.COLUMN)
        photo_w = spec.width - column_w

        image.paste(self.photo_or_placeholder(photo_w, spec.height), (column_w, 0))

        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, column_w, spec.height], fill=spec.ink)

        pad = self.u(64)
        inner = column_w - pad * 2
        y = pad

        if spec.tagline:
            eyebrow = self.font(20, bold=True)
            draw.text((pad, y), spec.tagline.upper()[:40], font=eyebrow, fill=spec.accent)
            y += self.u(46)

        # The headline gets the whole column below the eyebrow, minus the room
        # the footer block needs.
        footer = self.u(210) + self.footer
        font, lines, line_h = self.fit(
            draw, spec.headline, inner, spec.height - y - footer, start=76, minimum=26
        )
        y = self.draw_lines(draw, lines, font, pad, y, line_h, spec.paper)

        if spec.subheadline:
            y += self.u(24)
            sub, sub_lines, sub_h = self.fit(
                draw, spec.subheadline, inner, self.u(180),
                start=26, minimum=14, bold=False, body=True,
            )
            y = self.draw_lines(draw, sub_lines, sub, pad, y, sub_h, spec.paper)

        bottom = self.floor(64)

        if spec.offer:
            offer = self.font(34, bold=True)
            box_h = self.u(74)
            box_w = min(inner, int(draw.textlength(spec.offer, font=offer)) + self.u(52))
            top = bottom - box_h
            draw.rectangle([pad, top, pad + box_w, bottom], fill=spec.accent)
            draw.text(
                (pad + self.u(26), top + (box_h - self.u(34)) / 2 - self.u(4)),
                spec.offer, font=offer, fill=spec.ink,
            )
            bottom = top - self.u(24)

        if spec.cta:
            cta = self.font(24, bold=True)
            draw.text(
                (pad, bottom - self.u(30)), spec.cta.upper()[:48], font=cta, fill=spec.accent
            )

        return image
