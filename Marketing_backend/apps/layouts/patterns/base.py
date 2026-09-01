"""
Layout plugin contract.

Mirrors `SocialPlatformAdapter` and `AIProviderAdapter` — the pattern this
codebase already uses twice for pluggable behaviour. Adding a layout is one
new file under `patterns/`; the registry finds it and nothing else changes.

Every pattern draws against a `Spec`, and every measurement is expressed in
*units* rather than pixels. One unit is 1/1080 of the canvas width, so the
same code composes a 1080x1350 Instagram portrait and a 1600x900 X card
without a second implementation or a resize — which is the whole point of
composing locally instead of asking an image model for a finished poster.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from apps.layouts import fonts

#: Canvas width every pattern is authored against.
REFERENCE_WIDTH = 1080

DEFAULT_PALETTE = {'primary': '#221F3C', 'light': '#FDFFE9', 'accent': '#D2FFAA'}
DEFAULT_FONTS = {'primary': 'DM Sans', 'secondary': 'Noto Serif'}


@dataclass
class Spec:
    """Everything a pattern is allowed to know about."""

    width: int = 1080
    height: int = 1350

    headline: str = ''
    subheadline: str = ''
    offer: str = ''
    cta: str = ''
    tagline: str = ''
    phone: str = ''

    palette: dict = field(default_factory=lambda: dict(DEFAULT_PALETTE))
    fonts: dict = field(default_factory=lambda: dict(DEFAULT_FONTS))

    photo: Optional[Image.Image] = None
    logo: Optional[Image.Image] = None

    # Free-form per-pattern overrides, straight from ContentItem.layout_config.
    config: dict = field(default_factory=dict)

    # -- colours ---------------------------------------------------------
    def colour(self, role: str, default: str) -> str:
        value = (self.palette or {}).get(role)
        return value if _is_colour(value) else default

    @property
    def ink(self) -> str:
        return self.colour('primary', DEFAULT_PALETTE['primary'])

    @property
    def paper(self) -> str:
        return self.colour('light', DEFAULT_PALETTE['light'])

    @property
    def accent(self) -> str:
        return self.colour('accent', DEFAULT_PALETTE['accent'])

    # -- typefaces -------------------------------------------------------
    @property
    def display_family(self) -> str:
        return (self.fonts or {}).get('primary') or DEFAULT_FONTS['primary']

    @property
    def body_family(self) -> str:
        return (self.fonts or {}).get('secondary') or DEFAULT_FONTS['secondary']


def _is_colour(value) -> bool:
    """A hex string PIL will accept. Anything else falls back to the default."""
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not value.startswith('#') or len(value) not in (4, 7):
        return False
    return all(c in '0123456789abcdefABCDEF' for c in value[1:])


class LayoutPattern(ABC):
    """One way of arranging a poster."""

    #: Matches Brand.Layout values.
    key: str = ''
    display_name: str = ''
    description: str = ''
    #: False for patterns that are pure type and would be spoiled by a photo.
    uses_photo: bool = True
    #: Lowercase industry tags this skeleton suits, used to group and filter
    #: the template gallery. Empty means "fits anything". Purely descriptive:
    #: nothing stops a brand using any pattern.
    industries: tuple = ()

    def __init__(self, spec: Spec):
        self.spec = spec
        self.unit = spec.width / REFERENCE_WIDTH

    # -- units -----------------------------------------------------------
    def u(self, value: float) -> int:
        """Reference pixels -> canvas pixels."""
        return int(round(value * self.unit))

    def font(self, size: float, *, bold: bool = False, body: bool = False):
        family = self.spec.body_family if body else self.spec.display_family
        return fonts.load(family, self.u(size), bold)

    @property
    def footer(self) -> int:
        """
        Height the phone strip overlay will occupy.

        Patterns lay out against `floor()` rather than the canvas bottom, so
        the overlay never lands on top of a pattern's own footer row. Keeping
        the number here rather than in each pattern means the overlay and the
        reservation cannot drift apart.
        """
        return int(round(74 * self.unit)) if self.spec.phone else 0

    def floor(self, margin: float = 0) -> int:
        """The lowest y a pattern may draw to, given a bottom margin."""
        return self.spec.height - self.footer - self.u(margin)

    @property
    def logo_reserve(self) -> int:
        """
        Width the logo overlay claims in the top-right corner.

        Patterns that run content full-width across the top must subtract this,
        or a headline will be printed underneath the logo plate.
        """
        return int(round(210 * self.unit)) if self.spec.logo is not None else 0

    def head_width(self, inner: int, y: float) -> int:
        """`inner`, narrowed while y is still inside the logo's band."""
        if y > int(round(200 * self.unit)):
            return inner
        return max(int(inner * 0.4), inner - self.logo_reserve)

    # -- drawing helpers -------------------------------------------------
    def canvas(self, colour: Optional[str] = None) -> Image.Image:
        return Image.new(
            'RGB', (self.spec.width, self.spec.height), colour or self.spec.paper
        )

    @staticmethod
    def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> List[str]:
        """Greedy word wrap. A word longer than the line is left to overflow."""
        words = (text or '').split()
        if not words:
            return []
        lines, current = [], words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def fit(self, draw, text: str, max_width: int, max_height: int, *,
            start: float, minimum: float = 14, bold: bool = True,
            body: bool = False, leading: float = 1.12):
        """
        Largest size at which `text` fits the box, and the wrapped lines.

        Shrink-to-fit rather than truncate: a headline the reviewer wrote is
        the message, so losing its tail is worse than setting it smaller.
        """
        size = start
        while size > minimum:
            font = self.font(size, bold=bold, body=body)
            lines = self.wrap(draw, text, font, max_width)
            height = len(lines) * self.u(size) * leading
            if height <= max_height:
                return font, lines, self.u(size) * leading
            size -= max(1.0, size * 0.06)

        font = self.font(minimum, bold=bold, body=body)
        return (
            font,
            self.wrap(draw, text, font, max_width),
            self.u(minimum) * leading,
        )

    @staticmethod
    def draw_lines(draw, lines, font, x: int, y: float, line_height: float,
                   fill: str, centre_width: Optional[int] = None) -> float:
        """Draws wrapped lines and returns the y just past the last one."""
        for line in lines:
            left = x
            if centre_width is not None:
                left = x + (centre_width - draw.textlength(line, font=font)) / 2
            draw.text((left, y), line, font=font, fill=fill)
            y += line_height
        return y

    @staticmethod
    def cover(photo: Image.Image, width: int, height: int) -> Image.Image:
        """Crop-to-fill, centred. Never distorts the aspect ratio."""
        width, height = max(1, int(width)), max(1, int(height))
        source = photo.convert('RGB')
        scale = max(width / source.width, height / source.height)
        resized = source.resize(
            (max(1, int(source.width * scale)), max(1, int(source.height * scale))),
            Image.LANCZOS,
        )
        left = (resized.width - width) // 2
        top = (resized.height - height) // 2
        return resized.crop((left, top, left + width, top + height))

    def placeholder(self, width: int, height: int) -> Image.Image:
        """
        Stands in for a missing photo.

        A flat accent panel rather than a grey box: a poster with no image
        should still look composed, because plenty of brands run type-only.
        """
        return Image.new('RGB', (max(1, int(width)), max(1, int(height))), self.spec.accent)

    def photo_or_placeholder(self, width: int, height: int) -> Image.Image:
        if self.spec.photo is not None and self.uses_photo:
            return self.cover(self.spec.photo, width, height)
        return self.placeholder(width, height)

    @staticmethod
    def scrim(image: Image.Image, colour: str, opacity: float) -> Image.Image:
        """Tints an image so text laid over it stays readable."""
        overlay = Image.new('RGB', image.size, colour)
        return Image.blend(image, overlay, max(0.0, min(1.0, opacity)))

    # -- contract --------------------------------------------------------
    @abstractmethod
    def render(self) -> Image.Image:
        """Compose and return the poster. Overlays are applied afterwards."""

    # -- catalogue -------------------------------------------------------
    @classmethod
    def describe(cls) -> dict:
        return {
            'key': cls.key,
            'display_name': cls.display_name or cls.key,
            'description': cls.description,
            'uses_photo': cls.uses_photo,
            'industries': list(cls.industries),
        }


def text_box(spec: Spec) -> Tuple[int, int]:
    """Conventional side margin and content width."""
    margin = int(spec.width * 0.083)
    return margin, spec.width - margin * 2
