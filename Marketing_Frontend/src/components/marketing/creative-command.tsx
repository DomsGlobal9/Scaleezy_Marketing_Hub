import {
  BookOpen,
  Check,
  ExternalLink,
  Image as ImageIcon,
  Loader2,
  Search,
  Sparkles,
} from "lucide-react";
import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  fetchInspirations,
  isBrandAmbassador,
  isBrandTemplate,
  type Inspiration,
  SIGNAL_CATEGORIES,
} from "@/lib/brand-master";
import { fetchLibraryGalleryPage, type LibraryItem } from "@/lib/platform";
import { cn } from "@/lib/utils";

export type CreativeSourceType = "PLATFORM" | "BRAND";
export type CreativeRole = "PRIMARY" | "SUPPORTING";
export type CreativeDirection = "USE" | "AVOID";

export interface CreativeSelection {
  sourceType: CreativeSourceType;
  id: string;
  role: CreativeRole;
  direction: CreativeDirection;
  focusAreas: string[];
}

interface CreativeCard {
  id: string;
  sourceType: CreativeSourceType;
  title: string;
  kind: string;
  annotation: string;
  mediaUrl: string;
  sourceUrl: string;
  tags: string[];
  focusAreas: string[];
}

const libraryCard = (row: LibraryItem): CreativeCard => ({
  id: row.id,
  sourceType: "PLATFORM",
  title: row.title,
  kind: row.kind,
  annotation: row.annotation || row.body || "Curated by Scaleezy",
  mediaUrl: row.file_url || (row.kind === "IMAGE" ? row.reference_url : ""),
  sourceUrl: row.reference_url,
  tags: row.tags ?? [],
  focusAreas: [],
});

const brandCard = (row: Inspiration): CreativeCard => ({
  id: row.id,
  sourceType: "BRAND",
  title: row.title,
  kind: row.inspiration_type,
  annotation: row.annotation || "Saved in this brand's inspiration library",
  mediaUrl: row.file_url || (row.inspiration_type === "IMAGE" ? row.reference_url || "" : ""),
  sourceUrl: row.reference_url || "",
  tags: [],
  focusAreas: row.focus_areas ?? [],
});

const keyFor = (sourceType: CreativeSourceType, id: string) => `${sourceType}:${id}`;

function ReferencePreview({ card }: { card: CreativeCard }) {
  const isVideo = card.kind === "VIDEO" || card.kind === "REEL";
  if (card.mediaUrl && isVideo) {
    return (
      <video
        src={card.mediaUrl}
        className="h-32 w-full bg-black object-cover"
        muted
        playsInline
        preload="metadata"
        aria-label={card.title}
      />
    );
  }
  if (card.mediaUrl) {
    return <img src={card.mediaUrl} alt="" className="h-32 w-full bg-secondary object-cover" />;
  }
  return (
    <div className="grid h-32 place-items-center bg-black text-primary">
      {card.kind === "TEXT" ? (
        <BookOpen className="size-8" aria-hidden="true" />
      ) : (
        <ImageIcon className="size-8" aria-hidden="true" />
      )}
    </div>
  );
}

/** One of the brand's uploaded templates, offered as the look to match. */
function TemplateChoice({
  template,
  active,
  onChoose,
}: {
  template: Inspiration;
  active: boolean;
  onChoose: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onChoose}
      className={cn(
        "min-w-52 flex-1 overflow-hidden rounded-xl border text-left transition-colors",
        active
          ? "border-primary bg-primary/10"
          : "border-border bg-background hover:border-primary/50",
      )}
    >
      <span className="block aspect-[4/5] overflow-hidden bg-secondary">
        {template.file_url ? (
          <img
            src={template.file_url}
            alt={`${template.title} template`}
            className="h-full w-full object-cover"
            loading="lazy"
            decoding="async"
          />
        ) : (
          <span className="grid h-full place-items-center text-muted-foreground">
            <ImageIcon className="size-8" aria-hidden="true" />
          </span>
        )}
      </span>
      <span className="flex items-center gap-2 p-3 text-sm font-semibold text-foreground">
        <span
          className={cn(
            "grid size-5 place-items-center rounded-full border",
            active ? "border-primary bg-primary text-black" : "border-border",
          )}
        >
          {active ? <Check className="size-3" aria-hidden="true" /> : null}
        </span>
        <span className="min-w-0 truncate">{template.title}</span>
      </span>
    </button>
  );
}

