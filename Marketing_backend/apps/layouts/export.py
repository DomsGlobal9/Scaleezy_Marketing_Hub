"""
Export sizes.

Each destination gets its own composition at its own dimensions rather than a
crop of the portrait poster — the layout patterns are resolution-independent,
so this costs one more render and buys artwork that was actually designed for
the shape it ships in.
"""
import io
import logging
from collections import OrderedDict

from PIL import Image

from .render import compose_at

logger = logging.getLogger(__name__)

#: key -> (label, width, height, platform)
SIZES = OrderedDict([
    ('instagram_portrait', ('Instagram portrait', 1080, 1350, 'INSTAGRAM')),
    ('instagram_square', ('Instagram square', 1080, 1080, 'INSTAGRAM')),
    ('instagram_story', ('Instagram story', 1080, 1920, 'INSTAGRAM')),
    ('facebook', ('Facebook feed', 1200, 630, 'FACEBOOK')),
    ('x', ('X card', 1600, 900, 'X')),
    ('linkedin', ('LinkedIn feed', 1200, 627, 'LINKEDIN')),
    ('print_a4', ('Print A4 (PDF)', 2480, 3508, '')),
])

#: Exported as a PDF rather than a JPEG.
PDF_SIZES = {'print_a4'}

DEFAULT_SIZES = ('instagram_portrait',)


def catalogue():
    return [
        {
            'key': key,
            'label': label,
            'width': width,
            'height': height,
            'platform': platform,
            'format': 'PDF' if key in PDF_SIZES else 'JPEG',
        }
        for key, (label, width, height, platform) in SIZES.items()
    ]


def valid(keys):
    """Filters to known sizes, preserving the catalogue's order."""
    wanted = set(keys or [])
    return [k for k in SIZES if k in wanted]


def render_size(spec, layout_key: str, size_key: str):
    """
    Returns (image, format, filename_suffix) for one destination.

    A PDF is still composed as an image first — the layouts are pixel
    compositions, and PIL writes a single-page PDF straight from one.
    """
    label, width, height, _platform = SIZES[size_key]
    image = compose_at(spec, layout_key, width, height)
    fmt = 'PDF' if size_key in PDF_SIZES else 'JPEG'
    return image, fmt, size_key


class UploadBuffer(io.BytesIO):
    """
    BytesIO that carries a content type.

    SupabaseStorageService reads `content_type` off whatever it is handed, and
    a bare BytesIO cannot be given an attribute.
    """

    content_type = 'image/jpeg'


def to_file(image: Image.Image, fmt: str) -> UploadBuffer:
    """A file-like object the storage service can upload."""
    buffer = UploadBuffer()
    if image.mode != 'RGB':
        image = image.convert('RGB')
    if fmt == 'PDF':
        image.save(buffer, format='PDF', resolution=300.0)
    else:
        image.save(buffer, format='JPEG', quality=92, optimize=True)
    buffer.seek(0)
    buffer.content_type = 'application/pdf' if fmt == 'PDF' else 'image/jpeg'
    return buffer
