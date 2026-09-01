"""Two-column comparison table: us versus them, or before versus after."""
from PIL import ImageDraw

from .base import LayoutPattern


class VsTable(LayoutPattern):
    key = 'vs_table'
    display_name = 'Versus table'
    description = 'Two-column comparison — ours against theirs.'
    uses_photo = False
    industries = ('saas', 'finance', 'education', 'services')

    DEFAULT_ROWS = [
        ('Price', 'Higher'),
        ('Quality', 'Inconsistent'),
        ('Support', 'None'),
    ]

    def rows(self):
        """
        `layout_config.rows` is [[ours, theirs], ...].

        Falls back to a skeleton rather than rendering an empty table, so the
        pattern is previewable before anyone has filled it in.
        """
        raw = self.spec.config.get('rows')
        if not isinstance(raw, list) or not raw:
            return list(self.DEFAULT_ROWS)
        out = []
        for row in raw[:6]:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                out.append((str(row[0])[:40], str(row[1])[:40]))
        return out or list(self.DEFAULT_ROWS)

    def headers(self):
        config = self.spec.config
        ours = str(config.get('ours') or self.spec.tagline or 'Us')[:20]
        theirs = str(config.get('theirs') or 'Them')[:20]
        return ours, theirs

    def render(self):
        spec = self.spec
        image = self.canvas(spec.paper)
        draw = ImageDraw.Draw(image)

        pad = self.u(72)
        inner = spec.width - pad * 2
        y = self.u(90)

        font, lines, line_h = self.fit(
            draw, spec.headline, self.head_width(inner, y), self.u(230),
            start=62, minimum=24,
        )
        y = self.draw_lines(draw, lines, font, pad, y, line_h, spec.ink)
        y += self.u(56)

        rows = self.rows()
        ours, theirs = self.headers()

        col_w = inner // 2
        header_h = self.u(76)

        # The table takes the space that is actually left, so three rows and
        # six rows both fill the poster instead of leaving half of it empty.
        bottom_block = self.u(180)
        space = self.floor(72) - y - bottom_block
        row_h = max(self.u(76), min(self.u(150), int(space / max(1, len(rows)))))
        table_h = header_h + row_h * len(rows)

        # Our column is the accent block; theirs is left plain. The visual
        # weight is the argument.
        draw.rectangle([pad, y, pad + col_w, y + table_h], fill=spec.accent)

        head = self.font(26, bold=True)
        draw.text((pad + self.u(28), y + self.u(22)), ours.upper(), font=head, fill=spec.ink)
        draw.text(
            (pad + col_w + self.u(28), y + self.u(22)), theirs.upper(), font=head, fill=spec.ink
        )

        cell = self.font(24, bold=False, body=True)
        row_y = y + header_h
        for index, (mine, other) in enumerate(rows):
            # A rule under the header too, not only between rows — without it
            # the header and the first row read as one cell.
            draw.line(
                [(pad, row_y), (pad + inner, row_y)],
                fill=spec.ink, width=max(1, self.u(3 if index == 0 else 1)),
            )
            text_y = row_y + (row_h - self.u(24)) / 2 - self.u(4)
            draw.text((pad + self.u(28), text_y), mine, font=cell, fill=spec.ink)
            draw.text((pad + col_w + self.u(28), text_y), other, font=cell, fill=spec.ink)
            row_y += row_h

        draw.rectangle(
            [pad, y, pad + inner, y + table_h], outline=spec.ink, width=max(1, self.u(3))
        )
        draw.line(
            [(pad + col_w, y), (pad + col_w, y + table_h)],
            fill=spec.ink, width=max(1, self.u(3)),
        )

        # Offer and CTA sit on the base line rather than trailing the table,
        # so the poster is anchored top and bottom.
        floor = self.floor(72)

        if spec.cta:
            cta = self.font(22, bold=True)
            draw.text((pad, floor - self.u(30)), spec.cta.upper()[:44], font=cta, fill=spec.ink)

        if spec.offer:
            offer = self.font(40, bold=True)
            draw.text(
                (pad, floor - self.u(100)), spec.offer[:44], font=offer, fill=spec.ink
            )

        return image
