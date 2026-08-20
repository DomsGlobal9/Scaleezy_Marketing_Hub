"""
Composing a poster.

The engine: brand palette + brand fonts + a photograph + a layout pattern go
in, a finished image comes out. Nothing here calls an image model — that is
the point. An AI-generated poster is different every time and only accidentally
on-brand; a composed one uses the brand's actual colours and typefaces every
time, at any size.

Logo and phone overlays are applied here rather than inside each pattern, so
all six behave identically and a new pattern gets them for free.
"""
import logging
from dataclasses import replace
from typing import Optional

from PIL import Image, ImageDraw

from . import images, registry
from .fonts import load as load_font
from .patterns.base import Spec

logger = logging.getLogger(__name__)


class RenderError(Exception):
    """The poster could not be composed."""


def spec_from(brand, *, headline='', subheadline='', offer='', cta='',
              width=1080, height=1350, photo=None, logo=None,
              include_logo=None, include_phone=None, phone='',
              config=None) -> Spec:
    """
    Builds a render spec from a Brand plus the copy for one post.

    `include_logo` / `include_phone` default to the brand's own setting, and
    the caller may override them per generation — which is exactly what the
    publishing wizard's "Brand add-ons" toggles have always claimed to do.
    """
    palette = brand.palette if brand and isinstance(brand.palette, dict) else None
    fonts = brand.fonts if brand and isinstance(brand.fonts, dict) else None

    if include_logo is None:
        include_logo = bool(brand and brand.show_logo_on_posters)
    if include_phone is None:
        include_phone = bool(brand and brand.show_phone_on_posters)

    if include_logo and logo is None and brand is not None and brand.logo_url:
        logo = images.from_trusted_url(brand.logo_url)

    resolved_phone = (phone or (brand.contact_phone if brand else '') or '').strip()

    return Spec(
        width=int(width),
        height=int(height),
        headline=headline or '',
        subheadline=subheadline or '',
        offer=offer or '',
        cta=cta or (brand.cta_keyword if brand else '') or '',
        tagline=(brand.tagline if brand else '') or '',
        phone=resolved_phone if include_phone else '',
        palette=palette or {},
        fonts=fonts or {},
        photo=photo,
        logo=logo if include_logo else None,
        config=config or {},
    )


def compose(spec: Spec, layout_key: str) -> Image.Image:
    """Runs the pattern and applies the shared overlays."""
    pattern_cls = registry.resolve(layout_key)
    if pattern_cls is None:
        raise RenderError("No layout patterns are installed.")

    try:
        image = pattern_cls(spec).render()
    except Exception as exc:
        logger.exception("Layout %s failed to render", layout_key)
        raise RenderError(f"Layout '{layout_key}' failed: {exc}") from exc

    image = _overlay_logo(image, spec)
    image = _overlay_phone(image, spec)
    return image


def compose_at(spec: Spec, layout_key: str, width: int, height: int) -> Image.Image:
    """
    Composes at a different canvas size.

    Re-runs the pattern rather than resizing the 1080-wide poster: type stays
    crisp, and a wide X card gets a genuinely wide composition instead of a
    letterboxed portrait.
    """
    return compose(replace(spec, width=int(width), height=int(height)), layout_key)


# -- overlays -------------------------------------------------------------
def _overlay_logo(image: Image.Image, spec: Spec) -> Image.Image:
    if spec.logo is None:
        return image

    unit = spec.width / 1080
    box = int(110 * unit)
    margin = int(48 * unit)

    logo = spec.logo.convert('RGBA')
    scale = min(box / logo.width, box / logo.height)
    logo = logo.resize(
        (max(1, int(logo.width * scale)), max(1, int(logo.height * scale))), Image.LANCZOS
    )

    # A soft plate behind the logo so a dark mark stays visible on a dark
    # poster and vice versa.
    pad = int(14 * unit)
    plate = Image.new(
        'RGBA',
        (logo.width + pad * 2, logo.height + pad * 2),
        _rgba(spec.paper, 235),
    )
    plate.alpha_composite(logo, (pad, pad))

    canvas = image.convert('RGBA')
    canvas.alpha_composite(
        plate, (spec.width - plate.width - margin, margin)
    )
    return canvas.convert('RGB')


def _overlay_phone(image: Image.Image, spec: Spec) -> Image.Image:
    if not spec.phone:
        return image

    unit = spec.width / 1080
    height = int(74 * unit)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, spec.height - height, spec.width, spec.height], fill=spec.ink)

    font = load_font(spec.display_family, max(1, int(28 * unit)), True)
    text = spec.phone[:40]
    width = draw.textlength(text, font=font)
    draw.text(
        ((spec.width - width) / 2, spec.height - height + (height - 28 * unit) / 2 - 2 * unit),
        text, font=font, fill=spec.accent,
    )
    return image


def _rgba(hex_colour: str, alpha: int):
    value = (hex_colour or '#FFFFFF').lstrip('#')
    if len(value) == 3:
        value = ''.join(c * 2 for c in value)
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)
    except ValueError:
        return (255, 255, 255, alpha)


# -- convenience ----------------------------------------------------------
def photo_for(*, photo_base64: str = '', asset=None) -> Optional[Image.Image]:
    """
    Resolves the photograph.

    Either an upload from the caller, or an asset already in this workspace —
    whose URL the server owns. A raw URL from the client is never fetched.
    """
    if photo_base64:
        return images.from_base64(photo_base64)
    if asset is not None and getattr(asset, 'file_url', ''):
        return images.from_trusted_url(asset.file_url)
    return None
