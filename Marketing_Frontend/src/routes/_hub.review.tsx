import { createFileRoute } from "@tanstack/react-router";
import {
  Brain,
  CheckCircle2,
  Edit3,
  FileImage,
  Loader2,
  Maximize2,
  Palette,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { FeedbackTagPicker, useFeedbackElements } from "@/components/marketing/feedback-tags";
import { PosterStudio, useLayoutCatalogue } from "@/components/marketing/poster-studio";
import { EmptyState, PageHeader, StatusBadge } from "@/components/marketing/primitives";
import { api, apiPost } from "@/lib/api";
import { asList } from "@/lib/brand-master";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_hub/review")({
  head: () => ({
    meta: [
      { title: "Review — Scaleezy Marketing Hub" },
      {
        name: "description",
        content: "Approve or reject generated marketing content before it is published.",
      },
    ],
  }),
  component: ReviewPage,
});

interface ContentItem {
  id: string;
  parent: string | null;
  layout_config: Record<string, unknown> | null;
  layout_plugin: string;
  headline: string;
  cta: string;
  caption: string;
  hashtags: string;
  preview_url: string;
  content_format: string;
  status: string;
  version: number;
  review_note: string;
  created_at: string;
}

// Four ways work can relate to you, not six machine states. A reviewer should
// not need to understand the status field to find their work — the precise
// status still shows on every card's badge.
const TABS = [
  { key: "REVIEW", label: "Needs review", statuses: ["PENDING_REVIEW"] },
  { key: "WORKING", label: "In progress", statuses: ["DRAFT", "NEEDS_EDITS"] },
  { key: "DONE", label: "Done", statuses: ["APPROVED", "PUBLISHED"] },
  { key: "REJECTED", label: "Rejected", statuses: ["REJECTED"] },
] as const;

/** A string the studio saved in layout_config.copy, or undefined. */
function savedCopyField(item: ContentItem, field: string): string | undefined {
  const copy = item.layout_config?.["copy"];
  if (typeof copy !== "object" || copy === null || Array.isArray(copy)) return undefined;
  const value = (copy as Record<string, unknown>)[field];
  return typeof value === "string" && value !== "" ? value : undefined;
}

const EMPTY_COPY: Record<string, { title: string; description: string }> = {
  REVIEW: {
    title: "Nothing waiting on you",
    description: "Content submitted for review lands here.",
  },
  WORKING: {
    title: "No work in progress",
    description: "Create or upload content, save it, and it will remain here when you return.",
  },
  DONE: {
    title: "Nothing approved yet",
    description: "Approve content in the review queue and it moves here, ready to publish.",
  },
  REJECTED: {
    title: "Nothing rejected",
    description: "Content you reject is kept here as a record.",
  },
};

interface LearnedRule {
  element: string;
  label: string;
  group: string;
  text: string;
  occurrences: number;
}

interface TrainingReport {
  total_feedback: number;
  by_verdict: Record<string, number>;
  top_elements: { key: string; label: string; group: string; count: number }[];
  brand_name: string;
  brain_current: boolean;
  rules: LearnedRule[];
}

const TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  APPROVED: "success",
  PENDING_REVIEW: "warning",
  NEEDS_EDITS: "warning",
  REJECTED: "danger",
  DRAFT: "neutral",
  PUBLISHED: "success",
};

