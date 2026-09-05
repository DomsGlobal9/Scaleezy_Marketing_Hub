"""
Labelled fields typed into a free-text brief, read back deterministically.

The Create Studio's brief is one text box. Live, a user typed "Instagram
poster for the new Kanjivaram silk saree collection. Headline: Woven For
Celebrations. Offer: 20% off launch week. CTA: Shop the collection." and
never touched the offer chip - so `brief['offer']` stayed empty and the
poster carried no offer at all (the on-image offer line reads only the
structured key), and the typed headline was rewritten by the copy judge.
This module reads such labels back out of the text - no model in the loop -
so a typed field counts exactly like a chip.

THE MATCHING RULE. A label counts only where a person would open a labelled
field: at the start of the text, after a newline, or right after sentence
punctuation (`.`, `!`, `?`, `;`, `,`) or an opening bracket, with any
whitespace in between. It must be immediately followed by `:`, ` - ` or
` = `. Prose such as "the price: unbeatable" therefore never matches -
"price" follows a word, not punctuation. Labels are case-insensitive and
whole words ("Offers:" is not "Offer:"). A value runs until the next
recognised label, a newline or the end of the text; it is stripped of
surrounding quotes and one trailing `.`, whitespace-collapsed and cut to
MAX_VALUE_CHARS. The first occurrence of a key wins; a label with an empty
value is not a field and stays in the text.
"""
import re

MAX_VALUE_CHARS = 200

#: Structured brief key -> the labels a person may type for it.
LABELS = {
    'offer': ('offer', 'deal', 'discount', 'promo', 'promotion', 'price'),
    'requested_headline': ('headline', 'title', 'hook', 'tagline'),
    'cta': ('cta', 'call to action', 'call-to-action', 'button', 'button text'),
    'occasion': ('occasion', 'event', 'festival', 'season'),
    'campaign_name': ('campaign', 'campaign name'),
    'product': ('product', 'products', 'item'),
    'target_audience': ('audience', 'target audience', 'target'),
    'location': ('location', 'city', 'where'),
    'brand_tone': ('tone', 'voice', 'mood'),
}

_KEY_OF = {label: key for key, labels in LABELS.items() for label in labels}

# Longest label first, so "campaign name:" is never read as "campaign" + a
# value of "name: ...".
_ALTERNATION = '|'.join(
    re.escape(label) for label in sorted(_KEY_OF, key=len, reverse=True)
)
# Separator and value whitespace never cross a newline: "Offer:" alone on a
# line is an empty field, not a field whose value is the next line.
_FIELD = re.compile(
    r'(?:^|[\n.!?;,(\[{])\s*'                            # where a field may open
    rf'(?P<label>{_ALTERNATION})'                        # the label, whole word
    r'(?:[^\S\n]*:|[^\S\n]+-(?=[^\S\n])|[^\S\n]*=)[^\S\n]*',  # ':' or ' - ' or ' = '
    re.IGNORECASE,
)
_QUOTES_OPEN = '"\'“‘'
_QUOTES_CLOSE = '"\'”’'
_SENTINEL = '\x00'
#: A run of punctuation/whitespace around one or more removed fields.
_REMOVED_RUN = re.compile(r'[.!?;,\x00 \t]*\x00[.!?;,\x00 \t]*')
_EMPTY_BRACKETS = re.compile(r'[(\[{][\s.!?;,]*[)\]}]')


def _clean_value(raw):
    value = ' '.join(str(raw).split())
    for _ in range(2):
        if value.endswith('.'):
            value = value[:-1].rstrip()
        if (
            len(value) >= 2
            and value[0] in _QUOTES_OPEN
            and value[-1] in _QUOTES_CLOSE
        ):
            value = value[1:-1].strip()
    return value[:MAX_VALUE_CHARS].rstrip()


def _before_unmatched_closer(raw):
    """A field opened inside brackets - "(Offer: 20% off) for sarees" - ends
    at the bracket that closes them; a bracket pair inside a value stays."""
    depth = 0
    for index, char in enumerate(raw):
        if char in '([{':
            depth += 1
        elif char in ')]}':
            if depth == 0:
                return raw[:index]
            depth -= 1
    return raw


def _scan(text):
    """Every recognised field in `text`: a list of (key, value, span), where
    span is the [start, end) of the `Label: value` segment in the text."""
    text = str(text or '')
    matches = list(_FIELD.finditer(text))
    found = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw = text[match.end():end]
        newline = raw.find('\n')
        if newline != -1:
            raw = raw[:newline]
        raw = _before_unmatched_closer(raw)
        value = _clean_value(raw)
        if not value:
            continue
        key = _KEY_OF[match.group('label').casefold()]
        found.append((key, value, (match.start('label'), match.end() + len(raw))))
    return found


def extract_brief_fields(text):
    """The labelled fields in `text`, as {structured key: value}. Only keys
    that were found are returned; the first occurrence of a key wins."""
    fields = {}
    for key, value, _span in _scan(text):
        fields.setdefault(key, value)
    return fields


def plain_brief(text):
    """`text` with every recognised `Label: value` segment removed and the
    punctuation and whitespace around it tidied, so the copy model reads the
    brief without the field noise. The original text when nothing was found."""
    text = str(text or '')
    found = _scan(text)
    if not found:
        return text
    pieces = []
    cursor = 0
    for _key, _value, (start, end) in found:
        pieces.append(text[cursor:start])
        pieces.append(_SENTINEL)
        cursor = end
    pieces.append(text[cursor:])
    lines = []
    for line in ''.join(pieces).split('\n'):
        line = _REMOVED_RUN.sub(_tidy_run, line)
        line = _EMPTY_BRACKETS.sub(' ', line)
        line = ' '.join(line.split())
        if line:
            lines.append(line)
    return '\n'.join(lines)


def _tidy_run(match):
    """A field that opened the line leaves nothing behind; one that followed a
    sentence keeps that sentence's own punctuation, once."""
    if match.start() == 0:
        return ''
    for char in match.group(0):
        if char in '.!?;,':
            return char + ' '
    return ' '


def with_brief_fields(brief, instruction=''):
    """A brief with the fields typed into its own `instruction` applied.

    Reads `brief['instruction']` - the studio's typed brief - and ONLY that:
    the `instruction` argument is the caller's word (the worker passes the
    same text, the synchronous endpoint the campaign name, request-edits a
    reviewer's verdict, which must never be mined for labels). A structured
    key is filled only when the brief's own value is empty - the studio's
    chip always wins - and `requested_headline` / `cta` are set the same
    way. When any field was recognised the brief's instruction becomes the
    plain text (see `plain_brief`), as does the `instruction` argument when
    it was that same text, and the creative direction's "User creation
    request" line that quoted it.

    Returns (brief, instruction, filled): `filled` is {key: value} for what
    this call supplied, for the generation trace.
    """
    source = str(brief.get('instruction') or '')
    fields = extract_brief_fields(source)
    if not fields:
        return brief, instruction, {}
    filled = {
        key: value for key, value in fields.items()
        if not ' '.join(str(brief.get(key) or '').split())
    }
    plain = plain_brief(source)
    updated = {**brief, **filled, 'instruction': plain}
    direction = brief.get('creative_direction')
    if plain and isinstance(direction, dict) and isinstance(direction.get('instructions'), list):
        updated['creative_direction'] = {
            **direction,
            'instructions': [
                line.replace(source, plain) if isinstance(line, str) else line
                for line in direction['instructions']
            ],
        }
    if instruction == source:
        instruction = plain
    return updated, instruction, filled
