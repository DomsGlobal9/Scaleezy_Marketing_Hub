/**
 * Overview — where the work stands today.
 *
 * Everything on this page is a real count or a real state: the brand's
 * readiness from Brand Master, the pipeline from the content, publishing and
 * account tables. Nothing decorative, and every tile opens the screen that
 * owns the number.
 */
import { useEffect, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  GraduationCap,
  Megaphone,
  Send,
  Share2,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, SectionTitle } from "@/components/marketing/primitives";
import { api } from "@/lib/api";
import {
  READINESS_COPY,
  fetchCurrentBrand,
  fetchOverview,
  tabForReadinessKey,
  type BrandMasterOverview,
} from "@/lib/brand-master";

export const Route = createFileRoute("/_hub/")({
  head: () => ({
    meta: [
      { title: "Overview — Scaleezy Marketing Hub" },
      {
        name: "description",
        content: "Brand readiness, the content pipeline and connected channels.",
      },
    ],
  }),
  component: OverviewPage,
});

interface Kpi {
  key: string;
  label: string;
  value: number;
  icon: string;
  hint?: string | null;
  accent?: "gold";
}

const ICON_MAP: Record<string, LucideIcon> = {
  CheckCircle2,
  Send,
  CalendarClock,
  Megaphone,
  AlertTriangle,
  Share2,
};

/** Which screen owns each pipeline number. */
const KPI_ROUTE: Record<string, "/review" | "/publishing" | "/accounts"> = {
  awaiting_review: "/review",
  approved: "/review",
  scheduled: "/publishing",
  published: "/publishing",
  failed: "/publishing",
  connected_accounts: "/accounts",
};

