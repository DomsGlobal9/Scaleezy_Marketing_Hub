/**
 * Small pieces every Brand Master panel shares: honest empty/failed/loading
 * states, a per-slice loader, and the provenance chip.
 */
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export function Empty({
  title,
  hint,
  action,
}: {
  title: string;
  hint: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-dashed p-10 text-center">
      <p className="font-medium text-foreground">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{hint}</p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function Failed({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center">
      <p className="text-sm font-medium text-destructive">{message}</p>
      <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-16 w-full rounded-xl" />
      ))}
    </div>
  );
}

export function InlineError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
      {message}
    </p>
  );
}

/** A tab that fetches its own slice, so one slow layer never blocks the rest. */
export function useSlice<T>(load: () => Promise<T>, enabled: boolean) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    load()
      .then((value) => {
        if (!cancelled) setData(value);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // `load` is recreated per render by design; nonce is the retry trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, nonce]);

  return { data, error, loading, reload: () => setNonce((n) => n + 1) };
}

export function Chip({
  tone,
  children,
}: {
  tone: "hard" | "soft" | "user" | "ai" | "warn";
  children: ReactNode;
}) {
  const styles = {
    hard: "border-foreground/25 bg-foreground/5 text-foreground",
    soft: "border-border bg-muted/60 text-muted-foreground",
    user: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700",
    ai: "border-sky-500/30 bg-sky-500/10 text-sky-700",
    warn: "border-amber-500/30 bg-amber-500/10 text-amber-700",
  } as const;
  return (
    <span
      className={`rounded-full border px-2.5 py-0.5 text-[0.6875rem] font-medium ${styles[tone]}`}
    >
      {children}
    </span>
  );
}

export const errorMessage = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;
