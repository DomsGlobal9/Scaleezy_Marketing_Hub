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

THE MATCHING RULE (the studio mirrors this paragraph verbatim). A label
counts in two places: (1) at the start of the text, after a newline, or
right after sentence punctuation (`.`, `!`, `?`, `;`, `,`) or an opening
bracket (`(`, `[`, `{`), with any whitespace between, when it is followed by
`:` (spaces or tabs allowed before it), by ` - ` (at least one space or tab
on BOTH sides of the dash) or by `=` (spaces or tabs optional on either
side); or (2) right after a space or tab, when its first letter is uppercase
in the source and the separator is `:` - so "sarees Headline: Woven" is a
field while "the price: unbeatable" and "sarees Tone = warm" never are.
Labels are case-insensitive whole words ("Offers:" is not "Offer:"); a
multi-word label takes exactly one space or one hyphen between its words
("Call to action", "Call-to-action", "Button text", "Button-text"), never a
run of them. Neither the separator's whitespace nor the value ever crosses a
newline: a label with nothing before the end of its line is not a field and
stays in the text, and a label on the next line is read normally. A value
runs to the next recognised label, the end of its line or the end of the
text, and is cut at a closing bracket (`)`, `]`, `}`) that has no opener
inside the value; it is whitespace-collapsed, then - twice over, in either
order - stripped of one trailing `.` and of one MATCHING pair of surrounding
quotes (`"…"`, `'…'`, `“…”`, `‘…’`; a mixed or unclosed quote is left
alone), and finally cut to MAX_VALUE_CHARS. The first occurrence of a key
wins.
"""
import re

MAX_VALUE_CHARS = 200
#: Set on a brief this module has read, so a later pass over the same brief
#: (the copy-only rewrite hands it back) never re-reads the tidied text and
#: invents a second field from a segment a chip had already decided.
PARSED_MARKER = 'brief_fields_parsed'

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

#: Spaced spelling of a label -> key: "call-to-action" reads as "call to action".
_KEY_OF = {
    label.replace('-', ' '): key for key, labels in LABELS.items() for label in labels
}


def _label_pattern(label):
    """One space OR one hyphen between the words of a multi-word label."""
    return re.escape(label).replace('\\ ', '[ -]').replace('\\-', '[ -]')


# Longest label first, so "campaign name:" is never read as "campaign" + a
# value of "name: ...".
_ALTERNATION = '|'.join(
    _label_pattern(label) for label in sorted(_KEY_OF, key=len, reverse=True)
)
# Separator and value whitespace never cross a newline: "Offer:" alone on a
# line is an empty field, not a field whose value is the next line.
_FIELD = re.compile(
    r'(?:'
    r'(?:^|[\n.!?;,(\[{])\s*'                            # (1) where a field opens
    rf'(?P<label>{_ALTERNATION})'                        # the label, whole word
    r'(?:[^\S\n]*:|[^\S\n]+-[^\S\n]+|[^\S\n]*=)'         # ':' or ' - ' or '='
    r'|'
    r'(?<=[^\S\n])(?=(?-i:[A-Z]))'                       # (2) after a space, Capitalised
    rf'(?P<loose>{_ALTERNATION})[^\S\n]*:'               # and only with ':'
    r')[^\S\n]*',
    re.IGNORECASE,
)
#: Opening quote -> the one closing quote that pairs with it.
_QUOTE_PAIRS = {'"': '"', "'": "'", '“': '”', '‘': '’'}
_SENTINEL = '\x00'
#: A run of punctuation/whitespace around one or more removed fields.
_REMOVED_RUN = re.compile(r'[.!?;,\x00 \t]*\x00[.!?;,\x00 \t]*')
_EMPTY_BRACKETS = re.compile(r'[(\[{][\s.!?;,]*[)\]}]')


def _clean_value(raw):
    value = ' '.join(str(raw).split())
    for _ in range(2):
        if value.endswith('.'):
            value = value[:-1].rstrip()
        if len(value) >= 2 and _QUOTE_PAIRS.get(value[0]) == value[-1]:
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
        group = 'label' if match.group('label') is not None else 'loose'
        key = _KEY_OF[match.group(group).casefold().replace('-', ' ')]
        found.append((key, value, (match.start(group), match.end() + len(raw))))
    return found


def extract_brief_fields(text):
    """The labelled fields in `text`, as {structured key: value}. Only keys
    that were found are returned; the first occurrence of a key wins."""
    fields = {}
    for key, value, _span in _scan(text):
        fields.setdefault(key, value)
    return fields


def plain_brief(text, keys=None):
    """`text` with every recognised `Label: value` segment removed - only
    those of the keys in `keys` when it is given - and the punctuation and
    whitespace around it tidied, so the copy model reads the brief without
    the field noise. The original text when nothing was removed."""
    text = str(text or '')
    found = [
        (key, value, span) for key, value, span in _scan(text)
        if keys is None or key in keys
    ]
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


def _requoted(line, source, plain):
    """The direction line that quoted `source` now quotes `plain`. The line
    is built whitespace-collapsed (see `creative_direction._clean_text`), so
    a brief typed one field per line is quoted there on one line."""
    if not isinstance(line, str):
        return line
    line = line.replace(source, plain)
    return line.replace(' '.join(source.split()), ' '.join(plain.split()))


def with_brief_fields(brief, instruction='', brand=None):
    """A brief with the fields typed into its own `instruction` applied.

    Reads `brief['instruction']` - the studio's typed brief - and ONLY that:
    the `instruction` argument is the caller's word (the worker passes the
    same text, the synchronous endpoint the campaign name, request-edits a
    reviewer's verdict, which must never be mined for labels). A structured
    key is filled only when the brief's own value is empty - the studio's
    chip always wins, and the typed segment then STAYS in the text so the
    copy model still reads what was typed - and `requested_headline` / `cta`
    are set the same way. When `brand` has approved DM keywords
    (`guardrails.approved_ctas`) a typed CTA must be one of them: an unlisted
    one never becomes the on-image CTA - it is dropped and reported as
    `cta_ignored`. The segments this call decided (applied or dropped) leave
    the brief's instruction (see `plain_brief`), the `instruction` argument
    when it was that same text, and the creative direction's "User creation
    request" line that quoted it. The brief is marked (`PARSED_MARKER`); a
    marked brief is handed back untouched, whatever its text now says.

    Returns (brief, instruction, filled): `filled` is {key: value} for what
    this call supplied, plus `cta_ignored` for a typed CTA it refused, for
    the generation trace.
    """
    if brief.get(PARSED_MARKER):
        return brief, instruction, {}
    source = str(brief.get('instruction') or '')
    fields = extract_brief_fields(source)
    if not fields:
        return brief, instruction, {}
    applied = {
        key: value for key, value in fields.items()
        if not ' '.join(str(brief.get(key) or '').split())
    }
    decided = set(applied)
    report = dict(applied)
    if 'cta' in applied:
        from apps.brands.services import guardrails

        if guardrails.approved_ctas(brand) and not guardrails.is_approved_cta(
            brand, applied['cta'],
        ):
            report['cta_ignored'] = applied.pop('cta')
            del report['cta']
    plain = plain_brief(source, decided)
    updated = {**brief, **applied, 'instruction': plain, PARSED_MARKER: True}
    direction = brief.get('creative_direction')
    if plain and isinstance(direction, dict) and isinstance(direction.get('instructions'), list):
        updated['creative_direction'] = {
            **direction,
            'instructions': [
                _requoted(line, source, plain) for line in direction['instructions']
            ],
        }
    if instruction == source:
        instruction = plain
    return updated, instruction, report