function ReviewPage() {
  const [tab, setTab] = useState<string>("REVIEW");
  const [all, setAll] = useState<ContentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [fixes, setFixes] = useState<Record<string, string>>({});
  const [tags, setTags] = useState<Record<string, string[]>>({});
  const [report, setReport] = useState<TrainingReport | null>(null);
  const [studio, setStudio] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<ContentItem | null>(null);
  const { groups, provisional } = useFeedbackElements();
  const { layouts, sizes } = useLayoutCatalogue();

  // The issues this brand raises most, offered as one-tap tags on every
  // pending card — the reviewer should recognise, not re-describe.
  const suggestions = useMemo(
    () =>
      (report?.top_elements ?? [])
        .slice(0, 6)
        .map((e) => ({ key: e.key, label: e.label, count: e.count })),
    [report],
  );

  // Element key -> the rule already learned for it, so tagging a known
  // problem needs no typed explanation at all.
  const ruleFor = useMemo(
    () => new Map((report?.rules ?? []).map((rule) => [rule.element, rule.text])),
    [report],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<unknown>("/api/marketing/content/");
      // Tolerates both the bare array and a paginated envelope, so this page
      // cannot silently go empty if the endpoint is ever paginated by default.
      setAll(asList<ContentItem>(data));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not load content.");
    } finally {
      setLoading(false);
    }
  }, []);

  // A returned item spawns a revision carrying the same image, so both used
  // to show — the "same poster in two tabs" confusion. The superseded version
  // is hidden and its reviewer note travels with the revision instead.
  const superseded = useMemo(() => {
    const ids = new Set<string>();
    for (const item of all) if (item.parent) ids.add(item.parent);
    return ids;
  }, [all]);

  const shown = useMemo(
    () => all.filter((i) => !(i.status === "NEEDS_EDITS" && superseded.has(i.id))),
    [all, superseded],
  );

  const counts = useMemo(() => {
    const acc: Record<string, number> = {};
    for (const t of TABS) {
      acc[t.key] = shown.filter((i) =>
        (t.statuses as readonly string[]).includes(i.status),
      ).length;
    }
    return acc;
  }, [shown]);

  const items = useMemo(() => {
    const active = TABS.find((t) => t.key === tab) ?? TABS[0];
    return shown.filter((i) => (active.statuses as readonly string[]).includes(i.status));
  }, [shown, tab]);

  // The note a creator must read: their own, or the one left on the version
  // this revision replaces.
  const noteFor = useCallback(
    (item: ContentItem) =>
      item.review_note ||
      (item.parent ? (all.find((p) => p.id === item.parent)?.review_note ?? "") : ""),
    [all],
  );

  const loadReport = useCallback(async () => {
    try {
      const next = await api<TrainingReport>("/api/marketing/feedback/training-report/");
      setReport(next);
      return next;
    } catch {
      // The report is a read-out, not a dependency of reviewing.
      setReport(null);
      return null;
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadReport();
  }, [loadReport]);

  const toggleTag = (id: string, key: string) =>
    setTags((prev) => {
      const current = prev[id] ?? [];
      return {
        ...prev,
        [id]: current.includes(key) ? current.filter((k) => k !== key) : [...current, key],
      };
    });

  const act = async (id: string, verb: "approve" | "reject" | "request-edits") => {
    const selected = tags[id] ?? [];
    if (verb !== "approve" && selected.length === 0) {
      toast.error("Select at least one issue so Scaleezy can learn the correction.");
      return;
    }
    if (verb !== "approve" && !(notes[id] ?? "").trim() && !(fixes[id] ?? "").trim()) {
      toast.error("Explain the problem or how it should be fixed.");
      return;
    }

    setBusy(id);
    try {
      const reportWasLoaded = report !== null;
      const previousOccurrences = new Map(
        (report?.rules ?? []).map((rule) => [rule.element, rule.occurrences]),
      );
      const result = await apiPost<{ regeneration_queued?: boolean }>(
        `/api/marketing/content/${id}/${verb}/`,
        {
          note: notes[id] ?? "",
          elements: selected,
          fix_request: fixes[id] ?? "",
        },
      );
      const [, nextReport] = await Promise.all([load(), loadReport()]);

      const regenNote =
        verb === "request-edits"
          ? result?.regeneration_queued
            ? " Scaleezy is regenerating it from your feedback."
            : " A new version was opened."
          : "";
      if (verb === "approve") {
        toast.success("Approved — ready to publish.");
      } else {
        const learningVerified =
          reportWasLoaded &&
          nextReport !== null &&
          nextReport.brain_current &&
          selected.length > 0 &&
          selected.every((element) => {
            const next = nextReport.rules.find((rule) => rule.element === element);
            return (next?.occurrences ?? 0) > (previousOccurrences.get(element) ?? 0);
          });
        if (learningVerified) {
          toast.success(
            verb === "reject"
              ? "Rejected — the next generation has learned this correction."
              : `Sent back for edits — the correction is active for the next generation.${regenNote}`,
          );
        } else if (selected.length > 0) {
          toast.warning(
            `Review saved, but immediate learning could not be verified. Check Brand Master → Attention.${regenNote}`,
          );
        } else {
          toast.success(verb === "reject" ? "Rejected." : `Sent back for edits.${regenNote}`);
        }
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Action failed.");
    } finally {
      setBusy(null);
    }
  };

  const updateDraft = (id: string, patch: Partial<Pick<ContentItem, "headline" | "caption" | "hashtags">>) => {
    setAll((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  };

  const saveDraft = async (item: ContentItem, submit = false) => {
    setBusy(item.id);
    try {
      await api<ContentItem>(`/api/marketing/content/${item.id}/`, {
        method: "PATCH",
        body: {
          headline: item.headline,
          caption: item.caption,
          hashtags: item.hashtags,
        },
      });
      if (submit) {
        await apiPost(`/api/marketing/content/${item.id}/submit/`, {});
        toast.success("Submitted for review.");
      } else {
        toast.success("Draft saved.");
      }
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save this draft.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="Review"
        subtitle="Nothing is published until it is approved here."
      />

      {report && (report.rules.length > 0 || report.total_feedback > 0) ? (
        <div className="surface-card mb-6 p-5">
          <div className="flex items-center gap-2">
            <Brain className="size-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold text-foreground">
              What the generator has learned
              {report.brand_name ? ` about ${report.brand_name}` : ""}
            </h2>
          </div>

          {report.rules.length > 0 ? (
            <ul className="mt-3 space-y-1.5">
              {report.rules.slice(0, 5).map((rule) => (
                <li key={rule.element} className="flex gap-2 text-xs text-muted-foreground">
                  <span className="shrink-0 rounded bg-secondary px-1.5 py-0.5 text-[0.625rem] font-medium text-foreground">
                    ×{rule.occurrences}
                  </span>
                  <span>{rule.text}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs text-muted-foreground">
              {report.total_feedback} review{report.total_feedback === 1 ? "" : "s"} recorded. No
              active corrective rule yet. Select an issue and correction when rejecting or
              requesting edits.
            </p>
          )}

          {!report.brain_current ? (
            <p className="mt-3 text-xs font-medium text-destructive">
              The latest learning is saved, but Brand Brain needs attention before generation uses
              it.
            </p>
          ) : null}

          {provisional ? (
            <p className="mt-3 text-[0.6875rem] text-muted-foreground">
              Feedback tags are a provisional vocabulary, pending the final element list.
            </p>
          ) : null}
        </div>
      ) : null}

      {/* One scrolling row on a phone instead of a three-deep wrap. */}
      <div className="mb-6 flex gap-2 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-x-visible sm:pb-0">
        {TABS.map((t) => (
          <Button
            key={t.key}
            size="sm"
            className="shrink-0"
            variant={tab === t.key ? "default" : "outline"}
            onClick={() => setTab(t.key)}
          >
            {t.label}
            {counts[t.key] ? (
              <span
                className={cn(
                  "ml-1.5 rounded-full px-1.5 py-0.5 text-[0.625rem]",
                  tab === t.key ? "bg-white/20" : "bg-secondary",
                )}
              >
                {counts[t.key]}
              </span>
            ) : null}
          </Button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Loading content…
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={FileImage}
          title={EMPTY_COPY[tab]?.title ?? "Nothing here"}
          description={EMPTY_COPY[tab]?.description ?? ""}
          action={
            tab === "WORKING" ? (
              <Button onClick={() => window.location.assign("/publishing")}>Create content</Button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {items.map((item) => (
            <article key={item.id} className="surface-card overflow-hidden">
              {item.preview_url ? (
                <button
                  type="button"
                  onClick={() => setLightbox(item)}
                  aria-label="Preview full image"
                  className="group relative block w-full cursor-zoom-in"
                >
                  {/* object-contain in a 4:5 frame: the whole poster is
                      visible on the card — nothing is cropped away. Lazy and
                      async: storage serves these slowly, and a dozen eager
                      full-size downloads held the whole page in "loading" for
                      tens of seconds. */}
                  <img
                    src={item.preview_url}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    className="aspect-[4/5] max-h-80 w-full border-b border-border bg-secondary/30 object-contain"
                  />
                  <span className="absolute right-2 top-2 rounded-md bg-black/50 p-1.5 text-white opacity-70 transition-opacity sm:opacity-0 sm:group-hover:opacity-100">
                    <Maximize2 className="size-3.5" />
                  </span>
                </button>
              ) : null}
              <div className="p-5">
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
                  <h3 className="min-w-0 truncate text-base font-semibold text-foreground">
                    {item.headline || "Untitled"}
                  </h3>
                  <StatusBadge
                    status={item.status.replace(/_/g, " ")}
                    tone={TONE[item.status] ?? "neutral"}
                  />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.content_format} · v{item.version}
                  {item.parent ? " · revision" : ""} ·{" "}
                  {new Date(item.created_at).toLocaleDateString()}
                </p>

                {item.caption && item.status !== "DRAFT" ? (
                  <p className="mt-3 line-clamp-3 text-sm text-muted-foreground">{item.caption}</p>
                ) : null}

                {item.layout_config?.["regenerating"] === true ? (
                  <p className="mt-3 flex items-center gap-2 rounded-lg border border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
                    <Loader2 className="size-3.5 shrink-0 animate-spin" />
                    Regenerating from your feedback — check back in a moment.
                  </p>
                ) : null}

                {noteFor(item) ? (
                  <p className="mt-3 rounded-lg border border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">Reviewer note:</span>{" "}
                    {noteFor(item)}
                  </p>
                ) : null}

                {item.status === "DRAFT" ? (
                  <div className="mt-4 space-y-3 border-t border-border pt-4">
                    <div className="space-y-1.5">
                      <label htmlFor={`draft-headline-${item.id}`} className="text-xs font-medium">
                        Headline
                      </label>
                      <Input
                        id={`draft-headline-${item.id}`}
                        value={item.headline}
                        disabled={busy === item.id}
                        onChange={(event) => updateDraft(item.id, { headline: event.target.value })}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label htmlFor={`draft-caption-${item.id}`} className="text-xs font-medium">
                        Caption
                      </label>
                      <Textarea
                        id={`draft-caption-${item.id}`}
                        rows={4}
                        value={item.caption}
                        disabled={busy === item.id}
                        onChange={(event) => updateDraft(item.id, { caption: event.target.value })}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label htmlFor={`draft-hashtags-${item.id}`} className="text-xs font-medium">
                        Hashtags
                      </label>
                      <Textarea
                        id={`draft-hashtags-${item.id}`}
                        rows={2}
                        value={item.hashtags}
                        disabled={busy === item.id}
                        onChange={(event) => updateDraft(item.id, { hashtags: event.target.value })}
                      />
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy === item.id}
                        onClick={() => void saveDraft(item)}
                      >
                        {busy === item.id ? <Loader2 className="size-4 animate-spin" /> : null}
                        Save draft
                      </Button>
                      <Button
                        size="sm"
                        disabled={busy === item.id}
                        onClick={() => void saveDraft(item, true)}
                      >
                        Submit for review
                      </Button>
                    </div>
                  </div>
                ) : null}

                {item.status === "APPROVED" ? (
                  <Button
                    className="mt-4 w-full"
                    onClick={() =>
                      window.location.assign(
                        `/publishing?content_item_id=${encodeURIComponent(item.id)}`,
                      )
                    }
                  >
                    Publish approved version
                  </Button>
                ) : null}

                {item.status === "DRAFT" && layouts.length > 0 ? (
                  <>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="mt-3 px-0 text-xs text-muted-foreground hover:text-foreground"
                      onClick={() => setStudio(studio === item.id ? null : item.id)}
                    >
                      <Palette className="size-4" />
                      {studio === item.id ? "Hide studio" : "Compose on-brand"}
                    </Button>
                    {studio === item.id ? (
                      <PosterStudio
                        // Remounts when the item's copy changes underneath it
                        // (draft edits, a finished regeneration), so the
                        // studio never renders a stale headline back over
                        // newer words.
                        key={`${item.id}:${item.headline}:${item.cta}`}
                        contentItemId={item.id}
                        layouts={layouts}
                        sizes={sizes}
                        defaultLayout={item.layout_plugin || undefined}
                        initialHeadline={item.headline || undefined}
                        initialOffer={item.cta || undefined}
                        initialSubheadline={savedCopyField(item, "subheadline")}
                        initialCta={savedCopyField(item, "cta")}
                        onRendered={() => void load()}
                      />
                    ) : null}
                  </>
                ) : null}

                {item.status === "PENDING_REVIEW" ? (
                  <>
                    <Textarea
                      rows={2}
                      className="mt-4"
                      placeholder="Optional note for the creator…"
                      value={notes[item.id] ?? ""}
                      onChange={(e) => setNotes((prev) => ({ ...prev, [item.id]: e.target.value }))}
                    />

                    <FeedbackTagPicker
                      groups={groups}
                      selected={tags[item.id] ?? []}
                      onToggle={(key) => toggleTag(item.id, key)}
                      disabled={busy === item.id}
                      suggestions={suggestions}
                    />

                    {(tags[item.id] ?? []).length > 0 ? (
                      <>
                        {(tags[item.id] ?? [])
                          .filter((key) => ruleFor.has(key))
                          .slice(0, 2)
                          .map((key) => (
                            <p
                              key={key}
                              className="mt-2 rounded-lg border border-border bg-secondary/40 px-3 py-2 text-[0.6875rem] text-muted-foreground"
                            >
                              <span className="font-medium text-foreground">
                                Already learned:
                              </span>{" "}
                              {ruleFor.get(key)} — tagging it again strengthens the rule,
                              no note needed.
                            </p>
                          ))}
                        <Textarea
                          rows={2}
                          className="mt-2"
                          placeholder="How should it be fixed next time? This becomes the rule."
                          value={fixes[item.id] ?? ""}
                          onChange={(e) =>
                            setFixes((prev) => ({ ...prev, [item.id]: e.target.value }))
                          }
                        />
                      </>
                    ) : null}

                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        disabled={busy === item.id}
                        onClick={() => act(item.id, "approve")}
                      >
                        <CheckCircle2 className="size-4" /> Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy === item.id}
                        onClick={() => act(item.id, "request-edits")}
                      >
                        <Edit3 className="size-4" /> Request edits
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive hover:text-destructive"
                        disabled={busy === item.id}
                        onClick={() => act(item.id, "reject")}
                      >
                        <XCircle className="size-4" /> Reject
                      </Button>
                    </div>
                  </>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      )}

      <Dialog open={lightbox !== null} onOpenChange={(open) => !open && setLightbox(null)}>
        {lightbox ? (
          <DialogContent className="max-h-[92vh] w-[calc(100vw-1.5rem)] max-w-3xl gap-3 overflow-y-auto rounded-lg p-4">
            <DialogHeader>
              <DialogTitle className="pr-8 text-base">
                {lightbox.headline || "Untitled"}
              </DialogTitle>
              <DialogDescription>
                {lightbox.content_format} · v{lightbox.version} ·{" "}
                {new Date(lightbox.created_at).toLocaleDateString()}
              </DialogDescription>
            </DialogHeader>
            <img
              src={lightbox.preview_url}
              alt={lightbox.headline || "Content preview"}
              decoding="async"
              className="max-h-[60vh] w-full rounded-lg border border-border bg-secondary/20 object-contain"
            />
            {lightbox.caption ? (
              <p className="text-sm text-muted-foreground">{lightbox.caption}</p>
            ) : null}
            {lightbox.hashtags ? (
              <p className="text-xs text-muted-foreground">{lightbox.hashtags}</p>
            ) : null}
            <a
              href={lightbox.preview_url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-foreground underline underline-offset-2"
            >
              Open full size in a new tab
            </a>
          </DialogContent>
        ) : null}
      </Dialog>
    </div>
  );
}
