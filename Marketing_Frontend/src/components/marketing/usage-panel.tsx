import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Usage {
  subscribed: boolean;
  plan: { key: string; name: string; description: string; price: string } | null;
  status?: string;
  period_end?: string;
  generations_used: number;
  generations_limit: number;
  generations_remaining: number | null;
  spend: string;
  spend_cap: string;
  spend_remaining: string | null;
  allowed: boolean;
  message: string;
}

function Meter({ used, limit }: { used: number; limit: number }) {
  // A limit of 0 means unlimited, not "nothing allowed" — a bar would be a lie.
  if (!limit) return null;
  const pct = Math.min(100, Math.round((used / limit) * 100));
  return (
    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-secondary">
      <div
        className={cn(
          "h-full rounded-full transition-all",
          pct >= 100 ? "bg-destructive" : pct >= 80 ? "bg-amber-500" : "bg-primary",
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

/**
 * What the workspace has used this period.
 *
 * Read-only: changing a plan is a commercial decision, and a self-service
 * upgrade button would be a self-service spend-cap raise.
 */
export function UsagePanel() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void api<Usage>("/api/marketing/billing/")
      .then((data) => {
        if (typeof data.subscribed !== "boolean")
          throw new Error("The server returned invalid usage details.");
        if (!cancelled) setUsage(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load plan usage.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  if (loading)
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading plan usage…
      </p>
    );
  if (error)
    return (
      <div className="space-y-3">
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
        <Button variant="outline" onClick={() => setAttempt((n) => n + 1)}>
          Retry usage
        </Button>
      </div>
    );
  if (!usage) return null;

  if (!usage.subscribed) {
    return (
      <p className="text-sm text-muted-foreground">
        This workspace has no plan attached, so generation is unlimited.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-foreground">{usage.plan?.name}</p>
          <p className="text-xs text-muted-foreground">{usage.plan?.description}</p>
        </div>
        {usage.period_end ? (
          <p className="text-xs text-muted-foreground">
            Resets {new Date(usage.period_end).toLocaleDateString()}
          </p>
        ) : null}
      </div>

      {!usage.allowed && usage.message ? (
        <p className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-foreground">
          {usage.message}
        </p>
      ) : null}

      <div>
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-xs text-muted-foreground">Generations</span>
          <span className="text-xs font-medium text-foreground">
            {usage.generations_used}
            {usage.generations_limit ? ` / ${usage.generations_limit}` : " · unlimited"}
          </span>
        </div>
        <Meter used={usage.generations_used} limit={usage.generations_limit} />
      </div>

      <div>
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-xs text-muted-foreground">AI spend</span>
          <span className="text-xs font-medium text-foreground">
            {usage.spend}
            {Number(usage.spend_cap) ? ` / ${usage.spend_cap}` : " · uncapped"}
          </span>
        </div>
        <Meter used={Number(usage.spend)} limit={Number(usage.spend_cap)} />
      </div>
    </div>
  );
}
