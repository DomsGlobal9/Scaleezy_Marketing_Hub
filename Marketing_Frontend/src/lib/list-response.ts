/** A failed or malformed list is unavailable, never an empty collection. */
export function parseList<T>(
  payload: unknown,
  isItem: (value: unknown) => value is T,
  label: string,
): T[] {
  const candidate = Array.isArray(payload)
    ? payload
    : isRecord(payload)
      ? payload["results"]
      : undefined;
  if (!Array.isArray(candidate) || !candidate.every(isItem)) {
    throw new Error(`${label} returned an invalid list. Please try again.`);
  }
  return candidate;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export const hasStringFields = (value: unknown, fields: readonly string[]) =>
  isRecord(value) && fields.every((field) => typeof value[field] === "string");
