import { Check, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

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

/**
 * What was wrong with this piece of content, in the shared vocabulary.
 *
 * The tags are what the training engine keys on: the same element raised
 * twice becomes a brand rule, so tagging is worth more than the free text
 * beside it. Any number of tags can be selected, across any groups —
 * `suggestions` puts the issues this brand raises most within one tap.
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
  const [openGroup, setOpenGroup] = useState<string | null>(null);

  const labelFor = useMemo(() => {
    const map = new Map<string, string>();
    for (const group of groups) {
      for (const element of group.elements) map.set(element.key, element.label);
    }
    for (const suggestion of suggestions) {
      if (!map.has(suggestion.key)) map.set(suggestion.key, suggestion.label);
    }
    return map;
  }, [groups, suggestions]);

  if (groups.length === 0 && suggestions.length === 0) return null;

  return (
    <div className="mt-3">
      <p className="text-xs font-medium text-foreground">
        What needs to change?{" "}
        <span className="font-normal text-muted-foreground">Tap as many as apply.</span>
      </p>

      {suggestions.length > 0 ? (
        <div className="mt-2">
          <p className="text-[0.6875rem] text-muted-foreground">
            Raised before for this brand — one tap:
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {suggestions.map((suggestion) => {
              const active = selected.includes(suggestion.key);
              return (
                <button
                  key={suggestion.key}
                  type="button"
                  disabled={disabled}
                  onClick={() => onToggle(suggestion.key)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[0.6875rem] transition-colors",
                    active
                      ? "border-primary bg-primary/10 font-medium text-foreground"
                      : "border-border bg-secondary/40 text-muted-foreground hover:text-foreground",
                  )}
                >
                  {active ? <Check className="size-3" /> : null}
                  {suggestion.label}
                  <span className="opacity-60">×{suggestion.count}</span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className="mt-2 flex flex-wrap gap-1.5">
        {groups.map((group) => {
          const chosen = group.elements.filter((e) => selected.includes(e.key)).length;
          const open = openGroup === group.group;
          return (
            <button
              key={group.group}
              type="button"
              disabled={disabled}
              onClick={() => setOpenGroup(open ? null : group.group)}
              className={cn(
                "rounded-full border px-2.5 py-1 text-[0.6875rem] transition-colors",
                open
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-secondary/40 text-muted-foreground hover:text-foreground",
              )}
            >
              {group.label}
              {chosen > 0 ? ` · ${chosen}` : ""}
            </button>
          );
        })}
      </div>

      {openGroup ? (
        <div className="mt-2 flex flex-wrap gap-1.5 rounded-lg border border-border bg-secondary/30 p-2">
          {groups
            .find((g) => g.group === openGroup)
            ?.elements.map((element) => {
              const active = selected.includes(element.key);
              return (
                <button
                  key={element.key}
                  type="button"
                  title={element.description}
                  disabled={disabled}
                  onClick={() => onToggle(element.key)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[0.6875rem] transition-colors",
                    active
                      ? "border-primary bg-primary/10 font-medium text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  {active ? <Check className="size-3" /> : null}
                  {element.label}
                </button>
              );
            })}
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
            {selected.length} tagged — raising the same one twice teaches the generator to
            avoid it.
          </p>
        </div>
      ) : null}
    </div>
  );
}