function OverviewPage() {
  const [kpis, setKpis] = useState<Kpi[] | null>(null);
  const [kpiError, setKpiError] = useState<string | null>(null);
  const [overview, setOverview] = useState<BrandMasterOverview | null>(null);
  const [brandError, setBrandError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<{ kpis: Kpi[] }>("/api/marketing/analytics/kpis/")
      .then((data) => {
        if (!cancelled) setKpis(data.kpis ?? []);
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setKpiError(e instanceof Error ? e.message : "Could not load the pipeline.");
      });
    fetchCurrentBrand()
      .then((brand) => fetchOverview(brand.id))
      .then((data) => {
        if (!cancelled) setOverview(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setBrandError(e instanceof Error ? e.message : "Could not load the brand.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="Overview"
        subtitle="Teach Scaleezy your brand, create on-brand content, review it, publish it — and let every decision make the next one better."
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/brand-master" search={{ tab: "teach" }}>
                <GraduationCap className="size-4" /> Teach Scaleezy
              </Link>
            </Button>
            <Button asChild>
              <Link to="/publishing">
                <Sparkles className="size-4" /> Create content
              </Link>
            </Button>
          </>
        }
      />

      {overview?.brand.status === "PENDING" ? (
        <div
          role="status"
          className="mb-6 flex items-start gap-3 rounded-xl border border-gold/40 bg-gold/10 px-4 py-3 text-sm"
        >
          <Sparkles className="mt-0.5 size-4 shrink-0 text-gold" />
          <p>
            <span className="font-medium text-foreground">Awaiting Scaleezy approval</span>
            <span className="text-muted-foreground">
              {" "}
              — calibration and generation unlock once approved. Brand Master and setup stay open;
              everything you teach now is kept.
            </span>
          </p>
        </div>
      ) : null}

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <BrandCard overview={overview} error={brandError} />
        <div className="surface-card p-6">
          <p className="label-eyebrow">How Scaleezy works</p>
          <ol className="mt-3 space-y-2 text-sm">
            {[
              [
                "Teach",
                "Brand basics, knowledge, inspirations and your taste go into Brand Master.",
                "/brand-master",
              ],
              [
                "Create",
                "Generation reads the compiled Brand Brain through the Context Gateway.",
                "/publishing",
              ],
              ["Review", "Approve, reject or send back. Every decision is evidence.", "/review"],
              [
                "Publish",
                "Approved content goes out through your connected accounts.",
                "/publishing",
              ],
            ].map(([step, detail, to]) => (
              <li key={step} className="flex items-start gap-3">
                <span className="mt-0.5 w-16 shrink-0 text-xs font-semibold tracking-wide text-foreground uppercase">
                  {step}
                </span>
                <Link
                  to={to as "/brand-master"}
                  className="text-muted-foreground hover:text-foreground"
                >
                  {detail}
                </Link>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="mt-10">
        <SectionTitle
          label="Pipeline"
          title="Where the work stands"
          description="Live counts. Each opens the screen that owns it."
        />
        {kpiError ? (
          <p className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
            {kpiError}
          </p>
        ) : kpis === null ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-28 rounded-xl" />
            ))}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {kpis.map((kpi) => {
              const Icon = ICON_MAP[kpi.icon] ?? Megaphone;
              const to = KPI_ROUTE[kpi.key] ?? "/publishing";
              return (
                <Link
                  key={kpi.key}
                  to={to}
                  className="surface-card group flex items-start gap-4 p-5 transition-transform duration-200 hover:-translate-y-0.5"
                >
                  <span
                    className={`grid size-10 shrink-0 place-items-center rounded-lg ${kpi.accent === "gold" ? "bg-gold/15 text-gold" : "bg-primary/10 text-primary"}`}
                  >
                    <Icon className="size-5" strokeWidth={1.75} />
                  </span>
                  <span className="min-w-0">
                    <span className="block font-display text-3xl leading-none font-semibold text-foreground">
                      {kpi.value}
                    </span>
                    <span className="mt-1.5 block text-sm font-medium text-foreground">
                      {kpi.label}
                    </span>
                    {kpi.hint ? (
                      <span className="mt-0.5 block text-xs text-muted-foreground">{kpi.hint}</span>
                    ) : null}
                  </span>
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

function BrandCard({
  overview,
  error,
}: {
  overview: BrandMasterOverview | null;
  error: string | null;
}) {
  if (error) {
    return (
      <div className="surface-card p-6">
        <p className="label-eyebrow">Brand</p>
        <p className="mt-3 text-sm text-destructive">{error}</p>
      </div>
    );
  }
  if (!overview) {
    return (
      <div className="surface-card p-6">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="mt-4 h-10 w-48" />
        <Skeleton className="mt-4 h-3 w-full" />
        <Skeleton className="mt-6 h-9 w-40" />
      </div>
    );
  }
  const { brand, readiness } = overview;
  const copy = READINESS_COPY[readiness.readiness_level];
  const target = tabForReadinessKey(readiness.recommended_next_action.key);
  const low = readiness.readiness_level === "STARTING" || readiness.readiness_level === "LEARNING";

  return (
    <div className="surface-card p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="label-eyebrow">Brand</p>
          <h2 className="mt-1 truncate font-display text-2xl font-semibold tracking-tight">
            {brand.name}
          </h2>
          <p className="text-sm text-muted-foreground">{brand.industry || "No industry set"}</p>
        </div>
        <span className="rounded-full border border-border bg-secondary/60 px-2.5 py-1 text-xs font-medium">
          {copy.label}
        </span>
      </div>
      <div className="mt-5 flex items-baseline gap-2">
        <span className="font-display text-4xl leading-none font-semibold">
          {readiness.readiness_score}
        </span>
        <span className="text-sm text-muted-foreground">/ 100 brand readiness</span>
      </div>
      <Progress value={readiness.readiness_score} className="mt-3" />
      <p className="mt-3 text-sm text-foreground">{readiness.recommended_next_action.label}</p>
      <p className="text-xs text-muted-foreground">{readiness.recommended_next_action.detail}</p>
      <div className="mt-5 flex flex-wrap gap-2">
        {target === "create" ? (
          <Button asChild size="sm">
            <Link to="/publishing">
              Create content <ArrowRight className="size-4" />
            </Link>
          </Button>
        ) : (
          <Button asChild size="sm" variant={low ? "default" : "outline"}>
            <Link to="/brand-master" search={{ tab: target }}>
              {low ? "Continue teaching Scaleezy" : "Do this next"}{" "}
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        )}
        <Button asChild size="sm" variant="ghost">
          <Link to="/brand-master">Open Brand Master</Link>
        </Button>
      </div>
    </div>
  );
}
