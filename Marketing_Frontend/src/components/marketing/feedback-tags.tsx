import { useEffect, useState } from "react";

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
 * beside it.
 */
export function FeedbackTagPicker({
  groups,
  selected,
  onToggle,
  disabled,
}: {
  groups: ElementGroup[];
  selected: string[];
  onToggle: (key: string) => void;
  disabled?: boolean;
}) {
  const [openGroup, setOpenGroup] = useState<string | null>(null);

  if (groups.length === 0) return null;

  return (
    <div className="mt-3">
      <p className="text-xs font-medium text-foreground">What needs to change?</p>
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
                "min-h-11 rounded-full border px-3 py-1 text-[0.6875rem] transition-colors lg:min-h-0 lg:px-2.5",
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
                    "min-h-11 rounded-md border px-3 py-1 text-[0.6875rem] transition-colors lg:min-h-0 lg:px-2",
                    active
                      ? "border-primary bg-primary/10 font-medium text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  {element.label}
                </button>
              );
            })}
        </div>
      ) : null}

      {selected.length > 0 ? (
        <p className="mt-2 text-[0.6875rem] text-muted-foreground">
          {selected.length} tagged — raising the same one twice teaches the generator to avoid it.
        </p>
      ) : null}
    </div>
  );
}
