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
import math
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

    #: Focal-point steering for photo crops: {'x': fx, 'y': fy} normalized
    #: 0..1 in source coordinates, optionally with 'bbox': [x0, y0, x1, y1]
    #: (the subject's bounds, also normalized). None keeps the historical
    #: centred crop. Populated from layout_config['photo_focus'] by the
    #: automatic compose; every pattern gets it for free through
    #: `photo_or_placeholder`.
    photo_focus: Optional[dict] = None

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
    def cover(photo: Image.Image, width: int, height: int,
              focus: Optional[dict] = None) -> Image.Image:
        """Crop-to-fill. Never distorts the aspect ratio.

        ``focus`` steers where the crop window lands on the resized photo:

        * ``None`` (default) — the historical centred crop, pixel for pixel.
        * ``{'x': fx, 'y': fy}`` — a focal point in normalized 0..1 source
          coordinates; the window is centred on it, then clamped inside the
          resized image.
        * optional ``'bbox': [x0, y0, x1, y1]`` (normalized) — the subject's
          bounds. Geometry, not a second AI call, keeps the subject whole:
          per axis, a bbox that fits the window shifts the window the
          minimum distance needed to contain it; a bbox larger than the
          window centres the window on the bbox instead.

        The focus values come from client-writable JSON, so everything is
        re-validated here; anything malformed degrades to the centred crop.
        """
        width, height = max(1, int(width)), max(1, int(height))
        source = photo.convert('RGB')
        scale = max(width / source.width, height / source.height)
        resized = source.resize(
            (max(1, int(source.width * scale)), max(1, int(source.height * scale))),
            Image.LANCZOS,
        )
        fx, fy, bbox = _focus_values(focus)
        left = _crop_origin(fx, resized.width, width,
                            (bbox[0], bbox[2]) if bbox else None)
        top = _crop_origin(fy, resized.height, height,
                           (bbox[1], bbox[3]) if bbox else None)
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
            # The one seam every pattern's photo goes through, so a focal
            # point on the Spec fixes face-cutting crops in all of them.
            return self.cover(self.spec.photo, width, height, self.spec.photo_focus)
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


# -- focal-point crop maths ------------------------------------------------
def _unit_interval(value, default):
    """`value` as a float clamped to 0..1, or `default` when it is not one."""
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default


def _focus_values(focus) -> Tuple[float, float, Optional[list]]:
    """(fx, fy, bbox) out of a focus dict, defensively.

    The dict ultimately comes from `layout_config`, which is client-writable
    JSON — so every number is re-validated even though `detect_photo_focus`
    clamps its own output. Malformed input degrades to the centred default
    (0.5, 0.5, no bbox) rather than raising out of a render.
    """
    if not isinstance(focus, dict):
        return 0.5, 0.5, None
    fx = _unit_interval(focus.get('x'), 0.5)
    fy = _unit_interval(focus.get('y'), 0.5)
    bbox = None
    raw = focus.get('bbox')
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        values = [_unit_interval(v, None) for v in raw]
        if None not in values and values[2] > values[0] and values[3] > values[1]:
            bbox = values
    return fx, fy, bbox


def _crop_origin(focal: float, resized: int, window: int, span) -> int:
    """Left/top of a crop window along one axis.

    `focal` is the normalized focal coordinate, `resized` the resized photo's
    extent, `window` the crop's extent, and `span` the subject bbox's
    normalized (lo, hi) on this axis, or None when no bbox is known.

    Start by centring the window on the focal point. int() floors here on
    purpose: floor(0.5 * n - w / 2) == (n - w) // 2 for every n and w, so
    the default 0.5 focal point reproduces the historical centred crop
    pixel for pixel (Python's round() half-to-even would drift by 1px on
    odd slack).
    """
    origin = int(focal * resized - window / 2)
    if span is not None:
        lo, hi = span[0] * resized, span[1] * resized
        if hi - lo <= window:
            # The subject fits: shift only as far as containment demands.
            # Applied lo-side first, hi-side last (ceil, so a fractional
            # edge is not left half a pixel outside); when a bbox exactly
            # the window's size straddles a pixel boundary the hi side wins
            # by under a pixel — the closest any integer crop can get.
            origin = min(origin, int(lo))
            origin = max(origin, math.ceil(hi) - window)
        else:
            # The subject cannot fit: centre on it and crop equally from
            # both ends — the least-bad window.
            origin = int((lo + hi) / 2 - window / 2)
    # Never read outside the resized image.
    return max(0, min(origin, resized - window))
