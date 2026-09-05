/**
 * Labelled fields typed into the free-text creative brief.
 *
 * "Headline: Woven For Celebrations. Offer: 20% off launch week. CTA: Shop
 * the collection." used to reach the poster only as prose — the offer slot
 * stayed empty because no chip was tapped. The backend now lifts labelled
 * text into the structured fields it leaves empty; this is the same rule on
 * the client, so the studio can show what was picked up and let the user
 * correct it before anything is spent.
 *
 * The rule (keep in step with the backend parser):
 *  - a label is case-insensitive and a whole word ("Offers:" is not
 *    "Offer:"); a multi-word label takes exactly one space or hyphen between
 *    its words ("Call to action", "Call-to-action", "Button text");
 *  - it is followed by `:` or `=` (any same-line spacing) or ` - ` (a space
 *    on both sides); neither the separator's spacing nor the value crosses a
 *    newline, so "Offer:" alone on a line is an empty field, not the next
 *    line's field;
 *  - it is recognised at the start of the text, after a newline, after
 *    sentence punctuation (`.` `!` `?` `;` `,`) or an opening bracket, with
 *    any whitespace between — and also after plain whitespace when it is
 *    capitalised and the separator is `:` ("sarees Headline: Woven" counts,
 *    "the price: unbeatable" does not);
 *  - the value runs until the next recognised label, a newline, an unmatched
 *    closing bracket ("(Offer: 20% off) for sarees") or the end of the text,
 *    and never includes the punctuation that introduces the next label;
 *  - a matching pair of surrounding quotes (straight or curly) and one
 *    trailing `.` are stripped, whitespace is collapsed, the value is capped
 *    at 200 characters;
 *  - the first occurrence of a key wins.
 */
export type BriefFieldKey =
  | "offer"
  | "requestedHeadline"
  | "cta"
  | "occasion"
  | "campaignName"
  | "product"
  | "audience"
  | "location"
  | "brandTone";

export type BriefFields = Partial<Record<BriefFieldKey, string>>;

const MAX_VALUE_CHARS = 200;

/** Longest spellings first so "Campaign name" is never read as "Campaign". */
const LABELS: ReadonlyArray<readonly [BriefFieldKey, string]> = [
  ["cta", "call to action|call-to-action"],
  ["audience", "target audience"],
  ["campaignName", "campaign name"],
  ["cta", "button text"],
  ["offer", "offer|deal|discount|promo|promotion|price"],
  ["requestedHeadline", "headline|title|hook|tagline"],
  ["cta", "cta|button"],
  ["occasion", "occasion|event|festival|season"],
  ["campaignName", "campaign"],
  ["product", "products|product|item"],
  ["audience", "audience|target"],
  ["location", "location|city|where"],
  ["brandTone", "tone|voice|mood"],
];

// Group 1: same-line whitespace when the label follows plain prose (the
// capitalised-label case, checked after the match); undefined when it opened
// the text or followed a newline, punctuation or a bracket. Then one capture
// group per vocabulary row — the matched row tells us the key — and lastly
// the separator. `[^\S\n]` is whitespace that is not a newline.
const LABEL_RE = new RegExp(
  "(?:(?:^|[\\n.!?;,(\\[{])\\s*|([^\\S\\n]+))(?:" +
    LABELS.map(([, pattern]) => `(${pattern})`).join("|") +
    ")([^\\S\\n]*:|[^\\S\\n]+-(?=[^\\S\\n])|[^\\S\\n]*=)[^\\S\\n]*",
  "gi",
);
const SEPARATOR_GROUP = LABELS.length + 2;

const QUOTES: ReadonlyArray<readonly [string, string]> = [
  ['"', '"'],
  ["'", "'"],
  ["“", "”"],
  ["‘", "’"],
];

/**
 * A field opened inside brackets — "(Offer: 20% off) for sarees" — ends at
 * the bracket that closes them; a bracket pair inside a value stays.
 */
function beforeUnmatchedCloser(raw: string): string {
  let depth = 0;
  for (let index = 0; index < raw.length; index += 1) {
    const char = raw[index];
    if (char === "(" || char === "[" || char === "{") depth += 1;
    else if (char === ")" || char === "]" || char === "}") {
      if (depth === 0) return raw.slice(0, index);
      depth -= 1;
    }
  }
  return raw;
}

function clean(raw: string): string {
  let value = raw.replace(/\s+/g, " ").trim();
  for (let pass = 0; pass < 2; pass += 1) {
    if (value.endsWith(".")) value = value.slice(0, -1).trim();
    for (const [open, close] of QUOTES) {
      if (value.length >= 2 && value.startsWith(open) && value.endsWith(close)) {
        value = value.slice(1, -1).trim();
      }
    }
  }
  return value.slice(0, MAX_VALUE_CHARS).trim();
}

export function extractBriefFields(text: string): BriefFields {
  const fields: BriefFields = {};
  if (!text) return fields;
  const matches: Array<{ key: BriefFieldKey; start: number; valueStart: number }> = [];
  LABEL_RE.lastIndex = 0;
  for (let m = LABEL_RE.exec(text); m; m = LABEL_RE.exec(text)) {
    const row = m.slice(2, SEPARATOR_GROUP).findIndex((group) => group !== undefined);
    if (row < 0) continue;
    const afterProse = m[1] !== undefined;
    if (afterProse) {
      // "sarees Headline: Woven" is a field; "the price: unbeatable" is prose.
      const initial = text[m.index + m[1]!.length] ?? "";
      const colon = m[SEPARATOR_GROUP]?.endsWith(":") ?? false;
      if (!/[A-Z]/.test(initial) || !colon) {
        LABEL_RE.lastIndex = m.index + 1;
        continue;
      }
    }
    matches.push({ key: LABELS[row]![0], start: m.index, valueStart: m.index + m[0].length });
    if (m[0].length === 0) LABEL_RE.lastIndex += 1;
  }
  matches.forEach((match, index) => {
    if (fields[match.key] !== undefined) return;
    const next = matches[index + 1];
    let end = next ? next.start : text.length;
    const newline = text.indexOf("\n", match.valueStart);
    if (newline !== -1 && newline < end) end = newline;
    const value = clean(beforeUnmatchedCloser(text.slice(match.valueStart, end)));
    if (value) fields[match.key] = value;
  });
  return fields;
}
