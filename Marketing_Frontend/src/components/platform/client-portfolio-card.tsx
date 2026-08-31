import { ArrowRight } from "lucide-react";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { FlagChips, StatusPill } from "@/components/platform/shared";
import { formatAgo, type ClientRow } from "@/lib/platform";
import { cn } from "@/lib/utils";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.625rem] font-semibold tracking-wide text-muted-foreground uppercase">
        {label}
      </dt>
      <dd className="mt-1 text-sm text-foreground">{children}</dd>
    </div>
  );
}

function ClientUsage({ row }: { row: ClientRow }) {
  const usage = row.usage;
  if (!usage) return <span className="text-muted-foreground">—</span>;
  if (!usage.subscribed) return <span className="text-muted-foreground">No plan · unlimited</span>;

  return (
    <div className="space-y-1 text-xs">
      {typeof usage.generations_used === "number" ? (
        <p className={cn(usage.allowed === false && "text-destructive")}>
          Generations {usage.generations_used}
          {usage.generations_limit ? ` / ${usage.generations_limit}` : " · unlimited"}
        </p>
      ) : null}
      {(usage.capabilities ?? []).map((capability) => (
        <p
          key={capability.capability}
          className={cn(
            capability.limit && capability.used >= capability.limit
              ? "text-destructive"
              : "text-muted-foreground",
          )}
        >
          {capability.capability} {capability.used}
          {capability.limit ? ` / ${capability.limit}` : " · unlimited"}
          {capability.overridden ? " · override" : ""}
        </p>
      ))}
      {usage.spend !== undefined ? (
        <p className="text-muted-foreground">
          Spend {usage.spend}
          {Number(usage.spend_cap) ? ` / ${usage.spend_cap}` : ""}
        </p>
      ) : null}
    </div>
  );
}

export function ClientPortfolioCard({ row }: { row: ClientRow }) {
  return (
    <article className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            to="/platform/clients/$workspaceId"
            params={{ workspaceId: row.workspace_id }}
            className="text-base font-semibold text-foreground hover:underline"
          >
            {row.name || "Untitled"}
          </Link>
          <p className="mt-1 font-mono text-[0.6875rem] break-all text-muted-foreground">
            {row.client_code || "No client code"}
          </p>
          {row.brand ? (
            <p className="mt-1 text-xs text-muted-foreground">
              {row.brand.name}
              {row.brand.industry ? ` · ${row.brand.industry}` : ""}
            </p>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground italic">No brand</p>
          )}
        </div>
        <div className="shrink-0 text-right">
          <StatusPill value={row.status} />
          {row.brand && row.brand.status !== "ACTIVE" ? (
            <p className="mt-1 text-[0.625rem] text-muted-foreground">
              brand {row.brand.status.toLowerCase()}
            </p>
          ) : null}
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-4">
        <Field label="Plan">
          {row.plan ? (
            <>
              {row.plan.name}
              {row.subscription_status ? (
                <span className="block text-xs text-muted-foreground">
                  {row.subscription_status}
                </span>
              ) : null}
            </>
          ) : (
            <span className="text-muted-foreground">No plan</span>
          )}
        </Field>
        <Field label="Stage">
          {row.onboarding ? (
            <>
              {row.onboarding.current_stage.replaceAll("_", " ")}
              <span className="block text-xs text-muted-foreground">
                {row.onboarding.status.toLowerCase()}
              </span>
            </>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </Field>
        <Field label="Readiness">
          {row.readiness ? (
            <>
              {row.readiness.score}/100
              <span className="block text-xs text-muted-foreground">
                {row.readiness.level.toLowerCase()}
              </span>
            </>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </Field>
        <Field label="Last active">{formatAgo(row.last_active_at)}</Field>
      </dl>

      <div className="mt-4 border-t border-border pt-4">
        <p className="text-[0.625rem] font-semibold tracking-wide text-muted-foreground uppercase">
          Usage
        </p>
        <div className="mt-1">
          <ClientUsage row={row} />
        </div>
      </div>

      {row.flags.length ? (
        <div className="mt-4 border-t border-border pt-4">
          <p className="mb-2 text-[0.625rem] font-semibold tracking-wide text-muted-foreground uppercase">
            Flags
          </p>
          <FlagChips flags={row.flags} />
        </div>
      ) : null}

      <Button asChild variant="outline" className="mt-4 w-full">
        <Link to="/platform/clients/$workspaceId" params={{ workspaceId: row.workspace_id }}>
          Open client <ArrowRight className="size-4" />
        </Link>
      </Button>
    </article>
  );
}
