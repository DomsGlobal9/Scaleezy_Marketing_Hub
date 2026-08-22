/**
 * Analytics — the publishing activity that is real, and the performance
 * surface that does not exist yet.
 *
 * The six charts and the per-platform table read DailyMetric,
 * PlatformPerformance and CampaignROI. Nothing in the product writes to those
 * three tables, so each one could only ever draw an empty framed chart under a
 * provenance badge — which reads as measured zero performance rather than as a
 * capability that was never built. They stay on the page as disabled
 * placeholders so its intended shape is still legible, and the dashboard
 * request that fed them is no longer sent.
 */
import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AlertTriangle, CalendarClock, Send, Share2 } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, SectionTitle, StatCard } from "@/components/marketing/primitives";
import { api } from "@/lib/api";

export const Route = createFileRoute("/_hub/analytics")({
  head: () => ({
    meta: [
      { title: "Marketing Analytics — Scaleezy Marketing Hub" },
      {
        name: "description",
        content: "Reach, engagement, conversions and ROI across every connected marketing channel.",
      },
      { property: "og:title", content: "Marketing Analytics — Scaleezy Marketing Hub" },
      {
        property: "og:description",
        content: "Understand how your marketing performs across connected channels.",
      },
    ],
  }),
  component: AnalyticsPage,
});

interface Kpi {
  key: string;
  label: string;
  value: number;
  hint?: string | null;
}

/** The performance charts this page is designed around, in their intended order. */
const PLANNED_CHARTS = [
  "Reach over time",
  "Engagement over time",
  "Platform Performance",
  "Platform comparison",
  "Conversion trend",
  "Campaign ROI",
];

const UNAVAILABLE = "Not available yet";

function ChartPlaceholder({ title }: { title: string }) {
  return (
    <div className="surface-card p-5">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
        <h3 className="truncate text-sm font-semibold text-muted-foreground">{title}</h3>
        <span className="shrink-0 rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground">
          {UNAVAILABLE}
        </span>
      </div>
      <div className="mt-4 h-32 w-full rounded-lg border border-dashed border-border" />
    </div>
  );
}

function AnalyticsPage() {
  const [kpis, setKpis] = useState<Kpi[] | null>(null);
  const [kpiError, setKpiError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // A failed load used to be flattened into an empty array, so a 403 or a 500
    // looked exactly like a workspace that has published nothing.
    api<{ kpis: Kpi[] }>("/api/marketing/analytics/kpis/")
      .then((data) => {
        if (!cancelled) setKpis(data.kpis ?? []);
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setKpiError(e instanceof Error ? e.message : "Could not load publishing activity.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="Analytics"
        subtitle="Publishing activity now, platform performance as metrics are ingested."
        backTo="/"
      />

      {kpiError ? (
        <p className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {kpiError}
        </p>
      ) : (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {kpis === null
            ? // The skeleton has to stand in for the cards, not sit inside them:
              // mapping over a null result yields nothing to carry a loading prop.
              Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-28 rounded-xl" />
              ))
            : kpis
                .filter((k) =>
                  ["published", "scheduled", "failed", "connected_accounts"].includes(k.key),
                )
                .map((k) => (
                  <StatCard
                    key={k.key}
                    label={k.label}
                    value={String(k.value)}
                    icon={
                      k.key === "connected_accounts"
                        ? Share2
                        : k.key === "failed"
                          ? AlertTriangle
                          : k.key === "scheduled"
                            ? CalendarClock
                            : Send
                    }
                    {...(k.hint ? { hint: k.hint } : {})}
                  />
                ))}
        </section>
      )}

      <div className="mt-6 rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">Performance reporting is not available yet.</p>
        <p className="mt-1">
          Reach, engagement, clicks, conversions and ROI need a metrics source, and none is
          connected to this workspace. Nothing is estimated in the meantime — the counts above are
          real publishing activity.
        </p>
      </div>

      <section className="mt-10 grid gap-4 xl:grid-cols-2">
        {PLANNED_CHARTS.map((title) => (
          <ChartPlaceholder key={title} title={title} />
        ))}
      </section>

      <section className="mt-10">
        <SectionTitle
          label="Campaign Performance"
          title="Platform performance"
          description="Per-platform reach, engagement, clicks, conversions and ROI, once a metrics source is connected."
        />
        <div className="surface-card overflow-hidden">
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs tracking-wide text-muted-foreground uppercase">
                  {["Platform", "Reach", "Engagement", "Clicks", "Conversions", "ROI"].map((h) => (
                    <th key={h} className="px-4 py-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-sm text-muted-foreground">
                    {UNAVAILABLE} — nothing ingests per-platform metrics.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="p-4 text-sm text-muted-foreground lg:hidden">
            {UNAVAILABLE} — nothing ingests per-platform metrics.
          </div>
        </div>
      </section>
    </div>
  );
}
