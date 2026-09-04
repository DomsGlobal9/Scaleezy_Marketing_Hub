import { createFileRoute } from "@tanstack/react-router";
import {
  Activity,
  DollarSign,
  Eye,
  Loader2,
  RefreshCw,
  Target,
  Upload,
  UserPlus,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";

import { PageHeader, SectionTitle, StatCard, StatusBadge } from "@/components/marketing/primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiGet, apiPost } from "@/lib/api";
import { useWorkspaces } from "@/lib/workspace";
import { hasStringFields, isRecord, parseList } from "@/lib/list-response";
import { isSyncRun, mergeSyncRun, useSyncRunPolling, type SyncRun } from "@/lib/sync-run";

export const Route = createFileRoute("/_hub/analytics")({
  head: () => ({ meta: [{ title: "Performance & Revenue — Scaleezy" }] }),
  component: AnalyticsPage,
});

interface DailyMetric {
  date: string;
  reach: number | null;
  engagement: number | null;
  posts_published: number | null;
  conversions: number | null;
}
interface PlatformMetric {
  id: string;
  platform: string;
  reach: number | null;
  engagement: number | null;
  clicks: number | null;
  conversions: number | null;
  roi_multiplier: number | null;
}
interface Observation {
  id: string;
  source: string;
  platform: string;
  content_headline: string;
  ai_provider: string;
  layout_plugin: string;
  reach: number | null;
  engagement: number | null;
  observed_at: string;
}
interface Lead {
  id: string;
  name: string;
  handle: string;
  status: string;
  source: string;
  estimated_value: string;
  currency: string;
  created_at: string;
}
interface RevenueEvent {
  id: string;
  source: string;
  external_event_id: string;
  campaign_name: string;
  amount: string;
  currency: string;
  occurred_at: string;
}
interface Dashboard {
  trend: DailyMetric[];
  platform_perf: PlatformMetric[];
  observations: Observation[];
  sync_runs: SyncRun[];
  leads: Lead[];
  revenue_events: RevenueEvent[];
  summary: {
    observation_count: number;
    lead_count: number;
    converted_leads: number;
    revenue: string | null;
    revenue_currency: string | null;
    revenue_by_currency: { currency: string; amount: string }[];
    measurements: {
      reach: number | null;
      engagement: number | null;
      clicks: number | null;
      conversions: number | null;
      measurement_coverage: Record<string, { measured: number; total: number }>;
    };
    latest_observed_at: string | null;
  };
}
interface Connection {
  id: string;
  platform: string;
  account_name: string;
  status: string;
}
const isMetric = (value: unknown) =>
  value === null || (typeof value === "number" && Number.isFinite(value));
const metricText = (value: number | null) =>
  value === null ? "Unavailable" : value.toLocaleString();
const money = (value: string | number, currency: string) => {
  if (!Number.isFinite(Number(value))) return "Unavailable";
  if (!/^[A-Z]{3}$/.test(currency))
    return `${Number(value).toLocaleString()} (currency unavailable)`;
  return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(value));
};
const compact = (value: number | null) =>
  value === null
    ? "—"
    : new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(
        value,
      );

