/**
 * Overview — a truthful command surface for the selected client.
 *
 * Every count below comes from the workspace-scoped analytics endpoint and
 * every readiness statement comes from Brand Master. The redesign changes
 * hierarchy only; it does not invent activity or bypass any owner screen.
 */
import { useEffect, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CalendarClock,
  Check,
  CheckCircle2,
  GraduationCap,
  Megaphone,
  PencilLine,
  Send,
  Share2,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import {
  READINESS_COPY,
  fetchCurrentBrand,
  fetchOverview,
  tabForReadinessKey,
  type BrandMasterTab,
  type BrandMasterOverview,
  type ReadinessLevel,
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

const KPI_ROUTE: Record<string, "/review" | "/publishing" | "/accounts"> = {
  awaiting_review: "/review",
  approved: "/review",
  scheduled: "/publishing",
  published: "/publishing",
  failed: "/publishing",
  connected_accounts: "/accounts",
};

const READINESS_HEADLINE: Record<ReadinessLevel, string> = {
  STARTING: "Your brand is taking shape.",
  LEARNING: "Your brand is learning.",
  STRONG: "Your brand is ready to create.",
  READY: "Your brand is scale-ready.",
};

const LIFECYCLE = [
  {
    label: "Plan",
    detail: "Teach the brief and define the goal.",
    to: "/brand-master" as const,
    icon: PencilLine,
  },
  {
    label: "Create",
    detail: "Generate from the active Brand Brain.",
    to: "/publishing" as const,
    icon: Sparkles,
  },
  {
    label: "Review",
    detail: "Collaborate, correct and approve.",
    to: "/review" as const,
    icon: Users,
  },
  {
    label: "Publish",
    detail: "Schedule across connected channels.",
    to: "/publishing" as const,
    icon: Send,
  },
  {
    label: "Analyze",
    detail: "Read performance and improve.",
    to: "/analytics" as const,
    icon: BarChart3,
  },
] as const;

function kpiValue(kpis: Kpi[] | null, key: string): number | null {
  if (!kpis) return null;
  return kpis.find((item) => item.key === key)?.value ?? 0;
}

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
      .catch((error: unknown) => {
        if (!cancelled) {
          setKpiError(error instanceof Error ? error.message : "Could not load the pipeline.");
        }
      });

    fetchCurrentBrand()
      .then((brand) => fetchOverview(brand.id))
      .then((data) => {
        if (!cancelled) setOverview(data);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setBrandError(error instanceof Error ? error.message : "Could not load the brand.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const readinessTarget = overview
    ? tabForReadinessKey(overview.readiness.recommended_next_action.key)
    : "overview";
  const awaitingReview = kpiValue(kpis, "awaiting_review");
  const approved = kpiValue(kpis, "approved");
  const scheduled = kpiValue(kpis, "scheduled");

  return (
    <div>
      {overview?.brand.status === "PENDING" ? (
        <div
          role="status"
          className="mb-8 flex items-start gap-3 border border-primary/45 bg-primary/10 px-4 py-3 text-sm"
        >
          <Sparkles className="mt-0.5 size-4 shrink-0 text-primary" />
          <p>
            <span className="font-semibold text-foreground">Awaiting Scaleezy approval.</span>{" "}
            <span className="text-muted-foreground">
              Brand Master and setup remain open; calibration and generation unlock after approval.
            </span>
          </p>
        </div>
      ) : null}

      <section className="grid gap-10 lg:grid-cols-[minmax(0,1.05fr)_minmax(26rem,0.95fr)] lg:gap-16">
        <div className="min-w-0 py-2 lg:py-8">
          <p className="text-xs font-bold tracking-[0.18em] text-muted-foreground uppercase">
            Editorial operations cockpit
          </p>

          {brandError ? (
            <div className="mt-7 border-l-2 border-destructive pl-5">
              <h1 className="text-4xl leading-[1.02] font-bold tracking-[-0.045em] sm:text-6xl">
                Your brand status is unavailable.
              </h1>
              <p className="mt-4 text-sm text-destructive">{brandError}</p>
            </div>
          ) : overview ? (
            <>
              <h1 className="mt-7 max-w-[10ch] text-5xl leading-[0.98] font-bold tracking-[-0.055em] text-foreground sm:text-6xl xl:text-7xl">
                {READINESS_HEADLINE[overview.readiness.readiness_level]}
              </h1>
              <p className="mt-6 max-w-xl text-base leading-7 text-muted-foreground sm:text-lg">
                {READINESS_COPY[overview.readiness.readiness_level].blurb} Current readiness is{" "}
                <strong className="font-semibold text-foreground">
                  {overview.readiness.readiness_score}%
                </strong>
                .
              </p>
              <Link
                to="/brand-master"
                search={{ tab: readinessTarget === "create" ? "overview" : readinessTarget }}
                className="lime-link mt-6 inline-flex items-center gap-2 text-sm"
              >
                {overview.readiness.recommended_next_action.label}
                <ArrowRight className="size-4" />
              </Link>
            </>
          ) : (
            <div className="mt-7 space-y-5">
              <Skeleton className="h-16 w-full max-w-lg" />
              <Skeleton className="h-16 w-4/5 max-w-md" />
              <Skeleton className="h-5 w-full max-w-xl" />
              <Skeleton className="h-5 w-2/3 max-w-md" />
            </div>
          )}
        </div>

        <div className="min-w-0">
          <p className="mb-5 text-xs font-bold tracking-[0.18em] text-foreground uppercase">
            Next actions
          </p>
          <div className="relative space-y-0 before:absolute before:top-6 before:bottom-6 before:left-5 before:w-px before:bg-border">
            <ActionRow
              icon={Sparkles}
              label="Generate a campaign"
              detail="Create content from the active Brand Brain."
              action="Create"
              to="/publishing"
              primary
            />
            <ActionRow
              icon={Check}
              label="Review content"
              detail={
                awaitingReview === null
                  ? "Loading the review queue…"
                  : `${awaitingReview} item${awaitingReview === 1 ? "" : "s"} waiting for review.`
              }
              action="Review"
              to="/review"
            />
            <ActionRow
              icon={Send}
              label="Publish approved work"
              detail={
                approved === null
                  ? "Loading approved content…"
                  : `${approved} approved item${approved === 1 ? "" : "s"} ready for publishing.`
              }
              action="Publish"
              to="/publishing"
            />
            <ActionRow
              icon={GraduationCap}
              label="Teach Scaleezy"
              detail={
                overview?.readiness.recommended_next_action.detail ??
                "Add evidence to sharpen the next output."
              }
              action="Teach"
              to="/brand-master"
              search={{ tab: readinessTarget === "create" ? "teach" : readinessTarget }}
            />
          </div>
        </div>
      </section>

      <section className="app-section mt-12">
        <p className="mb-6 text-xs font-bold tracking-[0.18em] text-foreground uppercase">
          Content lifecycle
        </p>
        <div className="scrollbar-hide -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <ol className="grid min-w-[800px] grid-cols-5 gap-8">
            {LIFECYCLE.map((step, index) => (
              <li key={step.label} className="relative">
                {index < LIFECYCLE.length - 1 ? (
                  <span
                    className="absolute top-6 left-14 h-px w-[calc(100%-3rem)] bg-border"
                    aria-hidden
                  />
                ) : null}
                <Link to={step.to} className="group relative block pr-4">
                  <span
                    className={
                      index === 0
                        ? "grid size-12 place-items-center rounded-full border border-primary bg-primary text-primary-foreground"
                        : "grid size-12 place-items-center rounded-full border border-border bg-background text-foreground transition-colors group-hover:border-primary group-hover:text-primary"
                    }
                  >
                    <step.icon className="size-5" strokeWidth={1.8} />
                  </span>
                  <span className="mt-4 block text-sm font-semibold text-foreground">
                    {step.label}
                  </span>
                  <span className="mt-1 block max-w-[10rem] text-xs leading-5 text-muted-foreground">
                    {step.detail}
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="app-section mt-10">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-bold tracking-[0.18em] text-foreground uppercase">
              Live pipeline
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Workspace-scoped counts from the systems that own them.
            </p>
          </div>
          {scheduled !== null ? (
            <Link to="/publishing" className="lime-link inline-flex items-center gap-2 text-sm">
              {scheduled} scheduled <ArrowRight className="size-4" />
            </Link>
          ) : null}
        </div>

        {kpiError ? (
          <p className="border-l-2 border-destructive bg-destructive/5 px-4 py-3 text-sm text-destructive">
            {kpiError}
          </p>
        ) : kpis === null ? (
          <div className="space-y-1">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        ) : (
          <div className="divide-y divide-border border-y border-border">
            {kpis.map((kpi) => {
              const Icon = ICON_MAP[kpi.icon] ?? Megaphone;
              return (
                <Link
                  key={kpi.key}
                  to={KPI_ROUTE[kpi.key] ?? "/publishing"}
                  className="group grid min-h-16 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-4 py-3 transition-colors hover:bg-secondary/70 sm:px-3"
                >
                  <Icon className="size-5 text-primary" strokeWidth={1.8} />
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-foreground">{kpi.label}</span>
                    {kpi.hint ? (
                      <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                        {kpi.hint}
                      </span>
                    ) : null}
                  </span>
                  <span className="flex items-center gap-3 text-2xl font-bold tracking-tight text-foreground">
                    {kpi.value}
                    <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
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

function ActionRow({
  icon: Icon,
  label,
  detail,
  action,
  to,
  search,
  primary = false,
}: {
  icon: LucideIcon;
  label: string;
  detail: string;
  action: string;
  to: "/publishing" | "/review" | "/brand-master";
  search?: { tab: BrandMasterTab };
  primary?: boolean;
}) {
  return (
    <div className="relative grid grid-cols-[2.5rem_minmax(0,1fr)_auto] items-start gap-4 py-3 first:pt-0 last:pb-0">
      <span
        className={
          primary
            ? "relative z-10 grid size-10 place-items-center rounded-full border border-primary bg-primary text-primary-foreground"
            : "relative z-10 grid size-10 place-items-center rounded-full border border-primary bg-background text-primary"
        }
      >
        <Icon className="size-4.5" strokeWidth={2} />
      </span>
      <span className="min-w-0 pt-0.5">
        <span className="block text-sm font-semibold text-foreground">{label}</span>
        <span className="mt-1 block text-sm leading-5 text-muted-foreground">{detail}</span>
      </span>
      {search ? (
        <Link
          to="/brand-master"
          search={search}
          className="lime-link mt-2 inline-flex items-center gap-1 text-sm"
        >
          {action} <ArrowRight className="size-4" />
        </Link>
      ) : (
        <Link to={to} className="lime-link mt-2 inline-flex items-center gap-1 text-sm">
          {action} <ArrowRight className="size-4" />
        </Link>
      )}
    </div>
  );
}
