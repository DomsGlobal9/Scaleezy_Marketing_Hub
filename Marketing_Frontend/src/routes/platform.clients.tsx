/**
 * Client portfolio — every workspace on the platform, one row each.
 *
 * Filter chips name the flags the server computes; the chip is sent as
 * `?filter=` and the server narrows, flags and pages — rows arrive already
 * filtered. Every cell is a real query on the server; a missing value renders
 * as a dash, never as zero.
 */
import { createFileRoute, Link, Outlet, useChildMatches } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote, FlagChips, PlatformPageHeader, StatusPill } from "@/components/platform/shared";
import {
  errorText,
  fetchClients,
  formatAgo,
  type ClientList,
  type ClientRow,
} from "@/lib/platform";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/platform/clients")({
  head: () => ({ meta: [{ title: "Clients — Scaleezy Platform Console" }] }),
  component: ClientsRoute,
});

/** The list is the parent of the detail route; a matched child takes over. */
function ClientsRoute() {
  const children = useChildMatches();
  if (children.length > 0) return <Outlet />;
  return <ClientsPage />;
}

/**
 * Keys are the server's `?filter=` vocabulary (apps/platform/views_clients.py
 * FILTERS); it selects on the same flags it returns, so no client-side pass
 * over `flags` is needed here.
 */
const FILTERS: Array<{ key: string; label: string }> = [
  { key: "", label: "All" },
  { key: "pending", label: "Awaiting approval" },
  { key: "at_risk", label: "At risk" },
  { key: "over_quota", label: "Over quota / spend cap" },
  { key: "never_generated", label: "Never generated" },
  { key: "inactive", label: "Inactive" },
  { key: "failing_publishes", label: "Failing publishes" },
  { key: "suspended", label: "Suspended" },
  { key: "archived", label: "Archived" },
];