function parseDashboard(value: unknown): Dashboard {
  if (!isRecord(value) || !isRecord(value["summary"]))
    throw new Error("Analytics returned an invalid dashboard.");
  const summary = value["summary"];
  const measurements = summary["measurements"];
  if (
    !["observation_count", "lead_count", "converted_leads"].every(
      (key) => typeof summary[key] === "number",
    ) ||
    !isRecord(measurements) ||
    !isRecord(measurements["measurement_coverage"]) ||
    !["reach", "engagement", "clicks", "conversions"].every((key) => isMetric(measurements[key])) ||
    !Array.isArray(summary["revenue_by_currency"]) ||
    !summary["revenue_by_currency"].every((row) => hasStringFields(row, ["currency", "amount"]))
  ) {
    throw new Error("Analytics returned an invalid summary.");
  }
  for (const key of [
    "trend",
    "platform_perf",
    "observations",
    "leads",
    "revenue_events",
    "sync_runs",
  ]) {
    if (!Array.isArray(value[key])) throw new Error("Analytics returned an invalid list.");
  }
  if (
    !(value["trend"] as unknown[]).every(
      (row) =>
        hasStringFields(row, ["date"]) &&
        isRecord(row) &&
        isMetric(row["reach"]) &&
        isMetric(row["engagement"]),
    ) ||
    !(value["platform_perf"] as unknown[]).every(
      (row) =>
        hasStringFields(row, ["id", "platform"]) &&
        isRecord(row) &&
        ["reach", "engagement", "clicks", "conversions"].every((key) => isMetric(row[key])),
    ) ||
    !(value["observations"] as unknown[]).every(
      (row) =>
        hasStringFields(row, ["id", "source", "platform", "observed_at"]) &&
        isRecord(row) &&
        isMetric(row["reach"]),
    ) ||
    !(value["leads"] as unknown[]).every((row) =>
      hasStringFields(row, [
        "id",
        "name",
        "handle",
        "status",
        "source",
        "estimated_value",
        "currency",
        "created_at",
      ]),
    ) ||
    !(value["revenue_events"] as unknown[]).every((row) =>
      hasStringFields(row, [
        "id",
        "source",
        "external_event_id",
        "campaign_name",
        "amount",
        "currency",
        "occurred_at",
      ]),
    ) ||
    !(value["sync_runs"] as unknown[]).every(isSyncRun)
  )
    throw new Error("Analytics returned invalid records.");
  return value as unknown as Dashboard;
}

function AnalyticsPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connection, setConnection] = useState("");
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncRuns, setSyncRuns] = useState<SyncRun[]>([]);
  const [metric, setMetric] = useState({
    platform: "",
    reach: "",
    engagement: "",
    clicks: "",
    conversions: "",
    spend: "",
    currency: "USD",
  });
  const [revenue, setRevenue] = useState({
    source: "",
    external_event_id: "",
    campaign_name: "",
    amount: "",
    currency: "USD",
  });
  const [leadForm, setLeadForm] = useState({ name: "", email: "", estimated_value: "", notes: "" });

  // Mirrors the backend gate exactly (apps/analytics/views.py GrowthLeadView
  // via GovernedAnalyticsView: POST needs EDITOR or above). An unknown role —
  // the fallback membership path reports none — is not mutation authority.
  // The server re-checks every request as the final authority.
  const { workspaces, selectedId } = useWorkspaces();
  const memberRole = workspaces.find((w) => w.id === selectedId)?.role ?? null;
  const canWriteLeads =
    memberRole !== null && ["EDITOR", "MANAGER", "ADMIN", "OWNER"].includes(memberRole);

  const load = useCallback(async () => {
    const [dashboard, accounts] = await Promise.all([
      apiGet<unknown>("/api/marketing/analytics/dashboard/"),
      apiGet<unknown>("/api/marketing/social-accounts/"),
    ]);
    const supported = parseList(
      accounts,
      (row): row is Connection =>
        hasStringFields(row, ["id", "platform", "account_name", "status"]),
      "Accounts",
    ).filter((row) => row.status === "CONNECTED" && ["X", "YOUTUBE"].includes(row.platform));
    const parsed = parseDashboard(dashboard);
    setData(parsed);
    setSyncRuns((current) => [
      ...parsed.sync_runs,
      ...current.filter(
        (run) => !run.execution.terminal && !parsed.sync_runs.some((next) => next.id === run.id),
      ),
    ]);
    setConnections(supported);
    setConnection((current) =>
      supported.some((row) => row.id === current) ? current : supported[0]?.id || "",
    );
    setError("");
  }, []);

  const handleLoadError = useCallback(
    (reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "Analytics could not load."),
    [],
  );
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      await load();
    } catch (reason) {
      handleLoadError(reason);
    } finally {
      setLoading(false);
    }
  }, [load, handleLoadError]);
  const updateSyncRun = useCallback(
    (run: SyncRun) => setSyncRuns((current) => mergeSyncRun(current, run)),
    [],
  );
  useSyncRunPolling(
    syncRuns,
    "/api/marketing/analytics/performance/sync/",
    updateSyncRun,
    load,
    handleLoadError,
  );
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const sync = async () => {
    setWorking("sync");
    try {
      const queued = await apiPost<unknown>("/api/marketing/analytics/performance/sync/", {
        social_connection: connection,
      });
      if (!isSyncRun(queued))
        throw new Error("The sync response was invalid. Refresh before starting another sync.");
      updateSyncRun(queued);
      toast.success("Performance sync queued");
      await load().catch(handleLoadError);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Sync failed");
    } finally {
      setWorking("");
    }
  };
  const importMetrics = async () => {
    setWorking("metric");
    try {
      await apiPost("/api/marketing/analytics/performance/import/", {
        source_record_id: `operator-${crypto.randomUUID()}`,
        platform: metric.platform,
        observed_at: new Date().toISOString(),
        ...Object.fromEntries(
          (["reach", "engagement", "clicks", "conversions"] as const)
            .filter((key) => metric[key].trim() !== "")
            .map((key) => [key, Number(metric[key])]),
        ),
        spend: metric.spend || "0",
        currency: metric.currency.trim().toUpperCase(),
        source_payload: { entered_from: "analytics_console" },
      });
      setMetric({
        platform: "",
        reach: "",
        engagement: "",
        clicks: "",
        conversions: "",
        spend: "",
        currency: "USD",
      });
      toast.success("Metrics imported with source lineage");
      await load().catch(handleLoadError);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Import failed");
    } finally {
      setWorking("");
    }
  };
  const recordRevenue = async () => {
    setWorking("revenue");
    try {
      await apiPost("/api/marketing/analytics/revenue/", {
        ...revenue,
        occurred_at: new Date().toISOString(),
      });
      setRevenue({
        source: "",
        external_event_id: "",
        campaign_name: "",
        amount: "",
        currency: "USD",
      });
      toast.success("Revenue attributed");
      await load().catch(handleLoadError);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Revenue could not be recorded");
    } finally {
      setWorking("");
    }
  };
  const addLead = async () => {
    setWorking("lead");
    try {
      // Manual intake: the backend defaults source to MANUAL when no
      // engagement item is linked, so only the operator fields are sent.
      await apiPost("/api/marketing/analytics/leads/", {
        name: leadForm.name.trim(),
        email: leadForm.email.trim(),
        estimated_value: leadForm.estimated_value || "0",
        notes: leadForm.notes.trim(),
      });
      setLeadForm({ name: "", email: "", estimated_value: "", notes: "" });
      toast.success("Lead captured");
      await load().catch(handleLoadError);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Lead could not be added");
    } finally {
      setWorking("");
    }
  };

  if (error && !data)
    return (
      <div
        role="alert"
        className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
      >
        <p>{error}</p>
        <Button
          className="mt-3"
          variant="outline"
          disabled={loading}
          onClick={() => void refresh()}
        >
          Try again
        </Button>
      </div>
    );
  if (!data)
    return (
      <div
        role="status"
        aria-label="Loading analytics"
        className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
      >
        {Array.from({ length: 8 }).map((_, index) => (
          <Skeleton key={index} className="h-28 rounded-xl" />
        ))}
      </div>
    );
  const freshness = data.summary.latest_observed_at
    ? new Date(data.summary.latest_observed_at).toLocaleString()
    : "No observations yet";
  const totals = data.summary.measurements;
  const coverageHint = (field: string) => {
    const coverage = totals.measurement_coverage[field];
    return coverage && coverage.measured < coverage.total
      ? `${coverage.measured} of ${coverage.total} source records measured; total unavailable`
      : freshness;
  };
  const revenueTotals = data.summary.revenue_by_currency;

  return (
    <div>
      <PageHeader
        eyebrow="Performance"
        title="Performance & revenue"
        subtitle="Every number has a source. Follow content from generation through engagement, lead and revenue."
        backTo="/"
      />
      {error ? (
        <div
          role="alert"
          className="mb-5 rounded-xl border border-destructive/30 p-4 text-sm text-destructive"
        >
          <p>{error} The last loaded data is still shown.</p>
          <Button
            className="mt-3"
            variant="outline"
            disabled={loading}
            onClick={() => void refresh()}
          >
            Try again
          </Button>
        </div>
      ) : null}
      {loading ? (
        <p role="status" className="mb-4 text-sm text-muted-foreground">
          Refreshing analytics…
        </p>
      ) : null}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard
          label="Measured reach"
          value={compact(totals.reach)}
          icon={Eye}
          hint={coverageHint("reach")}
        />
        <StatCard
          label="Engagement"
          value={compact(totals.engagement)}
          icon={Activity}
          hint={coverageHint("engagement")}
        />
        <StatCard
          label="Conversions"
          value={compact(totals.conversions)}
          icon={Target}
          hint={coverageHint("conversions")}
        />
        <StatCard
          label="Leads"
          value={String(data.summary.lead_count)}
          icon={Users}
          hint={`${data.summary.converted_leads} converted`}
        />
        <StatCard
          label="Attributed revenue"
          value={
            revenueTotals.length === 1
              ? money(revenueTotals[0]!.amount, revenueTotals[0]!.currency)
              : revenueTotals.length
                ? "Multiple currencies"
                : "—"
          }
          icon={DollarSign}
          hint={
            revenueTotals.length > 1
              ? revenueTotals.map((row) => money(row.amount, row.currency)).join(" · ")
              : revenueTotals.length
                ? "Recorded source currency; no conversion"
                : "No revenue events recorded"
          }
        />
      </section>

      <div className="mt-8 grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(20rem,0.5fr)]">
        <section className="surface-card p-5">
          <SectionTitle
            label="Measured trend"
            title="Reach and engagement"
            description="Latest cumulative observation per source post or record. Missing or partial totals stay unavailable."
          />
          {data.trend.length ? (
            <div className="mt-5 h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.trend} margin={{ left: -18, right: 12 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Line
                    type="monotone"
                    dataKey="reach"
                    stroke="var(--primary)"
                    strokeWidth={3}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="engagement"
                    stroke="var(--foreground)"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Empty text="Sync an account or import a client report to start the measured trend." />
          )}
        </section>
        <section className="surface-card p-5">
          <SectionTitle
            label="Fresh data"
            title="Sync platform metrics"
            description="Real X post metrics and YouTube public video statistics."
          />
          <Label className="mt-5 block" htmlFor="metric-account">
            Connected account
          </Label>
          <Select value={connection} onValueChange={setConnection}>
            <SelectTrigger id="metric-account" className="mt-2 w-full">
              <SelectValue placeholder="Choose X or YouTube" />
            </SelectTrigger>
            <SelectContent>
              {connections.map((row) => (
                <SelectItem key={row.id} value={row.id}>
                  {row.platform} · {row.account_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            className="mt-4 w-full"
            onClick={sync}
            disabled={
              !canWriteLeads ||
              !connection ||
              working === "sync" ||
              syncRuns.some(
                (run) => run.social_connection === connection && !run.execution.terminal,
              )
            }
          >
            {working === "sync" ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}{" "}
            Sync now
          </Button>
          <p className="mt-3 text-xs text-muted-foreground">
            For any other network, import its export below. Scaleezy does not restrict the platform.
          </p>
          {syncRuns.length > 0 && (
            <div aria-live="polite" className="mt-5 border-t pt-4">
              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                Recent syncs
              </p>
              <div className="mt-3 space-y-2">
                {syncRuns.map((run) => (
                  <div key={run.id} className="rounded-lg border p-3 text-xs">
                    <div className="flex items-center justify-between gap-3">
                      <span className="truncate font-semibold">
                        {run.platform} · {run.account_name}
                      </span>
                      <StatusBadge
                        status={run.execution.state.replaceAll("_", " ")}
                        tone={
                          run.execution.terminal && run.execution.state === "FAILED"
                            ? "danger"
                            : run.execution.terminal && run.execution.state === "COMPLETED"
                              ? "success"
                              : "neutral"
                        }
                      />
                    </div>
                    <p className="mt-1 text-muted-foreground">
                      {new Date(run.created_at).toLocaleString()}
                      {run.execution.terminal &&
                        run.execution.state === "COMPLETED" &&
                        ` · ${run.observed_count} observed`}
                    </p>
                    {run.error && (
                      <p className="mt-1 break-words text-destructive">
                        {run.error}
                        {!run.execution.terminal
                          ? " The background task still owns this attempt."
                          : ""}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>

      <Tabs defaultValue="platforms" className="mt-10">
        <TabsList className="flex h-auto flex-wrap justify-start">
          <TabsTrigger value="platforms">Platforms</TabsTrigger>
          <TabsTrigger value="sources">Source ledger</TabsTrigger>
          <TabsTrigger value="revenue">Leads &amp; revenue</TabsTrigger>
          <TabsTrigger value="intake">Data intake</TabsTrigger>
        </TabsList>
        <TabsContent value="platforms" className="mt-5">
          <section className="surface-card p-5">
            <SectionTitle
              label="Channel comparison"
              title="Performance by platform"
              description="Unavailable and partially measured totals are shown as unavailable. A recorded zero remains zero."
            />
            {data.platform_perf.length ? (
              <>
                <div className="mt-5 h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.platform_perf} margin={{ left: -18 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="platform" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Bar dataKey="reach" fill="var(--primary)" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="engagement" fill="var(--foreground)" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <PlatformTable rows={data.platform_perf} />
              </>
            ) : (
              <Empty text="No measured platform performance yet." />
            )}
          </section>
        </TabsContent>
        <TabsContent value="sources" className="mt-5">
          <SourceLedger rows={data.observations} />
        </TabsContent>
        <TabsContent value="revenue" className="mt-5">
          <div className="grid gap-5 xl:grid-cols-2">
            <section className="surface-card p-5">
              <SectionTitle
                label="Pipeline"
                title="Captured leads"
                description="Governed engagement capture and manual team intake."
              />
              <div className="mt-5 space-y-3">
                {data.leads.map((lead) => (
                  <article
                    key={lead.id}
                    className="flex items-center justify-between gap-4 rounded-lg border p-4"
                  >
                    <div>
                      <p className="font-semibold">{lead.name || lead.handle || "Unnamed lead"}</p>
                      <p className="text-xs text-muted-foreground">
                        {lead.source} · {new Date(lead.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      {Number(lead.estimated_value) > 0 && (
                        <span className="text-sm font-semibold">
                          {money(lead.estimated_value, lead.currency)}
                        </span>
                      )}
                      <StatusBadge
                        status={lead.status}
                        tone={lead.status === "CONVERTED" ? "success" : "neutral"}
                      />
                    </div>
                  </article>
                ))}
                {!data.leads.length && (
                  <p className="text-sm text-muted-foreground">
                    No leads captured yet. Capture one from the Engagement inbox or add one below.
                  </p>
                )}
              </div>
              <div className="mt-5 border-t pt-4">
                <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  Add lead
                </p>
                {!canWriteLeads && (
                  // Same explanation the backend's 403 gives, shown before
                  // anyone fills a form they cannot submit.
                  <p className="mt-3 rounded-lg border border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
                    Only a marketing executive or above can capture leads.
                  </p>
                )}
                <div className="mt-3 grid gap-4 sm:grid-cols-2">
                  <Field
                    id="lead-name"
                    label="Name"
                    value={leadForm.name}
                    onChange={(name) => setLeadForm({ ...leadForm, name })}
                  />
                  <Field
                    id="lead-email"
                    label="Email"
                    value={leadForm.email}
                    onChange={(email) => setLeadForm({ ...leadForm, email })}
                  />
                  <Field
                    id="lead-value"
                    label="Estimated value"
                    value={leadForm.estimated_value}
                    onChange={(estimated_value) => setLeadForm({ ...leadForm, estimated_value })}
                    number
                  />
                  <Field
                    id="lead-notes"
                    label="Notes"
                    value={leadForm.notes}
                    onChange={(notes) => setLeadForm({ ...leadForm, notes })}
                  />
                </div>
                <Button
                  className="mt-4"
                  onClick={addLead}
                  disabled={!leadForm.name.trim() || !canWriteLeads || working === "lead"}
                >
                  {working === "lead" ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <UserPlus className="size-4" />
                  )}{" "}
                  Add lead
                </Button>
              </div>
            </section>
            <section className="surface-card p-5">
              <SectionTitle
                label="Revenue lineage"
                title="Attributed events"
                description="Idempotent billing, CRM or operator events."
              />
              <div className="mt-5 space-y-3">
                {data.revenue_events.map((event) => (
                  <article
                    key={event.id}
                    className="flex items-center justify-between gap-4 rounded-lg border p-4"
                  >
                    <div>
                      <p className="font-semibold">{event.campaign_name || event.source}</p>
                      <p className="text-xs text-muted-foreground">{event.external_event_id}</p>
                    </div>
                    <strong>{money(event.amount, event.currency)}</strong>
                  </article>
                ))}
                {!data.revenue_events.length && (
                  <p className="text-sm text-muted-foreground">No attributed revenue yet.</p>
                )}
              </div>
            </section>
          </div>
        </TabsContent>
        <TabsContent value="intake" className="mt-5">
          <div className="grid gap-5 xl:grid-cols-2">
            <MetricForm
              value={metric}
              onChange={setMetric}
              onSubmit={importMetrics}
              busy={working === "metric"}
            />
            <RevenueForm
              value={revenue}
              onChange={setRevenue}
              onSubmit={recordRevenue}
              busy={working === "revenue"}
            />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <p className="mt-5 rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
      {text}
    </p>
  );
}
function PlatformTable({ rows }: { rows: PlatformMetric[] }) {
  return (
    <div className="mt-5 overflow-x-auto">
      <table className="w-full min-w-[44rem] text-sm">
        <thead>
          <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
            {["Platform", "Reach", "Engagement", "Clicks", "Conversions"].map((head) => (
              <th key={head} className="px-3 py-3 font-medium">
                {head}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b last:border-0">
              <td className="px-3 py-3 font-semibold">{row.platform}</td>
              <td className="px-3 py-3">{metricText(row.reach)}</td>
              <td className="px-3 py-3">{metricText(row.engagement)}</td>
              <td className="px-3 py-3">{metricText(row.clicks)}</td>
              <td className="px-3 py-3">{metricText(row.conversions)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function SourceLedger({ rows }: { rows: Observation[] }) {
  return (
    <section className="surface-card overflow-hidden">
      <div className="border-b p-5">
        <SectionTitle
          label="Provenance"
          title="Observation ledger"
          description="Source, content, provider and layout behind every measurement."
        />
      </div>
      <div className="grid gap-3 p-4 lg:hidden">
        {rows.map((row) => (
          <article key={row.id} className="rounded-lg border p-4">
            <div className="flex items-center justify-between gap-3">
              <strong>{row.platform}</strong>
              <StatusBadge status={row.source} />
            </div>
            <p className="mt-2 text-sm">{row.content_headline || "Unlinked observation"}</p>
            <p className="mt-2 text-xs text-muted-foreground">
              Reach {metricText(row.reach)} · {new Date(row.observed_at).toLocaleString()}
            </p>
          </article>
        ))}
      </div>
      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full min-w-[54rem] text-sm">
          <thead>
            <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
              {["Observed", "Platform", "Source", "Content", "AI provider", "Layout", "Reach"].map(
                (head) => (
                  <th key={head} className="px-4 py-3 font-medium">
                    {head}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-b last:border-0">
                <td className="px-4 py-3 whitespace-nowrap">
                  {new Date(row.observed_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3 font-semibold">{row.platform}</td>
                <td className="px-4 py-3">{row.source}</td>
                <td className="max-w-64 truncate px-4 py-3">{row.content_headline || "—"}</td>
                <td className="px-4 py-3">{row.ai_provider || "—"}</td>
                <td className="px-4 py-3">{row.layout_plugin || "—"}</td>
                <td className="px-4 py-3">{metricText(row.reach)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && (
        <p className="p-8 text-center text-sm text-muted-foreground">No source observations yet.</p>
      )}
    </section>
  );
}

type MetricValue = {
  platform: string;
  reach: string;
  engagement: string;
  clicks: string;
  conversions: string;
  spend: string;
  currency: string;
};
function MetricForm({
  value,
  onChange,
  onSubmit,
  busy,
}: {
  value: MetricValue;
  onChange: (value: MetricValue) => void;
  onSubmit: () => void;
  busy: boolean;
}) {
  return (
    <section className="surface-card p-5">
      <SectionTitle
        label="Any platform"
        title="Import auditable metrics"
        description="Use a platform export. Leave unmeasured fields blank; enter zero only when the source reports zero."
      />
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <Field
          id="metric-platform"
          label="Platform"
          value={value.platform}
          onChange={(platform) => onChange({ ...value, platform })}
          wide
        />
        {(["reach", "engagement", "clicks", "conversions", "spend"] as const).map((key) => (
          <Field
            key={key}
            id={`metric-${key}`}
            label={key}
            value={value[key]}
            onChange={(next) => onChange({ ...value, [key]: next })}
            number
          />
        ))}
        <Field
          id="metric-currency"
          label="Spend currency (3-letter code)"
          value={value.currency}
          onChange={(currency) => onChange({ ...value, currency: currency.toUpperCase() })}
        />
      </div>
      <Button className="mt-5" onClick={onSubmit} disabled={!value.platform.trim() || busy}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />} Import
        metrics
      </Button>
    </section>
  );
}
type RevenueValue = {
  source: string;
  external_event_id: string;
  campaign_name: string;
  amount: string;
  currency: string;
};
function RevenueForm({
  value,
  onChange,
  onSubmit,
  busy,
}: {
  value: RevenueValue;
  onChange: (value: RevenueValue) => void;
  onSubmit: () => void;
  busy: boolean;
}) {
  return (
    <section className="surface-card p-5">
      <SectionTitle
        label="Monetization"
        title="Record revenue"
        description="Use the immutable Stripe, CRM, invoice or other source event id to prevent double-counting."
      />
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <Field
          id="revenue-source"
          label="Source"
          value={value.source}
          onChange={(source) => onChange({ ...value, source })}
        />
        <Field
          id="revenue-id"
          label="External event id"
          value={value.external_event_id}
          onChange={(external_event_id) => onChange({ ...value, external_event_id })}
        />
        <Field
          id="revenue-campaign"
          label="Campaign"
          value={value.campaign_name}
          onChange={(campaign_name) => onChange({ ...value, campaign_name })}
        />
        <Field
          id="revenue-amount"
          label="Amount"
          value={value.amount}
          onChange={(amount) => onChange({ ...value, amount })}
          number
        />
        <Field
          id="revenue-currency"
          label="Currency (3-letter code)"
          value={value.currency}
          onChange={(currency) => onChange({ ...value, currency: currency.toUpperCase() })}
        />
      </div>
      <Button
        className="mt-5"
        onClick={onSubmit}
        disabled={!value.source.trim() || !value.external_event_id.trim() || !value.amount || busy}
      >
        {busy ? <Loader2 className="size-4 animate-spin" /> : <DollarSign className="size-4" />}{" "}
        Record revenue
      </Button>
    </section>
  );
}
function Field({
  id,
  label,
  value,
  onChange,
  number = false,
  wide = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  number?: boolean;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "sm:col-span-2" : ""}>
      <Label htmlFor={id}>
        {label[0]?.toUpperCase()}
        {label.slice(1)}
      </Label>
      <Input
        id={id}
        className="mt-2"
        type={number ? "number" : "text"}
        min={number ? "0" : undefined}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}
