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
 *  - a label is case-insensitive and is followed by `:` (any spacing),
 *    ` - ` or ` = ` (spaces on both sides);
 *  - it is recognised only at the start of the text, after a newline, after
 *    sentence punctuation (`.` `!` `?` `;` `,`) or after an opening bracket;
 *  - the value runs until the next recognised label, a newline or the end of
 *    the text, and never includes the punctuation that introduces the next
 *    label;
 *  - surrounding quotes, one trailing `.` and an unmatched trailing closing
 *    bracket are stripped, whitespace is collapsed, the value is capped at
 *    200 characters;
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
  ["cta", "call[\\s-]+to[\\s-]+action"],
  ["audience", "target\\s+audience"],
  ["campaignName", "campaign\\s+name"],
  ["cta", "button\\s+text"],
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

// One capture group per vocabulary row: the matched row tells us the key.
const LABEL_RE = new RegExp(
  "(?:^|[\\n.!?;,(\\[{])\\s*(?:" +
    LABELS.map(([, pattern]) => `(${pattern})`).join("|") +
    ")(?:\\s*:|\\s+-\\s+|\\s+=\\s+)\\s*",
  "gi",
);

const QUOTES: ReadonlyArray<readonly [string, string]> = [
  ['"', '"'],
  ["'", "'"],
  ["“", "”"],
  ["‘", "’"],
];

const BRACKETS: ReadonlyArray<readonly [string, string]> = [
  ["(", ")"],
  ["[", "]"],
  ["{", "}"],
];

function clean(raw: string): string {
  let value = raw.replace(/\s+/g, " ").trim();
  for (let pass = 0; pass < 3; pass += 1) {
    const before = value;
    if (value.endsWith(".")) value = value.slice(0, -1).trim();
    // "(Event: Diwali)" — the bracket that opened the label closes the value.
    for (const [open, close] of BRACKETS) {
      if (value.endsWith(close) && !value.includes(open)) value = value.slice(0, -1).trim();
    }
    for (const [open, close] of QUOTES) {
      if (value.length >= 2 && value.startsWith(open) && value.endsWith(close)) {
        value = value.slice(1, -1).trim();
      }
    }
    if (value === before) break;
  }
  return value.slice(0, MAX_VALUE_CHARS).trim();
}

export function extractBriefFields(text: string): BriefFields {
  const fields: BriefFields = {};
  if (!text) return fields;
  const matches: Array<{ key: BriefFieldKey; start: number; valueStart: number }> = [];
  LABEL_RE.lastIndex = 0;
  for (let m = LABEL_RE.exec(text); m; m = LABEL_RE.exec(text)) {
    const row = m.slice(1).findIndex((group) => group !== undefined);
    if (row < 0) continue;
    matches.push({ key: LABELS[row]![0], start: m.index, valueStart: m.index + m[0].length });
    if (m[0].length === 0) LABEL_RE.lastIndex += 1;
  }
  matches.forEach((match, index) => {
    if (fields[match.key] !== undefined) return;
    const next = matches[index + 1];
    let end = next ? next.start : text.length;
    const newline = text.indexOf("\n", match.valueStart);
    if (newline !== -1 && newline < end) end = newline;
    const value = clean(text.slice(match.valueStart, end));
    if (value) fields[match.key] = value;
  });
  return fields;
}
