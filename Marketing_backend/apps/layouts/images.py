"""
Getting pixels in safely.

Two sources only: a base64 payload the caller uploaded, and a URL this server
already owns (a brand logo, or an asset in the workspace's own storage). There
is deliberately no "fetch whatever URL the client sends" path — that is a
server-side request forgery hole, and a poster renderer is an unusually
convenient place to hide one.
"""
import base64
import binascii
import io
import logging

from PIL import Image

logger = logging.getLogger(__name__)

#: Refuse anything larger, before decoding. A poster only ever needs a few MB
#: and a decompression bomb needs far less than this to hurt.
MAX_BYTES = 12 * 1024 * 1024

#: Largest source image accepted, in pixels. Pillow's own bomb check is looser
#: than we need.
MAX_PIXELS = 50_000_000

FETCH_TIMEOUT = 15


def _open(data: bytes):
    if not data or len(data) > MAX_BYTES:
        return None
    try:
        image = Image.open(io.BytesIO(data))
        if (image.width * image.height) > MAX_PIXELS:
            logger.warning("Rejected oversized image %sx%s", image.width, image.height)
            return None
        image.load()
        return image
    except Exception:
        logger.debug("Unreadable image payload", exc_info=True)
        return None


def from_base64(value: str):
    """Accepts a bare base64 string or a full `data:image/...;base64,` URL."""
    if not value or not isinstance(value, str):
        return None
    payload = value.split(',', 1)[1] if value.startswith('data:') else value
    try:
        return _open(base64.b64decode(payload, validate=False))
    except (binascii.Error, ValueError):
        return None


def from_trusted_url(url: str):
    """
    Downloads an image from a URL the *server* chose — never one a client
    supplied. Returns None on any failure; a missing logo must not fail a
    render.
    """
    if not url or not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        return None

    import requests

    try:
        response = requests.get(url, timeout=FETCH_TIMEOUT, stream=True)
        if not response.ok:
            logger.info("Image fetch returned %s for %s", response.status_code, url[:120])
            return None
        # Read at most MAX_BYTES + 1 so an enormous body cannot exhaust memory
        # before the size check runs.
        data = response.raw.read(MAX_BYTES + 1, decode_content=True)
        return _open(data)
    except Exception:
        logger.info("Image fetch failed for %s", url[:120], exc_info=True)
        return None


def to_bytes(image: Image.Image, fmt: str = 'JPEG', quality: int = 92) -> bytes:
    buffer = io.BytesIO()
    if fmt.upper() in ('JPEG', 'PDF') and image.mode != 'RGB':
        image = image.convert('RGB')
    image.save(buffer, format=fmt.upper(), quality=quality)
    return buffer.getvalue()


def to_data_url(image: Image.Image, fmt: str = 'JPEG') -> str:
    mime = 'application/pdf' if fmt.upper() == 'PDF' else f"image/{fmt.lower()}"
    return f"data:{mime};base64,{base64.b64encode(to_bytes(image, fmt)).decode()}"