export function CreativeCommand({
  brandId,
  selections,
  onSelectionsChange,
  templates = [],
  templateId = "",
  onTemplateChange,
  showTemplates = false,
  showReferences = false,
}: {
  brandId: string | null;
  selections: CreativeSelection[];
  onSelectionsChange: (next: CreativeSelection[]) => void;
  /** The brand's uploaded BRAND_TEMPLATE inspirations, active only. */
  templates?: Inspiration[];
  templateId?: string;
  onTemplateChange?: (next: string) => void;
  showTemplates?: boolean;
  showReferences?: boolean;
}) {
  const [library, setLibrary] = useState<LibraryItem[]>([]);
  const [brandRows, setBrandRows] = useState<Inspiration[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"ALL" | CreativeSourceType>("ALL");
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!showReferences) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([
      fetchLibraryGalleryPage(),
      brandId ? fetchInspirations(brandId) : Promise.resolve([]),
    ])
      .then(([platformPage, ownRows]) => {
        if (cancelled) return;
        setLibrary(platformPage.items);
        setNextOffset(platformPage.nextOffset);
        // Templates have their own "Your templates" direction, and the
        // ambassador photo its own toggle; here either would double as a
        // reference and confuse the flows.
        setBrandRows(
          ownRows.filter(
            (row) =>
              row.retrieval_eligibility?.eligible !== false &&
              !isBrandTemplate(row) &&
              !isBrandAmbassador(row),
          ),
        );
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(
            reason instanceof Error ? reason.message : "Creative references could not load.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [brandId, showReferences]);

  const loadMore = async () => {
    if (nextOffset === null || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await fetchLibraryGalleryPage(nextOffset);
      setLibrary((current) => {
        const known = new Set(current.map((row) => row.id));
        return [...current, ...page.items.filter((row) => !known.has(row.id))];
      });
      setNextOffset(page.nextOffset);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "More references could not load.");
    } finally {
      setLoadingMore(false);
    }
  };

  const cards = useMemo(
    () => [...library.map(libraryCard), ...brandRows.map(brandCard)],
    [library, brandRows],
  );
  // Deferred: the input keeps every keystroke, while the card grid it drives
  // re-filters in a low-priority render — typing stays responsive however
  // large the library grows.
  const deferredQuery = useDeferredValue(query);
  const filtered = useMemo(() => {
    const needle = deferredQuery.trim().toLocaleLowerCase();
    return cards.filter((card) => {
      if (tab !== "ALL" && card.sourceType !== tab) return false;
      if (!needle) return true;
      return [card.title, card.annotation, card.kind, ...card.tags]
        .join(" ")
        .toLocaleLowerCase()
        .includes(needle);
    });
  }, [cards, deferredQuery, tab]);

  const selected = useMemo(
    () => new Map(selections.map((row) => [keyFor(row.sourceType, row.id), row])),
    [selections],
  );

  const toggle = (card: CreativeCard) => {
    const key = keyFor(card.sourceType, card.id);
    if (selected.has(key)) {
      onSelectionsChange(selections.filter((row) => keyFor(row.sourceType, row.id) !== key));
      return;
    }
    onSelectionsChange([
      ...selections,
      {
        sourceType: card.sourceType,
        id: card.id,
        role: selections.length === 0 ? "PRIMARY" : "SUPPORTING",
        direction: "USE",
        focusAreas: card.focusAreas,
      },
    ]);
  };

  const update = (row: CreativeSelection, patch: Partial<CreativeSelection>) => {
    const key = keyFor(row.sourceType, row.id);
    onSelectionsChange(
      selections.map((candidate) =>
        keyFor(candidate.sourceType, candidate.id) === key ? { ...candidate, ...patch } : candidate,
      ),
    );
  };

  return (
    <section className="mt-5 rounded-2xl border border-border bg-secondary/20 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" aria-hidden="true" />
            <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-foreground">
              {showTemplates ? "Choose one of your templates" : "Choose inspiration"}
            </h3>
          </div>
          <p className="mt-1 max-w-2xl text-xs text-muted-foreground">
            {showTemplates
              ? "This generation matches the template you pick — for this content only. Nothing is saved as a Brand Brain rule."
              : "Choose any number of references. Tell Scaleezy what to use, avoid, and focus on."}
          </p>
        </div>
        {showReferences ? (
          <span className="rounded-full bg-black px-3 py-1 text-xs font-semibold text-primary">
            {selections.length} selected
          </span>
        ) : null}
      </div>

      {showTemplates ? (
        <div className="mt-5">
          <div className="mt-2 flex gap-2 overflow-x-auto pb-1">
            {templates.map((template) => (
              <TemplateChoice
                key={template.id}
                template={template}
                active={templateId === template.id}
                onChoose={() => onTemplateChange?.(template.id)}
              />
            ))}
          </div>
        </div>
      ) : null}

      {showReferences ? (
        <>
          <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap gap-1.5" aria-label="Reference source">
              {(
                [
                  ["ALL", "All"],
                  ["PLATFORM", "Scaleezy library"],
                  ["BRAND", "My inspirations"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={tab === value}
                  // Transition: switching re-renders the whole card grid;
                  // sliced, the click paints inside the 200ms INP budget.
                  onClick={() => startTransition(() => setTab(value))}
                  className={cn(
                    "rounded-full border px-3 py-1.5 text-xs font-medium",
                    tab === value
                      ? "border-black bg-black text-primary"
                      : "border-border bg-background text-muted-foreground hover:text-foreground",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="relative sm:w-72">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search inspirations"
                className="pl-9"
              />
            </div>
          </div>

          {loading ? (
            <div className="grid min-h-40 place-items-center text-sm text-muted-foreground">
              <span className="flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Loading references…
              </span>
            </div>
          ) : error ? (
            <div
              role="alert"
              className="mt-4 rounded-xl border border-destructive/30 p-4 text-sm text-destructive"
            >
              {error}
            </div>
          ) : filtered.length === 0 ? (
            <div className="mt-4 rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              No references match this view. Add inspirations in Brand Master or ask the Scaleezy
              team to publish more to the shared library.
            </div>
          ) : (
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {filtered.map((card) => {
                const row = selected.get(keyFor(card.sourceType, card.id));
                const isSelected = Boolean(row);
                return (
                  <article
                    key={keyFor(card.sourceType, card.id)}
                    className={cn(
                      "overflow-hidden rounded-xl border bg-background",
                      isSelected ? "border-primary ring-1 ring-primary" : "border-border",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => toggle(card)}
                      className="block w-full text-left"
                    >
                      <div className="relative">
                        <ReferencePreview card={card} />
                        <span className="absolute left-2 top-2 rounded-full bg-black/85 px-2 py-1 text-[0.625rem] font-semibold uppercase tracking-wide text-primary">
                          {card.sourceType === "PLATFORM" ? "Scaleezy" : "Your brand"}
                        </span>
                        <span
                          className={cn(
                            "absolute right-2 top-2 grid size-7 place-items-center rounded-full border",
                            isSelected
                              ? "border-primary bg-primary text-black"
                              : "border-white/60 bg-black/60 text-white",
                          )}
                        >
                          {isSelected ? <Check className="size-4" aria-hidden="true" /> : null}
                        </span>
                      </div>
                      <div className="p-3">
                        <h4 className="line-clamp-1 text-sm font-semibold text-foreground">
                          {card.title}
                        </h4>
                        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                          {card.annotation}
                        </p>
                      </div>
                    </button>

                    {row ? (
                      <div className="space-y-3 border-t border-border bg-secondary/30 p-3">
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <Label className="text-[0.625rem] uppercase tracking-wide">
                              Importance
                            </Label>
                            <select
                              value={row.role}
                              onChange={(event) =>
                                update(row, { role: event.target.value as CreativeRole })
                              }
                              className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-xs"
                            >
                              <option value="PRIMARY">Primary</option>
                              <option value="SUPPORTING">Supporting</option>
                            </select>
                          </div>
                          <div>
                            <Label className="text-[0.625rem] uppercase tracking-wide">
                              Instruction
                            </Label>
                            <select
                              value={row.direction}
                              onChange={(event) =>
                                update(row, { direction: event.target.value as CreativeDirection })
                              }
                              className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-xs"
                            >
                              <option value="USE">Use this</option>
                              <option value="AVOID">Avoid this</option>
                            </select>
                          </div>
                        </div>
                        <div>
                          <Label className="text-[0.625rem] uppercase tracking-wide">
                            Use specific details{" "}
                            <span className="normal-case text-muted-foreground">
                              (empty = everything)
                            </span>
                          </Label>
                          <div className="mt-1.5 flex max-h-24 flex-wrap gap-1 overflow-y-auto">
                            {SIGNAL_CATEGORIES.map((focus) => {
                              const active = row.focusAreas.includes(focus.value);
                              return (
                                <button
                                  key={focus.value}
                                  type="button"
                                  aria-pressed={active}
                                  onClick={() =>
                                    update(row, {
                                      focusAreas: active
                                        ? row.focusAreas.filter((value) => value !== focus.value)
                                        : [...row.focusAreas, focus.value],
                                    })
                                  }
                                  className={cn(
                                    "rounded-full border px-2 py-1 text-[0.625rem]",
                                    active
                                      ? "border-primary bg-primary/15 text-foreground"
                                      : "border-border bg-background text-muted-foreground",
                                  )}
                                >
                                  {focus.label}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                        {card.sourceUrl ? (
                          <a
                            href={card.sourceUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
                          >
                            View source <ExternalLink className="size-3" aria-hidden="true" />
                          </a>
                        ) : null}
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          )}

          {!loading && !error && nextOffset !== null && tab !== "BRAND" ? (
            <div className="mt-4 flex justify-center">
              <button
                type="button"
                disabled={loadingMore}
                onClick={() => void loadMore()}
                className="rounded-full border border-border bg-background px-4 py-2 text-xs font-semibold text-foreground hover:border-primary disabled:opacity-60"
              >
                {loadingMore ? "Loading more…" : "Load more Scaleezy inspirations"}
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
