/**
 * Console overview — platform health as the server measures it.
 *
 * Every tile shows `signal.display`, never `value`: a signal that is not live
 * has no number, and painting one would be a lie. The pending-signups count is
 * the approval queue's own `pending_total`.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { AlertTriangle, ArrowRight, CheckCircle2, Inbox, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote, PlatformPageHeader } from "@/components/platform/shared";
import {
  errorText,
  fetchPlatformHealth,
  fetchSignups,
  formatDateTime,
  type HealthSignal,
  type PlatformHealth,
} from "@/lib/platform";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/platform/")({
  head: () => ({ meta: [{ title: "Overview — Scaleezy Platform Console" }] }),
  component: OverviewPage,
});

function SignalTile({ signal }: { signal: HealthSignal }) {
  const attention = signal.live && signal.actionable && (signal.value ?? 0) > 0;
  return (
    <div
      className={cn(
        "surface-card p-4",
        !signal.live && "border-dashed bg-muted/30",
        attention && "border-amber-400/60 bg-amber-50/60",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-foreground">{signal.label}</p>
        {attention ? (
          <AlertTriangle className="size-4 shrink-0 text-amber-600" />
        ) : signal.live ? (
          <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />
        ) : null}
      </div>
      <p
        className={cn(
          "mt-2 font-display text-2xl leading-none font-semibold",
          signal.live ? "text-foreground" : "text-sm font-medium text-muted-foreground italic",
        )}
      >
        {signal.display}
      </p>
      <p className="mt-2 text-[0.6875rem] leading-snug text-muted-foreground">{signal.reason}</p>
    </div>
  );
}

function OverviewPage() {
  const [health, setHealth] = useState<PlatformHealth | null>(null);
  const [pending, setPending] = useState<number | null>(null);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setPendingError(null);
    const [healthResult, queueResult] = await Promise.allSettled([
      fetchPlatformHealth(),
      fetchSignups("PENDING"),
    ]);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    else setError(errorText(healthResult.reason, "Could not load platform health."));
    if (queueResult.status === "fulfilled") setPending(queueResult.value.pending_total);
    else setPendingError(errorText(queueResult.reason, "Could not load the approval queue."));
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const live = health?.signals.filter((s) => s.live) ?? [];
  const unmonitored = health?.signals.filter((s) => !s.live) ?? [];

  return (
    <div>
      <PlatformPageHeader
        eyebrow="Platform"
        title="Overview"
        subtitle="What the platform can measure about itself right now. Signals it cannot measure say so instead of showing a number."
        actions={
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn("size-4", loading && "animate-spin")} /> Refresh
          </Button>
        }
      />

      <ErrorNote message={error} />

      <div className="grid gap-4 md:grid-cols-2">
        <div
          className={cn(
            "surface-card flex items-center gap-4 p-5",
            (health?.needs_attention ?? 0) > 0 && "border-amber-400/60 bg-amber-50/60",
          )}
        >
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-slate-900 text-amber-300">
            <AlertTriangle className="size-5" strokeWidth={1.75} />
          </span>
          <div className="min-w-0">
            <p className="text-xs tracking-wide text-muted-foreground uppercase">Needs attention</p>
            {loading && !health ? (
              <Skeleton className="mt-1 h-7 w-16" />
            ) : (
              <p className="font-display text-2xl font-semibold text-foreground">
                {health ? health.needs_attention : "—"}
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  of {live.length} live signal{live.length === 1 ? "" : "s"}
                </span>
              </p>
            )}
            {health ? (
              <p className="text-[0.6875rem] text-muted-foreground">
                Measured {formatDateTime(health.generated_at)}
              </p>
            ) : null}
          </div>
        </div>

        <Link
          to="/platform/signups"
          className="surface-card group flex items-center gap-4 p-5 transition-transform hover:-translate-y-0.5"
        >
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-slate-900 text-amber-300">
            <Inbox className="size-5" strokeWidth={1.75} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-xs tracking-wide text-muted-foreground uppercase">Awaiting approval</p>
            {loading && pending === null && !pendingError ? (
              <Skeleton className="mt-1 h-7 w-16" />
            ) : pendingError ? (
              <p className="text-sm text-destructive">{pendingError}</p>
            ) : (
              <p className="font-display text-2xl font-semibold text-foreground">
                {pending}
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  client{pending === 1 ? "" : "s"} in the queue
                </span>
              </p>
            )}
          </div>
          <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-semibold tracking-tight text-foreground">Live signals</h2>
        {loading && !health ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-28 rounded-xl" />
            ))}
          </div>
        ) : live.length ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {live.map((signal) => (
              <SignalTile key={signal.key} signal={signal} />
            ))}
          </div>
        ) : health ? (
          <p className="text-sm text-muted-foreground">No live signals were reported.</p>
        ) : null}
      </section>

      {unmonitored.length ? (
        <section className="mt-8">
          <h2 className="mb-1 text-sm font-semibold tracking-tight text-foreground">Not monitored</h2>
          <p className="mb-3 text-xs text-muted-foreground">
            Nothing in the codebase measures these yet. They are listed so nobody mistakes silence
            for health.
          </p>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {unmonitored.map((signal) => (
              <SignalTile key={signal.key} signal={signal} />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
