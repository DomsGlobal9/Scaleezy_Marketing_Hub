"""
Legibility as an invariant, not a hope.

A poster's palette carries three roles — ink, paper, accent — and the six
patterns draw exactly four text-on-ground pairs out of them:

    ink on paper      the headline and body (agency_column, cos_split, …)
    accent on paper   the tagline eyebrow, the CTA, the offer line
    ink on accent     text inside a filled accent panel (agency_column's
                      offer bar, patterns/base.py's flat photo stand-in)
    accent on ink     the phone bar along the poster's foot (render.py)

Nothing used to check any of them. Measured against the shipping default
palette (`#221F3C` ink, `#FDFFE9` paper, `#D2FFAA` accent) every one of the
four `PALETTES` schemes failed at least one pair, `classic` included: a pale
accent on near-white paper scores 1.11:1, so the tagline, the CTA and the
offer were drawn in a colour a reader cannot see. `mono` sets accent = ink
outright, which makes the offer bar and the phone bar a solid block with
invisible lettering in it.

So this module repairs a palette instead of trusting it. Ratios are WCAG 2.1
relative luminance: 4.5:1 for the ink/paper pair a reader actually reads at
body size, 3:1 for the three accent pairs, which every pattern sets bold,
uppercase or display-sized. Repair preserves the brand's hue — a colour is
walked toward black or toward white, whichever reaches the floor with the
smaller shift, never replaced with a generic swatch — so a brand whose
palette is already legible passes through byte-for-byte unchanged.

The accent carries two constraints at once (it must separate from the paper
AND from the ink), so it is chosen by a bounded, deterministic ladder rather
than a single nudge: the first rung satisfying both wins, and if none does,
the rung with the best worst-pair. That cannot fail to terminate and cannot
return something worse than it was given.
"""

#: WCAG 2.1 contrast floors. Body text is read at size; every accent pair is
#: drawn bold, uppercase or display-sized, which is the large-text threshold.
TEXT_MIN = 4.5
DISPLAY_MIN = 3.0

#: The repair ladder: fractions of the way toward black or toward white.
#: 4% rungs are fine enough that a repaired colour still reads as the brand's
#: (a 0.04 shift is imperceptible) and coarse enough to stay cheap.
_LADDER = tuple(step / 100 for step in range(0, 101, 4))

_BLACK = '#000000'
_WHITE = '#FFFFFF'


def _channels(colour):
    """The three 8-bit channels of `#rrggbb`, or None if it is not one."""
    value = str(colour or '').lstrip('#')
    if len(value) == 3:
        value = ''.join(channel * 2 for channel in value)
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _linear(channel):
    ratio = channel / 255.0
    return ratio / 12.92 if ratio <= 0.04045 else ((ratio + 0.055) / 1.055) ** 2.4


def relative_luminance(colour):
    """WCAG 2.1 relative luminance in [0, 1]; 0.0 for an unparseable colour."""
    channels = _channels(colour)
    if channels is None:
        return 0.0
    red, green, blue = (_linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(one, other):
    """WCAG 2.1 contrast ratio between two colours, from 1.0 to 21.0."""
    first, second = relative_luminance(one), relative_luminance(other)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _mix(base, tint, amount):
    """`base` walked `amount` of the way toward `tint`. Always `#rrggbb`."""
    base_channels, tint_channels = _channels(base), _channels(tint)
    if base_channels is None or tint_channels is None:
        return base
    return '#' + ''.join(
        f'{int(round(b + (t - b) * amount)):02x}'
        for b, t in zip(base_channels, tint_channels)
    )


def _rungs(colour):
    """Every repair candidate for `colour`, nearest shift first.

    Both directions interleaved so the ladder is ordered by how far it moves
    the brand's colour, not by which way it happens to go — a colour that
    needs a 12% lift is not passed over for one that needs a 40% darken.
    """
    seen = {colour}
    yield colour
    for amount in _LADDER[1:]:
        for target in (_BLACK, _WHITE):
            candidate = _mix(colour, target, amount)
            if candidate not in seen:
                seen.add(candidate)
                yield candidate


def ensure_contrast(colour, against, minimum):
    """`colour` shifted just far enough to clear `minimum` against `against`.

    Returned unchanged when it already clears, and when either colour is
    unparseable — a pattern's own hex validation owns that case, and guessing
    at a malformed palette would be a second bug on top of the first.
    """
    if _channels(colour) is None or _channels(against) is None:
        return colour
    for candidate in _rungs(colour):
        if contrast_ratio(candidate, against) >= minimum:
            return candidate
    # Unreachable in practice: black and white bracket every background, so
    # some rung always clears. Kept so the function is total.
    return _BLACK if relative_luminance(against) > 0.5 else _WHITE


def _best_accent(accent, paper, ink, minimum):
    """An accent that separates from the paper AND from the ink.

    Two constraints, one colour, so a single nudge cannot serve both: walked
    down the ladder, the first rung clearing both wins. When none does — a
    paper and an ink close enough in luminance to leave no gap between them —
    the rung with the best worst-pair wins, which is still strictly better
    than the accent that came in.
    """
    best, best_score = accent, -1.0
    for candidate in _rungs(accent):
        worst = min(
            contrast_ratio(candidate, paper), contrast_ratio(candidate, ink)
        )
        if worst >= minimum:
            return candidate
        if worst > best_score:
            best, best_score = candidate, worst
    return best


def legible_palette(palette):
    """`palette` with every drawn text pair guaranteed to clear its floor.

    A new dict; the input is never mutated. Roles this does not know about
    are carried through untouched, and a palette that is already legible
    comes back byte-for-byte identical — so a brand whose colours were chosen
    by a designer is never "corrected" on their behalf.

    Paper is the one fixed point: it is the ground the poster is printed on
    and the photo is graded against, so the repair moves ink and accent
    around it rather than restating the background.
    """
    if not isinstance(palette, dict):
        return palette
    repaired = dict(palette)
    paper = repaired.get('light')
    ink = repaired.get('primary')
    accent = repaired.get('accent')
    if _channels(paper) is None:
        return repaired

    if _channels(ink) is not None:
        ink = ensure_contrast(ink, paper, TEXT_MIN)
        repaired['primary'] = ink

    if _channels(accent) is not None:
        if _channels(ink) is None:
            repaired['accent'] = ensure_contrast(accent, paper, DISPLAY_MIN)
        else:
            repaired['accent'] = _best_accent(accent, paper, ink, DISPLAY_MIN)
    return repaired
