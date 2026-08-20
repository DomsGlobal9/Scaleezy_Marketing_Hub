import { createFileRoute } from "@tanstack/react-router";
import { CheckCircle2, Edit3, FileImage, Loader2, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, PageHeader, StatusBadge } from "@/components/marketing/primitives";
import { api, apiPost } from "@/lib/api";
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
  headline: string;
  caption: string;
  hashtags: string;
  preview_url: string;
  content_format: string;
  status: string;
  version: number;
  review_note: string;
  created_at: string;
}

const TABS = [
  { key: "PENDING_REVIEW", label: "Pending" },
  { key: "APPROVED", label: "Approved" },
  { key: "NEEDS_EDITS", label: "Needs edits" },
  { key: "REJECTED", label: "Rejected" },
  { key: "DRAFT", label: "Drafts" },
] as const;

const TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  APPROVED: "success",
  PENDING_REVIEW: "warning",
  NEEDS_EDITS: "warning",
  REJECTED: "danger",
  DRAFT: "neutral",
  PUBLISHED: "success",
};

function ReviewPage() {
  const [tab, setTab] = useState<string>("PENDING_REVIEW");
  const [items, setItems] = useState<ContentItem[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const all = await api<ContentItem[]>("/api/marketing/content/");
      const list = Array.isArray(all) ? all : [];
      setItems(list.filter((i) => i.status === tab));
      setCounts(
        list.reduce<Record<string, number>>((acc, i) => {
          acc[i.status] = (acc[i.status] ?? 0) + 1;
          return acc;
        }, {}),
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not load content.");
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (id: string, verb: "approve" | "reject" | "request-edits") => {
    setBusy(id);
    try {
      await apiPost(`/api/marketing/content/${id}/${verb}/`, { note: notes[id] ?? "" });
      toast.success(
        verb === "approve"
          ? "Approved — ready to publish."
          : verb === "reject"
            ? "Rejected."
            : "Sent back for edits. A new version was opened.",
      );
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Action failed.");
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

      <div className="mb-6 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <Button
            key={t.key}
            size="sm"
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
          title="Nothing here"
          description="Generated content appears here for approval before it can be published."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {items.map((item) => (
            <article key={item.id} className="surface-card overflow-hidden">
              {item.preview_url ? (
                <img
                  src={item.preview_url}
                  alt=""
                  className="h-48 w-full border-b border-border object-cover"
                />
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
                  {item.content_format} · v{item.version} ·{" "}
                  {new Date(item.created_at).toLocaleDateString()}
                </p>

                {item.caption ? (
                  <p className="mt-3 line-clamp-3 text-sm text-muted-foreground">{item.caption}</p>
                ) : null}

                {item.review_note ? (
                  <p className="mt-3 rounded-lg border border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">Reviewer note:</span>{" "}
                    {item.review_note}
                  </p>
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
    </div>
  );
}
