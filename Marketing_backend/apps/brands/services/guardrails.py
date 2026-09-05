"""
Hard brand guardrails — the declared floor under the learned ceiling.

The learning loop discovers rules AFTER a mistake ships once. This module is
the other half: law a human wrote down up front, enforced at three points —

* ``preflight_violations``  — refuses a brief BEFORE any provider is paid.
  Only rules a human explicitly wrote can block; everything here is that.
* ``copy_violations``       — checks what the model actually wrote.
* ``enforce``               — deterministic, silent fixes: strip banned
  hashtags, append required lines, guarantee a CTA keyword.

Empty guardrails are a byte-for-byte no-op on every path: a brand that never
wrote a rule generates exactly as it did before this module existed.
"""
import re

MAX_ITEMS = 50
MAX_TERM_LENGTH = 120

LIST_KEYS = (
    'forbidden_words',
    'banned_hashtags',
    'forbidden_imagery',
    'required_on_every_post',
    'approved_ctas',
)
LANGUAGE_RULES = ('', 'english_only', 'hinglish_allowed')

#: Brief fields a human typed, in the order a reader would recognise them.
#: Guardrails scan ONLY authored text: scanning machine-built fields (brand
#: context, creative direction) would let a rule block the system's own output.
_BRIEF_FIELDS = (
    ('campaign_name', 'campaign name'),
    ('product', 'product'),
    ('target_audience', 'audience'),
    ('location', 'location'),
    ('occasion', 'occasion'),
    ('offer', 'offer'),
    ('brand_tone', 'brand tone'),
    ('instruction', 'instruction'),
    ('video_script', 'video script'),
)


def clean(raw):
    """The canonical guardrail dict, whatever was stored or submitted.

    ``guardrails`` is client-writable JSON, so nothing about its shape can be
    trusted; junk degrades to the empty rule set instead of failing a
    generation or a save.
    """
    source = raw if isinstance(raw, dict) else {}
    cleaned = {}
    for key in LIST_KEYS:
        values = source.get(key)
        items = {}
        if isinstance(values, list):
            for value in values:
                raw_term = str(value) if isinstance(value, (str, int)) else ''
                # Collapse ALL internal whitespace and drop unprintables: a
                # term is rendered into every prompt under the BRAND LAW
                # header, so an embedded newline would let a stored term
                # fabricate its own prompt lines with top authority.
                chunks = (
                    ''.join(ch for ch in chunk if ch.isprintable())
                    for chunk in raw_term.split()
                )
                term = ' '.join(chunk for chunk in chunks if chunk)
                if key == 'banned_hashtags':
                    term = term.lstrip('#')
                # Case-insensitive dedupe, first casing wins: "Cheap" and
                # "cheap" are one ban, and matching is case-insensitive anyway.
                if term and len(term) <= MAX_TERM_LENGTH:
                    items.setdefault(term.casefold(), term)
        cleaned[key] = list(items.values())[:MAX_ITEMS]
    language = source.get('language_rule')
    cleaned['language_rule'] = language if language in LANGUAGE_RULES else ''
    return cleaned


def is_empty(guardrails):
    g = clean(guardrails)
    return not any(g[key] for key in LIST_KEYS) and not g['language_rule']


def _for_brand(brand):
    if brand is None:
        return clean({})
    return clean(getattr(brand, 'guardrails', None))


def _pattern(term):
    """Whole-term match: banning "manual" must not block "user manuals"...
    it does match "manual" as a word but never inside another word."""
    return re.compile(r'(?<!\w)' + re.escape(term) + r'(?!\w)', re.IGNORECASE)


def _normal_term(text):
    return ' '.join(str(text or '').split()).casefold()


def approved_ctas(brand):
    """The DM keywords this brand's law allows as its call to action, [] when
    it wrote none."""
    return _for_brand(brand)['approved_ctas']


def is_approved_cta(brand, cta):
    """Whether `cta` IS one of the brand's approved DM keywords - compared
    case-insensitively with whitespace collapsed, never as a substring.
    False for a brand with no approved list: there is nothing to approve by.
    A CTA typed into the studio's brief is held to this before it becomes
    the poster's on-image call to action (see `brief_fields`)."""
    wanted = _normal_term(cta)
    return bool(wanted) and any(
        _normal_term(term) == wanted for term in approved_ctas(brand)
    )


def preflight_fields(brief):
    """The human-authored text of a brief, labelled for readable refusals."""
    fields = {}
    for key, label in _BRIEF_FIELDS:
        value = brief.get(key)
        if isinstance(value, str) and value.strip():
            fields[label] = value
    slides = brief.get('slides')
    if isinstance(slides, list):
        joined = ' '.join(
            str(slide.get('description', ''))
            for slide in slides
            if isinstance(slide, dict)
        ).strip()
        if joined:
            fields['slides'] = joined
    return fields


