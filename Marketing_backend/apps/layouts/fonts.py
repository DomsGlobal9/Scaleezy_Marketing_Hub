"""
Turning a brand's font *name* into something PIL can draw with.

`Brand.fonts` holds human names ("DM Sans", "Noto Serif") because that is what
a designer types. PIL needs a file. This module bridges the two, and — more
importantly — always returns a usable font rather than raising, so a poster
never fails to render because a server is missing a typeface.

Resolution order for a family:

1. A bundled or configured .ttf whose name matches (LAYOUT_FONT_DIRS).
2. The family name handed straight to PIL, which searches the OS font dirs.
3. A generic stack of faces almost every OS has.
4. Pillow's built-in scalable default.
"""
import logging
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from PIL import ImageFont

logger = logging.getLogger(__name__)

#: Faces to try when the brand's own family cannot be found. Ordered by how
#: widely available they are rather than how nice they look.
FALLBACK_FACES = (
    'DejaVuSans.ttf',
    'LiberationSans-Regular.ttf',
    'Arial.ttf',
    'arial.ttf',
    'Helvetica.ttc',
    'segoeui.ttf',
)

FALLBACK_BOLD = (
    'DejaVuSans-Bold.ttf',
    'LiberationSans-Bold.ttf',
    'Arialbd.ttf',
    'arialbd.ttf',
    'segoeuib.ttf',
)


def font_dirs():
    """Directories searched for bundled brand fonts."""
    configured = getattr(settings, 'LAYOUT_FONT_DIRS', None) or []
    bundled = Path(__file__).resolve().parent / 'assets' / 'fonts'
    return [Path(d) for d in configured] + [bundled]


def _candidate_files(family: str, bold: bool):
    """
    Filenames a family plausibly lives under.

    "DM Sans" is shipped as DMSans-Regular.ttf, DMSans.ttf, dm-sans.ttf, ...
    Rather than maintain a mapping per typeface, generate the usual shapes.
    """
    compact = family.replace(' ', '')
    hyphen = family.replace(' ', '-')
    weight = 'Bold' if bold else 'Regular'
    stems = [
        f"{compact}-{weight}",
        f"{hyphen}-{weight}",
        compact if not bold else f"{compact}Bold",
        hyphen,
        family,
    ]
    out = []
    for stem in stems:
        for ext in ('.ttf', '.otf'):
            out.append(f"{stem}{ext}")
    return out


@lru_cache(maxsize=256)
def load(family: str, size: int, bold: bool = False):
    """
    Returns a PIL font for this family at this size. Never raises.

    Cached: a single poster asks for a dozen sizes and an export run repeats
    that for every platform, so uncached lookups would dominate render time.
    """
    size = max(1, int(size))
    family = (family or '').strip()

    if family:
        names = _candidate_files(family, bold)
        for directory in font_dirs():
            for name in names:
                path = directory / name
                if path.exists():
                    try:
                        return ImageFont.truetype(str(path), size)
                    except Exception:
                        logger.debug("Unreadable font file %s", path)

        # PIL searches the platform font directories itself.
        for name in names + [family]:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue

    for name in (FALLBACK_BOLD if bold else FALLBACK_FACES):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue

    # Pillow >= 10.1 returns a scalable TrueType here, not the old bitmap.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()
