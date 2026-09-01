"""
Style variants — how six skeletons become more than a thousand templates.

The founder asked for "more than 1000 templates". Hand-authoring a thousand
`LayoutPattern` files is neither feasible nor useful: what makes templates feel
different is colour scheme, photo grading, background, casing and type pairing
far more than box geometry. So a template here is a (pattern, variant) pair —
the pattern supplies the skeleton, and the variant restyles the `Spec` before
the pattern draws, so every existing and future pattern gets the whole variant
space for free without changing a line of pattern code.

Every axis operates only on what `Spec` already carries, and every derived
colour is a valid hex the patterns' own validation accepts. The pick is
deterministic per content item: the same poster recomposes identically, two
different posters almost never dress alike.
"""
import uuid

from PIL import Image, ImageEnhance, ImageOps

#: Axis definitions. Order matters: it is the mixed-radix digit order the
#: deterministic pick uses, so appending options extends the space without
#: reshuffling every existing item's variant.
PALETTES = ('classic', 'inverted', 'accent_ink', 'mono')
PHOTOS = ('asis', 'bw', 'warm', 'cool', 'muted', 'crisp')
PAPERS = ('pure', 'warm_tint', 'cool_tint')
CASINGS = ('asis', 'upper')
PAIRINGS = ('asis', 'flipped')


def _mix(base_hex, tint_hex, amount):
    """`base` nudged toward `tint`. Always returns #rrggbb."""
    try:
        b = [int(base_hex.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
        t = [int(tint_hex.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
    except (ValueError, AttributeError, IndexError):
        return base_hex
    return '#' + ''.join(
        f'{int(round(bc + (tc - bc) * amount)):02x}' for bc, tc in zip(b, t)
    )


def variant_for(item, *, uses_photo=True):
    """
    The style variant a content item wears, decided once from its id.

    Mixed-radix decode of the UUID keeps the axes independent — consecutive
    ids differ in the fastest digit first, so a burst of generations varies
    visibly instead of stepping through one axis at a time.
    """
    try:
        seed = uuid.UUID(str(item.pk)).int
    except (ValueError, AttributeError, TypeError):
        seed = 0
    picks = {}
    for name, options in (
        ('palette', PALETTES),
        ('photo', PHOTOS if uses_photo else ('asis',)),
        ('paper', PAPERS),
        ('casing', CASINGS),
        ('pairing', PAIRINGS),
    ):
        seed, index = divmod(seed, len(options))
        picks[name] = options[index]
    return picks


def coerce(candidate):
    """A stored variant dict with every unknown value degraded to its default.

    `layout_config` is client-writable JSON, so a stored variant cannot be
    trusted; a poisoned value falls back rather than failing a compose."""
    stored = candidate if isinstance(candidate, dict) else {}
    cleaned = {}
    for name, options in (
        ('palette', PALETTES), ('photo', PHOTOS), ('paper', PAPERS),
        ('casing', CASINGS), ('pairing', PAIRINGS),
    ):
        value = stored.get(name)
        cleaned[name] = value if value in options else options[0]
    return cleaned


def apply(spec, variant):
    """Restyles a Spec in place according to a variant, and returns it."""
    palette = dict(spec.palette or {})
    primary = palette.get('primary', '#221F3C')
    light = palette.get('light', '#FDFFE9')
    accent = palette.get('accent', '#D2FFAA')

    scheme = variant.get('palette', 'classic')
    if scheme == 'inverted':
        # Dark poster: the brand's ink becomes the paper.
        palette.update(primary=light, light=primary, accent=accent)
    elif scheme == 'accent_ink':
        palette.update(primary=accent, accent=primary)
    elif scheme == 'mono':
        palette.update(accent=primary)

    paper = variant.get('paper', 'pure')
    if paper == 'warm_tint':
        palette['light'] = _mix(palette.get('light', light), '#B4682F', 0.08)
    elif paper == 'cool_tint':
        palette['light'] = _mix(palette.get('light', light), '#2F58B4', 0.08)
    spec.palette = palette

    photo = variant.get('photo', 'asis')
    if spec.photo is not None and photo != 'asis':
        image = spec.photo.convert('RGB')
        if photo == 'bw':
            image = ImageOps.grayscale(image).convert('RGB')
        elif photo == 'warm':
            image = Image.blend(image, Image.new('RGB', image.size, '#C86428'), 0.12)
        elif photo == 'cool':
            image = Image.blend(image, Image.new('RGB', image.size, '#2864C8'), 0.12)
        elif photo == 'muted':
            image = ImageEnhance.Color(image).enhance(0.45)
        elif photo == 'crisp':
            image = ImageEnhance.Contrast(image).enhance(1.22)
        spec.photo = image

    if variant.get('casing') == 'upper' and spec.headline:
        spec.headline = spec.headline.upper()

    if variant.get('pairing') == 'flipped':
        fonts = dict(spec.fonts or {})
        fonts['primary'], fonts['secondary'] = (
            fonts.get('secondary', ''), fonts.get('primary', ''),
        )
        spec.fonts = {k: v for k, v in fonts.items() if v} or spec.fonts

    return spec


def catalogue_size():
    """How many distinct (pattern, variant) templates exist right now."""
    from . import registry

    per_photo = len(PALETTES) * len(PHOTOS) * len(PAPERS) * len(CASINGS) * len(PAIRINGS)
    per_flat = len(PALETTES) * 1 * len(PAPERS) * len(CASINGS) * len(PAIRINGS)
    return sum(
        per_photo if registry.get(key).uses_photo else per_flat
        for key in registry.keys()
    )
