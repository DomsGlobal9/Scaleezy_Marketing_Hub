import { Check, ChevronDown, ChevronUp, Search, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface FeedbackElement {
  key: string;
  label: string;
  group: string;
  group_label: string;
  description: string;
  is_provisional: boolean;
}

interface ElementGroup {
  group: string;
  label: string;
  elements: FeedbackElement[];
}

interface ElementsResponse {
  groups: ElementGroup[];
  count: number;
  provisional: boolean;
}

/** A recurring issue the trainer has already seen, offered as a one-tap tag. */
export interface SuggestedElement {
  key: string;
  label: string;
  count: number;
}

/**
 * The vocabulary is a global catalogue, so it is fetched once per page load
 * and shared by every review card rather than re-requested per card.
 */
export function useFeedbackElements() {
  const [groups, setGroups] = useState<ElementGroup[]>([]);
  const [provisional, setProvisional] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void api<ElementsResponse>("/api/marketing/feedback/elements/")
      .then((data) => {
        if (cancelled) return;
        setGroups(data.groups ?? []);
        setProvisional(Boolean(data.provisional));
      })
      // Tagging is optional; a reviewer can still approve or reject without it.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return { groups, provisional };
}

//: The issues reviewers reach for most, shown before the brand has any
//: history of its own. Once the training report has real recurrences, those
//: take these slots instead.
const STARTER_KEYS = [
  "headline",
  "tone_of_voice",
  "brand_colours",
  "font_choice",
  "imagery_subject",
  "logo_placement",
  "image_quality",
  "composition_balance",
];

function Chip({
  active,
  disabled,
  onClick,
  title,
  children,
}: {
  active: boolean;
  disabled?: boolean | undefined;
  onClick: () => void;
  title?: string | undefined;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[0.6875rem] transition-colors",
        active
          ? "border-primary bg-primary/10 font-medium text-foreground"
          : "border-border bg-secondary/40 text-muted-foreground hover:text-foreground",
      )}
    >
      {active ? <Check className="size-3" /> : null}
      {children}
    </button>
  );
}

/**
 * What was wrong with this piece of content, in the shared vocabulary.
 *
 * The tags are what the training engine keys on: a selected corrective issue
 * becomes a soft brand rule immediately, and later occurrences strengthen it.
 * One flat row of the likeliest tags, then search for the rest - the reviewer
 * recognises, they never navigate a taxonomy.
 */
export function FeedbackTagPicker({
  groups,
  selected,
  onToggle,
  disabled,
  suggestions = [],
}: {
  groups: ElementGroup[];
  selected: string[];
  onToggle: (key: string) => void;
  disabled?: boolean;
  suggestions?: SuggestedElement[];
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const flat = useMemo(() => groups.flatMap((g) => g.elements), [groups]);

  const labelFor = useMemo(() => {
    const map = new Map<string, string>();
    for (const element of flat) map.set(element.key, element.label);
    for (const s of suggestions) if (!map.has(s.key)) map.set(s.key, s.label);
    return map;
  }, [flat, suggestions]);

  // The quick row: this brand's recurring issues first, topped up with the
  // starter set so a brand new workspace still gets one-tap tags.
  const quick = useMemo(() => {
    const row: { key: string; label: string; count?: number }[] = suggestions.map(
      (s) => ({ key: s.key, label: s.label, count: s.count }),
    );
    const taken = new Set(row.map((r) => r.key));
    for (const key of STARTER_KEYS) {
      if (row.length >= 8) break;
      if (taken.has(key)) continue;
      const element = flat.find((e) => e.key === key);
      if (element) {
        row.push({ key: element.key, label: element.label });
        taken.add(key);
      }
    }
    return row;
  }, [suggestions, flat]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return flat;
    return flat.filter(
      (e) =>
        e.label.toLowerCase().includes(q) ||
        e.description.toLowerCase().includes(q) ||
        e.group_label.toLowerCase().includes(q),
    );
  }, [flat, query]);

  if (flat.length === 0 && suggestions.length === 0) return null;

  return (
    <div className="mt-3">
      <p className="text-xs font-medium text-foreground">
        What needs to change?{" "}
        <span className="font-normal text-muted-foreground">Tap all that apply.</span>
      </p>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {quick.map((entry) => (
          <Chip
            key={entry.key}
            active={selected.includes(entry.key)}
            disabled={disabled}
            onClick={() => onToggle(entry.key)}
          >
            {entry.label}
            {entry.count ? <span className="opacity-60">×{entry.count}</span> : null}
          </Chip>
        ))}
        {flat.length > quick.length ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() => setOpen((v) => !v)}
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2.5 py-1 text-[0.6875rem] text-muted-foreground transition-colors hover:text-foreground"
          >
            {open ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
            {open ? "Fewer options" : `All options (${flat.length})`}
          </button>
        ) : null}
      </div>

      {open ? (
        <div className="mt-2 rounded-lg border border-border bg-secondary/30 p-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={query}
              disabled={disabled}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search: headline, colours, logo…"
              className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div className="mt-2 max-h-48 space-y-2 overflow-y-auto pr-1">
            {groups.map((group) => {
              const visible = group.elements.filter((e) => matches.includes(e));
              if (visible.length === 0) return null;
              return (
                <div key={group.group}>
                  <p className="mb-1 text-[0.625rem] font-medium uppercase tracking-wide text-muted-foreground">
                    {group.label}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {visible.map((element) => (
                      <Chip
                        key={element.key}
                        active={selected.includes(element.key)}
                        disabled={disabled}
                        title={element.description}
                        onClick={() => onToggle(element.key)}
                      >
                        {element.label}
                      </Chip>
                    ))}
                  </div>
                </div>
              );
            })}
            {matches.length === 0 ? (
              <p className="py-2 text-center text-xs text-muted-foreground">
                Nothing matches “{query}”.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      {selected.length > 0 ? (
        <div className="mt-2">
          <div className="flex flex-wrap gap-1.5">
            {selected.map((key) => (
              <span
                key={key}
                className="inline-flex items-center gap-1 rounded-full border border-primary bg-primary/10 py-0.5 pl-2 pr-1 text-[0.6875rem] font-medium text-foreground"
              >
                {labelFor.get(key) ?? key}
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onToggle(key)}
                  aria-label={`Remove ${labelFor.get(key) ?? key}`}
                  className="rounded-full p-0.5 hover:bg-primary/20"
                >
                  <X className="size-3" />
                </button>
              </span>
            ))}
          </div>
          <p className="mt-1.5 text-[0.6875rem] text-muted-foreground">
            {selected.length} tagged — each selected issue teaches the next generation immediately.
          </p>
        </div>
      ) : null}
    </div>
  );
}