def preflight_violations(brand, fields):
    """Plain-English reasons this brief must not be paid for, or []."""
    g = _for_brand(brand)
    banned = [('word', t) for t in g['forbidden_words']]
    banned += [('imagery', t) for t in g['forbidden_imagery']]
    messages = []
    for kind, term in banned:
        for label, text in fields.items():
            if _pattern(term).search(text):
                noun = 'visual motif' if kind == 'imagery' else 'word'
                messages.append(
                    f'The {noun} "{term}" is banned for this brand '
                    f'(found in the {label}).'
                )
                break
    return messages


#: One tag = "#" up to the next whitespace or "#". Detection and enforcement
#: MUST tokenize identically, or a flagged tag survives the strip (burning
#: the paid retry) — and "#summer-sale" must never trip a ban on "sale".
_HASHTAG = re.compile(r'#([^\s#]+)')
_TAG_TRAILING = '.,;:!?)("\'`'


def _normal_tag(raw):
    return str(raw).rstrip(_TAG_TRAILING).casefold()


def _hashtag_tokens(hashtags):
    return [
        match.group(1).rstrip(_TAG_TRAILING)
        for match in _HASHTAG.finditer(str(hashtags or ''))
    ]


def copy_violations(brand, payload):
    """What the generated copy got wrong against the written law."""
    g = _for_brand(brand)
    payload = payload if isinstance(payload, dict) else {}
    title = str(payload.get('postTitle') or '')
    description = str(payload.get('postDescription') or '')
    hashtags = str(payload.get('postHashtags') or '')
    prose = ' '.join((title, description))

    messages = []
    for term in g['forbidden_words']:
        if _pattern(term).search(prose) or _pattern(term).search(hashtags):
            messages.append(f'The caption used the banned word "{term}".')

    banned_tags = {t.casefold() for t in g['banned_hashtags']}
    if banned_tags:
        for token in _hashtag_tokens(hashtags):
            if token.casefold() in banned_tags:
                messages.append(f'The banned hashtag "#{token}" was used.')

    if g['approved_ctas'] and not any(
        _pattern(cta).search(prose) for cta in g['approved_ctas']
    ):
        listed = ', '.join(g['approved_ctas'])
        messages.append(
            f'The caption is missing a DM keyword — it must use one of: {listed}.'
        )
    return messages


def enforce(brand, payload, *, cta=''):
    """Deterministic, silent fixes. Returns (payload, notes).

    Only what can be fixed without judgement is fixed here: banned hashtags
    are removed, required lines are appended verbatim, and a missing CTA
    keyword gets a plain "DM <keyword>" line - unless `cta`, the poster's
    own call to action (typed into the brief, painted on the image), is
    itself an approved keyword: one CTA per poster, so the caption gets no
    second line. Banned words in prose are NOT rewritten — deleting words
    changes meaning, so those stay violations for the retry (and the trace)
    instead.
    """
    g = _for_brand(brand)
    payload = dict(payload) if isinstance(payload, dict) else {}
    notes = []

    banned_tags = {t.casefold() for t in g['banned_hashtags']}
    hashtags = str(payload.get('postHashtags') or '')
    if banned_tags and hashtags:
        removed = 0

        def drop(match):
            nonlocal removed
            if _normal_tag(match.group(1)) in banned_tags:
                removed += 1
                return ''
            return match.group(0)

        stripped = ' '.join(_HASHTAG.sub(drop, hashtags).split())
        if removed:
            payload['postHashtags'] = stripped
            notes.append(f'Removed {removed} banned hashtag(s).')

    description = str(payload.get('postDescription') or '')
    for required in g['required_on_every_post']:
        if not _pattern(required).search(description):
            description = (description + '\n' + required).strip()
            notes.append(f'Appended the required line "{required}".')

    if g['approved_ctas'] and not is_approved_cta(brand, cta):
        prose = ' '.join((str(payload.get('postTitle') or ''), description))
        if not any(_pattern(term).search(prose) for term in g['approved_ctas']):
            description = (description + f"\nDM {g['approved_ctas'][0]}").strip()
            notes.append(f'Appended the CTA keyword "{g["approved_ctas"][0]}".')

    if notes:
        payload['postDescription'] = description
    return payload, notes


def prompt_lines(brand):
    """The written law rendered as prompt constraints, [] when none exists."""
    g = _for_brand(brand)
    lines = []
    if g['forbidden_words']:
        lines.append(
            'NEVER use these words anywhere in the copy: '
            + ', '.join(g['forbidden_words']) + '.'
        )
    if g['forbidden_imagery']:
        lines.append(
            'NEVER include these visual motifs in the imagePrompt: '
            + ', '.join(g['forbidden_imagery']) + '.'
        )
    if g['banned_hashtags']:
        lines.append(
            'NEVER use these hashtags: '
            + ', '.join('#' + t for t in g['banned_hashtags']) + '.'
        )
    for required in g['required_on_every_post']:
        lines.append(f'The caption MUST contain, verbatim: "{required}".')
    if g['approved_ctas']:
        lines.append(
            'The call to action MUST use exactly one of these DM keywords: '
            + ', '.join(g['approved_ctas']) + '.'
        )
    if g['language_rule'] == 'english_only':
        lines.append('Write in English only.')
    elif g['language_rule'] == 'hinglish_allowed':
        lines.append('Hinglish is welcome where it fits the brand voice.')
    return lines
