#!/usr/bin/env python3
"""Generate the Open Graph social cards under public/og/.

Run this when a marketing page's title changes; the PNGs it writes are
committed, so a deploy never depends on this script having been run.

    Marketing_backend/venv/bin/python Marketing_Frontend/scripts/build_og_images.py

Pillow is the only dependency and it is already in the backend requirements,
which is why this is Python rather than Node - the frontend has no image
library, and adding one to render six static images would be a poor trade.

The cards are drawn rather than photographed for the same reason the on-page
illustrations are: there is nothing truthful to photograph, and a mocked-up
dashboard would put invented numbers on the most-shared image the product has.
"""
from __future__ import annotations

import pathlib
import sys

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:  # pragma: no cover - operator feedback, not a code path
    sys.exit("Pillow is required: use Marketing_backend/venv/bin/python to run this.")

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "public" / "og"
WORDMARK = ROOT / "public" / "brand" / "scaleezy-wordmark.webp"

# 1200x630 is the size every major platform crops from; anything else gets
# letterboxed or centre-cropped by someone.
SIZE = (1200, 630)

# The brand tokens from styles.css, converted once. oklch(0.08 0 0) and the
# logo-sampled lime #B9D53C.
INK = (10, 10, 10)
LIME = (185, 213, 60)
WHITE = (255, 255, 255)
MUTED = (150, 150, 150)

# DM Sans is loaded from Google Fonts at runtime and is not installed locally,
# so the cards use the closest grotesque the OS ships. The wordmark itself is
# the real asset, which is what carries the brand at this size.
FONT_CANDIDATES = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

CARDS = [
    ("og-default.png", "Social marketing that knows your brand.", "Scaleezy Marketing Hub"),
    ("og-how-it-works.png", "From your brand's own material to a published post.", "How it works"),
    ("og-capabilities.png", "Everything between a brand document and a measured post.", "Capabilities"),
    ("og-trust.png", "An honest system beats a confident one.", "Trust"),
]


def load_font(size: int, *, bold: bool) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            try:
                # HelveticaNeue.ttc is a collection; index 1 is the bold face.
                if path.endswith(".ttc"):
                    return ImageFont.truetype(path, size, index=1 if bold else 0)
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Greedy word wrap measured against the real font, not a character count."""
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def build_card(filename: str, headline: str, label: str) -> pathlib.Path:
    card = Image.new("RGB", SIZE, INK)
    draw = ImageDraw.Draw(card)

    # A soft lime wash bleeding in from the top right, matching the hero on the
    # site. Pillow has no gradient primitive, so it is an ellipse pushed partly
    # off-canvas and genuinely blurred - resizing a small mask only produces a
    # hard-edged blob, which reads as a shape rather than as light.
    glow = Image.new("L", SIZE, 0)
    ImageDraw.Draw(glow).ellipse((760, -280, 1500, 320), fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    card.paste(Image.new("RGB", SIZE, LIME), (0, 0), glow)

    # The wordmark is white-and-lime on transparency, so it composites straight
    # onto the dark card. This is the one real brand asset on the image.
    if WORDMARK.exists():
        mark = Image.open(WORDMARK).convert("RGBA")
        target_w = 300
        mark = mark.resize((target_w, round(mark.height * target_w / mark.width)), Image.LANCZOS)
        card.paste(mark, (80, 72), mark)

    headline_font = load_font(66, bold=True)
    label_font = load_font(24, bold=False)

    draw.text((80, 214), label.upper(), font=label_font, fill=LIME)

    y = 268
    for line in wrap(headline, headline_font, SIZE[0] - 160):
        draw.text((80, y), line, font=headline_font, fill=WHITE)
        y += 82

    draw.line((80, SIZE[1] - 112, 152, SIZE[1] - 112), fill=LIME, width=4)
    draw.text(
        (80, SIZE[1] - 92),
        "Brand-aware AI marketing  ·  Human approval before every post",
        font=label_font,
        fill=MUTED,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / filename
    card.save(path, "PNG", optimize=True)
    return path


def main() -> None:
    for filename, headline, label in CARDS:
        path = build_card(filename, headline, label)
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
