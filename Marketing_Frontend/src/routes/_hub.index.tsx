/**
 * Overview — a truthful command surface for the selected client.
 *
 * Every count below comes from the workspace-scoped analytics endpoint and
 * every readiness statement comes from Brand Master. The redesign changes
 * hierarchy only; it does not invent activity or bypass any owner screen.
 */
import { queryOptions, useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  Check,
  CheckCircle2,
  GraduationCap,
  Megaphone,
  Send,
  Share2,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import {
  READINESS_COPY,
  fetchBrandMasterBootstrap,
  tabForReadinessKey,
  type BrandMasterTab,
  type ReadinessLevel,
} from "@/lib/brand-master";
import { readSelectedWorkspaceId } from "@/lib/workspace";

/**
 * Both queries are keyed by workspace so a sign-out/sign-in on the same
 * browser can never surface another tenant's cached counts, and cached for a
 * short while so returning to the Overview paints instantly from cache while
 * a background refetch keeps the numbers honest — instead of replaying the
 * skeleton screens on every visit.
 */
const OVERVIEW_STALE_MS = 30_000;

const kpisQuery = () =>
  queryOptions({
    queryKey: ["overview", "kpis", readSelectedWorkspaceId()],
    queryFn: async () => (await api<{ kpis: Kpi[] }>("/api/marketing/analytics/kpis/")).kpis ?? [],
    staleTime: OVERVIEW_STALE_MS,
  });

const brandOverviewQuery = () =>
  queryOptions({
    // One bootstrap request replaces the previous brands/current →
    // brand-master/{id}/ chain, which cost a full round trip twice, in series.
    queryKey: ["overview", "brand-master", readSelectedWorkspaceId()],
    queryFn: async () => (await fetchBrandMasterBootstrap()).overview,
    staleTime: OVERVIEW_STALE_MS,
  });

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
  // Fire-and-forget: starts both fetches the moment the workspace list has
  // resolved, roughly a second before the component tree mounts and its
  // useQuery hooks would otherwise send them. prefetchQuery never rejects and
  // useQuery below picks up the same in-flight promise.
  loader: ({ context }) => {
    if (typeof window === "undefined") return;
    void context.queryClient.prefetchQuery(kpisQuery());
    void context.queryClient.prefetchQuery(brandOverviewQuery());
  },
  component: OverviewPage,
});

interface Kpi {
  key: string;
  label: string;
  value: number;
  icon: string;
  hint?: string | null;
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
  READY: "Your brand context is ready.",
};

function kpiValue(kpis: Kpi[] | null, key: string): number | null {
  if (!kpis) return null;
  return kpis.find((item) => item.key === key)?.value ?? null;
}

function OverviewPage() {
  const kpisResult = useQuery(kpisQuery());
  const overviewResult = useQuery(brandOverviewQuery());

  // Cached data outranks a failed refresh: stale counts with the numbers
  // still on screen beat an error banner over a page that was just readable.
  const kpis = kpisResult.data ?? null;
  const kpiError =
    kpis === null && kpisResult.error
      ? kpisResult.error instanceof Error
        ? kpisResult.error.message
        : "Could not load the pipeline."
      : null;
  const overview = overviewResult.data ?? null;
  const brandError =
    overview === null && overviewResult.error
      ? overviewResult.error instanceof Error
        ? overviewResult.error.message
        : "Could not load the brand."
      : null;

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
            <div role="alert" className="mt-7 border-l-2 border-destructive pl-5">
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
              {readinessTarget === "create" ? (
                <Link
                  to="/publishing"
                  className="lime-link mt-6 inline-flex items-center gap-2 text-sm"
                >
                  {overview.readiness.recommended_next_action.label}
                  <ArrowRight className="size-4" />
                </Link>
              ) : (
                <Link
                  to="/brand-master"
                  search={{ tab: readinessTarget }}
                  className="lime-link mt-6 inline-flex items-center gap-2 text-sm"
                >
                  {overview.readiness.recommended_next_action.label}
                  <ArrowRight className="size-4" />
                </Link>
              )}
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
                kpis === null
                  ? "Loading the review queue…"
                  : awaitingReview === null
                    ? "Review queue count unavailable."
                    : `${awaitingReview} item${awaitingReview === 1 ? "" : "s"} waiting for review.`
              }
              action="Review"
              to="/review"
            />
            <ActionRow
              icon={Send}
              label="Publish approved work"
              detail={
                kpis === null
                  ? "Loading approved content…"
                  : approved === null
                    ? "Approved content count unavailable."
                    : `${approved} approved item${approved === 1 ? "" : "s"} ready for publishing.`
              }
              action="Publish"
              to="/publishing"
            />
            {readinessTarget !== "create" ? (
              <ActionRow
                icon={GraduationCap}
                label="Teach Scaleezy"
                detail={
                  overview?.readiness.recommended_next_action.detail ??
                  "Add evidence to sharpen the next output."
                }
                action="Teach"
                to="/brand-master"
                search={{ tab: readinessTarget }}
              />
            ) : null}
          </div>
        </div>
      </section>

      <section className="app-section mt-12">
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
          <p
            role="alert"
            className="border-l-2 border-destructive bg-destructive/5 px-4 py-3 text-sm text-destructive"
          >
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
  const content = (
    <>
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
      <span className="lime-link mt-2 inline-flex items-center gap-1 text-sm">
        {action} <ArrowRight className="size-4" />
      </span>
    </>
  );

  const className =
    "group relative grid min-h-16 grid-cols-[2.5rem_minmax(0,1fr)_auto] items-start gap-4 py-3 transition-colors first:pt-0 last:pb-0 hover:bg-secondary/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";

  return search ? (
    <Link to="/brand-master" search={search} className={className}>
      {content}
    </Link>
  ) : (
    <Link to={to} className={className}>
      {content}
    </Link>
  );
}