function UsageCell({ row }: { row: ClientRow }) {
  const usage = row.usage;
  if (!usage) return <span className="text-xs text-muted-foreground">—</span>;
  if (!usage.subscribed) {
    return <span className="text-xs text-muted-foreground">No plan · unlimited</span>;
  }
  const caps = usage.capabilities ?? [];
  return (
    <div className="space-y-0.5 text-[0.6875rem]">
      {typeof usage.generations_used === "number" ? (
        <p className={cn(usage.allowed === false && "text-destructive")}>
          Gen {usage.generations_used}
          {usage.generations_limit ? ` / ${usage.generations_limit}` : " · ∞"}
        </p>
      ) : null}
      {caps.map((cap) => (
        <p
          key={cap.capability}
          className={cn(
            "whitespace-nowrap",
            cap.limit && cap.used >= cap.limit ? "text-destructive" : "text-muted-foreground",
          )}
        >
          {cap.capability} {cap.used}
          {cap.limit ? ` / ${cap.limit}` : " · ∞"}
          {cap.overridden ? " *" : ""}
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

function ClientsPage() {
  const [filter, setFilter] = useState("");
  const [days, setDays] = useState(30);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [page, setPage] = useState(1);
  const [list, setList] = useState<ClientList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadVersion = useRef(0);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setDebouncedQ(q.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(handle);
  }, [q]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const version = ++loadVersion.current;
      setLoading(true);
      setError(null);
      try {
        const params: {
          filter?: string;
          days?: number;
          q?: string;
          page?: number;
          pageSize?: number;
        } = { days, page, pageSize: 25 };
        if (filter) params.filter = filter;
        if (debouncedQ) params.q = debouncedQ;
        const next = await fetchClients(params, signal ? { signal } : undefined);
        if (version === loadVersion.current) setList(next);
      } catch (e: unknown) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        if (version === loadVersion.current) {
          setError(errorText(e, "Could not load the portfolio."));
        }
      } finally {
        if (version === loadVersion.current) setLoading(false);
      }
    },
    [filter, days, debouncedQ, page],
  );

  useEffect(() => {
    const controller = new AbortController();
    setList(null);
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const rows = list?.clients ?? [];
  const total = list?.total ?? list?.count ?? 0;
  const currentPage = list?.page ?? page;
  const totalPages = list?.total_pages ?? (total ? 1 : 0);

  return (
    <div>
      <PlatformPageHeader
        eyebrow="Platform"
        title="Clients"
        subtitle="Every workspace on the platform. Each column is a live query; flags are computed by the server on the same read."
        actions={
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn("size-4", loading && "animate-spin")} /> Refresh
          </Button>
        }
      />

      <div
        className="scrollbar-hide -mx-4 mb-4 flex flex-nowrap items-center gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0"
        role="group"
        aria-label="Filter clients"
      >
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            onClick={() => {
              setFilter(f.key);
              setPage(1);
            }}
            className={cn(
              "shrink-0 rounded-full border px-3.5 py-1.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-2",
              filter === f.key
                ? "border-slate-900 bg-slate-900 text-white"
                : "border-border bg-background text-muted-foreground hover:text-foreground",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] flex-1 sm:max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="Search client code, name or brand"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Inactive after
          <Input
            type="number"
            min={1}
            max={365}
            className="h-8 w-20 text-xs"
            value={days}
            onChange={(e) => {
              const next = Number(e.target.value);
              if (Number.isFinite(next) && next > 0) {
                setDays(Math.min(365, Math.round(next)));
                setPage(1);
              }
            }}
          />
          days
        </label>
        {list ? (
          <span className="ml-auto text-xs text-muted-foreground">
            {rows.length} of {total} client{total === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>

      <ErrorNote message={error} />

      {loading && !list ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-xl" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="surface-card p-10 text-center">
          <p className="font-medium text-foreground">No clients match.</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {list && list.count === 0
              ? "There are no workspaces on the platform yet."
              : "Try another filter or clear the search."}
          </p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-sm">
            <table className="w-full min-w-[1080px] text-left text-sm">
              <caption className="sr-only">
                Platform clients with status, plan, onboarding, readiness, usage, activity and flags
              </caption>
              <thead className="bg-muted/70 text-[0.6875rem] tracking-wide text-muted-foreground uppercase">
                <tr>
                  <th className="px-3 py-2 font-semibold">Code</th>
                  <th className="px-3 py-2 font-semibold">Name</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 font-semibold">Plan</th>
                  <th className="px-3 py-2 font-semibold">Stage</th>
                  <th className="px-3 py-2 font-semibold">Readiness</th>
                  <th className="px-3 py-2 font-semibold">Usage</th>
                  <th className="px-3 py-2 font-semibold">Last active</th>
                  <th className="px-3 py-2 font-semibold">Flags</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.workspace_id}
                    className="border-t border-border align-top transition-colors hover:bg-muted/40"
                  >
                    <td className="px-3 py-3 font-mono text-xs whitespace-nowrap">
                      <Link
                        to="/platform/clients/$workspaceId"
                        params={{ workspaceId: row.workspace_id }}
                        className="text-foreground hover:underline"
                      >
                        {row.client_code || "—"}
                      </Link>
                    </td>
                    <td className="px-3 py-2.5">
                      <Link
                        to="/platform/clients/$workspaceId"
                        params={{ workspaceId: row.workspace_id }}
                        className="font-medium text-foreground hover:underline"
                      >
                        {row.name || "Untitled"}
                      </Link>
                      {row.brand ? (
                        <p className="text-xs text-muted-foreground">
                          {row.brand.name}
                          {row.brand.industry ? ` · ${row.brand.industry}` : ""}
                        </p>
                      ) : (
                        <p className="text-xs text-muted-foreground italic">No brand</p>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <StatusPill value={row.status} />
                      {row.brand && row.brand.status !== "ACTIVE" ? (
                        <p className="mt-1 text-[0.625rem] text-muted-foreground">
                          brand {row.brand.status.toLowerCase()}
                        </p>
                      ) : null}
                    </td>
                    <td className="px-3 py-2.5 text-xs">
                      {row.plan ? (
                        <>
                          <p className="text-foreground">{row.plan.name}</p>
                          <p className="text-muted-foreground">{row.subscription_status ?? ""}</p>
                        </>
                      ) : (
                        <span className="text-muted-foreground">No plan</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-xs">
                      {row.onboarding ? (
                        <>
                          <p className="text-foreground">
                            {row.onboarding.current_stage.replaceAll("_", " ")}
                          </p>
                          <p className="text-muted-foreground">
                            {row.onboarding.status.toLowerCase()}
                          </p>
                        </>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-xs">
                      {row.readiness ? (
                        <>
                          <p className="font-medium text-foreground">{row.readiness.score}/100</p>
                          <p className="text-muted-foreground">
                            {row.readiness.level.toLowerCase()}
                          </p>
                        </>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <UsageCell row={row} />
                    </td>
                    <td className="px-3 py-2.5 text-xs whitespace-nowrap text-muted-foreground">
                      {formatAgo(row.last_active_at)}
                    </td>
                    <td className="px-3 py-2.5">
                      <FlagChips flags={row.flags} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {totalPages > 1 ? (
            <div className="mt-4 flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">
                Page {currentPage} of {totalPages}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={loading || !list?.previous_page}
                  onClick={() => setPage(list?.previous_page ?? Math.max(1, page - 1))}
                >
                  <ChevronLeft className="size-4" /> Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={loading || !list?.next_page}
                  onClick={() => setPage(list?.next_page ?? page + 1)}
                >
                  Next <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
