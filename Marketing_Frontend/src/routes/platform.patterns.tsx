import { createFileRoute } from "@tanstack/react-router";
import { Archive, Eye, Loader2, Play, RefreshCw, Send } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  ConfirmDialog,
  ErrorNote,
  PlatformPageHeader,
  StatusPill,
  type ConfirmRequest,
} from "@/components/platform/shared";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  compileLearnedPatterns,
  errorText,
  fetchLearnedPatterns,
  fetchPatternContributors,
  formatDateTime,
  publishLearnedPattern,
  retireLearnedPattern,
  type LearnedPattern,
  type PatternContributor,
} from "@/lib/platform";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/platform/patterns")({
  head: () => ({ meta: [{ title: "Learned patterns — Scaleezy Platform Console" }] }),
  component: PatternsPage,
});

type Filter = "ALL" | "DRAFT" | "PUBLISHED" | "RETIRED";

function Contributors({ pattern, onClose }: { pattern: LearnedPattern | null; onClose: () => void }) {
  const [rows, setRows] = useState<PatternContributor[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!pattern) return;
    let cancelled = false;
    setRows(null);
    setError(null);
    fetchPatternContributors(pattern.id)
      .then((value) => {
        if (!cancelled) setRows(value.contributors);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(errorText(e, "Could not load contributors."));
      });
    return () => {
      cancelled = true;
    };
  }, [pattern]);

  return (
    <Dialog open={!!pattern} onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Contributing clients</DialogTitle>
          <DialogDescription>
            Platform-only lineage for {pattern?.category} / {pattern?.attribute}. This list is never
            sent to a client or AI provider.
          </DialogDescription>
        </DialogHeader>
        <ErrorNote message={error} />
        {!rows ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Loading…
          </div>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No contributor rows remain.</p>
        ) : (
          <div className="max-h-80 overflow-auto rounded-lg border">
            {rows.map((row) => (
              <div key={row.workspace_id} className="flex justify-between border-b px-3 py-2 last:border-0">
                <span className="text-sm font-medium">{row.name}</span>
                <span className="font-mono text-xs text-muted-foreground">{row.client_code}</span>
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function PatternsPage() {
  const [patterns, setPatterns] = useState<LearnedPattern[] | null>(null);
  const [filter, setFilter] = useState<Filter>("ALL");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [contributors, setContributors] = useState<LearnedPattern | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPatterns(await fetchLearnedPatterns());
    } catch (e: unknown) {
      setError(errorText(e, "Could not load learned patterns."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const compile = () =>
    setConfirm({
      title: "Compile learned patterns now?",
      description:
        "The worker rebuilds drafts from every CLIENT workspace. INTERNAL workspaces are excluded. Existing published patterns remain live when their evidence still exists.",
      confirmLabel: "Queue compile",
      run: async () => {
        await compileLearnedPatterns();
        toast.success("Compilation queued. Refresh after the worker finishes.");
      },
    });

  const publish = (pattern: LearnedPattern) =>
    setConfirm({
      title: "Publish this learned pattern?",
      description: `It is backed by ${pattern.contributor_count} client${pattern.contributor_count === 1 ? "" : "s"} and reaches matching generations at rank 82, below every brand-specific rule.`,
      confirmLabel: "Publish",
      run: async () => {
        await publishLearnedPattern(pattern.id);
        toast.success("Pattern published.");
        await load();
      },
    });

  const retire = (pattern: LearnedPattern) =>
    setConfirm({
      title: "Retire this learned pattern?",
      description: "It stops reaching generations immediately. Lineage stays available here.",
      confirmLabel: "Retire",
      destructive: true,
      reason: { label: "Reason", placeholder: "Why this pattern should stop" },
      run: async (reason) => {
        await retireLearnedPattern(pattern.id, reason);
        toast.success("Pattern retired.");
        await load();
      },
    });

  const visible = (patterns ?? []).filter((row) => filter === "ALL" || row.status === filter);
  const counts = Object.fromEntries(
    (["ALL", "DRAFT", "PUBLISHED", "RETIRED"] as Filter[]).map((status) => [
      status,
      status === "ALL" ? patterns?.length ?? 0 : patterns?.filter((p) => p.status === status).length ?? 0,
    ]),
  ) as Record<Filter, number>;

  return (
    <div>
      <PlatformPageHeader
        eyebrow="Platform intelligence"
        title="Learned patterns"
        subtitle="Cross-client observations compiled from every client. Evidence depth is always visible; only published rows reach generation, at rank 82."
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={cn("size-4", loading && "animate-spin")} /> Refresh
            </Button>
            <Button size="sm" onClick={compile}>
              <Play className="size-4" /> Compile
            </Button>
          </>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {(["ALL", "DRAFT", "PUBLISHED", "RETIRED"] as Filter[]).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setFilter(value)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium",
              filter === value ? "border-slate-900 bg-slate-900 text-white" : "bg-background text-muted-foreground",
            )}
          >
            {value === "ALL" ? "All" : value.toLowerCase()} · {counts[value]}
          </button>
        ))}
      </div>

      <ErrorNote message={error} />
      {loading && !patterns ? (
        <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
      ) : visible.length === 0 ? (
        <div className="surface-card p-10 text-center text-sm text-muted-foreground">
          No patterns in this state. Compile to rebuild drafts from current evidence.
        </div>
      ) : (
        <div className="space-y-3">
          {visible.map((pattern) => (
            <article key={pattern.id} className="surface-card grid gap-4 p-4 lg:grid-cols-[120px_minmax(0,1fr)_auto]">
              <div>
                <p className="font-display text-4xl font-semibold text-slate-900">{pattern.contributor_count}</p>
                <p className="text-xs text-muted-foreground">contributing client{pattern.contributor_count === 1 ? "" : "s"}</p>
                <p className="mt-1 text-xs text-muted-foreground">{pattern.supporting_brand_count} brand{pattern.supporting_brand_count === 1 ? "" : "s"}</p>
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill value={pattern.status} />
                  <span className="font-mono text-[0.6875rem] text-muted-foreground">confidence {Math.round(pattern.confidence * 100)}%</span>
                </div>
                <p className="mt-2 font-mono text-xs text-muted-foreground">{pattern.category} / {pattern.attribute}</p>
                <p className="mt-1 font-medium text-foreground">{pattern.value}</p>
                <p className="mt-2 text-[0.6875rem] text-muted-foreground">
                  {pattern.industry ? `Industry string = ${pattern.industry} · ` : "Global cohort · "}
                  compiled {formatDateTime(pattern.compiled_at)} · version {pattern.pattern_version}
                </p>
              </div>
              <div className="flex flex-wrap items-start gap-2 lg:justify-end">
                <Button size="sm" variant="outline" onClick={() => setContributors(pattern)}>
                  <Eye className="size-3.5" /> Contributors
                </Button>
                {pattern.status === "DRAFT" ? (
                  <Button size="sm" onClick={() => publish(pattern)}><Send className="size-3.5" /> Publish</Button>
                ) : null}
                {pattern.status === "PUBLISHED" ? (
                  <Button size="sm" variant="outline" onClick={() => retire(pattern)}><Archive className="size-3.5" /> Retire</Button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      )}

      <Contributors pattern={contributors} onClose={() => setContributors(null)} />
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </div>
  );
}
