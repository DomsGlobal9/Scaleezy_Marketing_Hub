import { createFileRoute } from "@tanstack/react-router";
import { Activity, DollarSign, Eye, Loader2, RefreshCw, Target, Upload, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
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

export const Route = createFileRoute("/_hub/analytics")({
  head: () => ({ meta: [{ title: "Performance & Revenue — Scaleezy" }] }),
  component: AnalyticsPage,
});

interface DailyMetric {
  date: string;
  reach: number;
  engagement: number;
  posts_published: number;
  conversions: number;
}
interface PlatformMetric {
  id: string;
  platform: string;
  reach: number;
  engagement: number;
  clicks: number;
  conversions: number;
  roi_multiplier: number;
}
interface Observation {
  id: string;
  source: string;
  platform: string;
  content_headline: string;
  ai_provider: string;
  layout_plugin: string;
  reach: number;
  engagement: number;
  observed_at: string;
}
interface SyncRun {
  id: string;
  account_name: string;
  platform: string;
  status: string;
  observed_count: number;
  error: string;
  created_at: string;
}
interface Lead {
  id: string;
  name: string;
  handle: string;
  status: string;
  source: string;
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
    revenue: string;
    latest_observed_at: string | null;
  };
}
interface Connection {
  id: string;
  platform: string;
  account_name: string;
  status: string;
}
interface ListEnvelope<T> {
  results?: T[];
}
const list = <T,>(value: T[] | ListEnvelope<T>) =>
  Array.isArray(value) ? value : (value.results ?? []);
const money = (value: string | number, currency = "USD") =>
  new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(value || 0));
const compact = (value: number) =>
  new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);

function AnalyticsPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connection, setConnection] = useState("");
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [metric, setMetric] = useState({
    platform: "",
    reach: "",
    engagement: "",
    clicks: "",
    conversions: "",
    spend: "",
  });
  const [revenue, setRevenue] = useState({
    source: "",
    external_event_id: "",
    campaign_name: "",
    amount: "",
    currency: "USD",
  });

  const load = useCallback(async () => {
    const [dashboard, accounts] = await Promise.all([
      apiGet<Dashboard>("/api/marketing/analytics/dashboard/"),
      apiGet<Connection[] | ListEnvelope<Connection>>("/api/marketing/social-accounts/"),
    ]);
    const supported = list(accounts).filter(
      (row) => row.status === "CONNECTED" && ["X", "YOUTUBE"].includes(row.platform),
    );
    setData(dashboard);
    setConnections(supported);
    setConnection((current) => current || supported[0]?.id || "");
  }, []);

  useEffect(() => {
    load().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "Analytics could not load."),
    );
  }, [load]);
  const totals = useMemo(
    () =>
      (data?.platform_perf ?? []).reduce(
        (all, row) => ({
          reach: all.reach + row.reach,
          engagement: all.engagement + row.engagement,
          clicks: all.clicks + row.clicks,
          conversions: all.conversions + row.conversions,
        }),
        { reach: 0, engagement: 0, clicks: 0, conversions: 0 },
      ),
    [data],
  );

  const sync = async () => {
    setWorking("sync");
    try {
      await apiPost("/api/marketing/analytics/performance/sync/", {
        social_connection: connection,
      });
      toast.success("Performance sync queued");
      await load();
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
        reach: Number(metric.reach || 0),
        engagement: Number(metric.engagement || 0),
        clicks: Number(metric.clicks || 0),
        conversions: Number(metric.conversions || 0),
        spend: metric.spend || "0",
        currency: "USD",
        source_payload: { entered_from: "analytics_console" },
      });
      setMetric({
        platform: "",
        reach: "",
        engagement: "",
        clicks: "",
        conversions: "",
        spend: "",
      });
      toast.success("Metrics imported with source lineage");
      await load();
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
      await load();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Revenue could not be recorded");
    } finally {
      setWorking("");
    }
  };

  if (error)
    return (
      <p className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        {error}
      </p>
    );
  if (!data)
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 8 }).map((_, index) => (
          <Skeleton key={index} className="h-28 rounded-xl" />
        ))}
      </div>
    );
  const freshness = data.summary.latest_observed_at
    ? new Date(data.summary.latest_observed_at).toLocaleString()
    : "No observations yet";

  return (
    <div>
      <PageHeader
        eyebrow="Growth engine"
        title="Performance & revenue"
        subtitle="Every number has a source. Follow content from generation through engagement, lead and revenue."
        backTo="/"
      />
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard
          label="Measured reach"
          value={compact(totals.reach)}
          icon={Eye}
          hint={freshness}
        />
        <StatCard label="Engagement" value={compact(totals.engagement)} icon={Activity} />
        <StatCard label="Conversions" value={compact(totals.conversions)} icon={Target} />
        <StatCard
          label="Leads"
          value={String(data.summary.lead_count)}
          icon={Users}
          hint={`${data.summary.converted_leads} converted`}
        />
        <StatCard
          label="Attributed revenue"
          value={money(data.summary.revenue)}
          icon={DollarSign}
        />
      </section>

      <div className="mt-8 grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(20rem,0.5fr)]">
        <section className="surface-card p-5">
          <SectionTitle
            label="Measured trend"
            title="Reach and engagement"
            description="Latest cumulative observation per published post — repeat syncs never double-count."
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
            disabled={!connection || working === "sync"}
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
        </section>
      </div>

      <Tabs defaultValue="platforms" className="mt-10">
        <TabsList className="flex h-auto flex-wrap justify-start">
          <TabsTrigger value="platforms">Platforms</TabsTrigger>
          <TabsTrigger value="sources">Source ledger</TabsTrigger>
          <TabsTrigger value="leads">Leads & revenue</TabsTrigger>
          <TabsTrigger value="intake">Data intake</TabsTrigger>
        </TabsList>
        <TabsContent value="platforms" className="mt-5">
          <section className="surface-card p-5">
            <SectionTitle
              label="Channel comparison"
              title="Performance by platform"
              description="Unavailable clicks or conversions remain zero and are never estimated."
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
        <TabsContent value="leads" className="mt-5">
          <div className="grid gap-5 xl:grid-cols-2">
            <section className="surface-card p-5">
              <SectionTitle
                label="Pipeline"
                title="Captured leads"
                description="Governed engagement and team intake."
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
                    <StatusBadge status={lead.status} />
                  </article>
                ))}
                {!data.leads.length && (
                  <p className="text-sm text-muted-foreground">No leads captured yet.</p>
                )}
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
              <td className="px-3 py-3">{row.reach.toLocaleString()}</td>
              <td className="px-3 py-3">{row.engagement.toLocaleString()}</td>
              <td className="px-3 py-3">{row.clicks.toLocaleString()}</td>
              <td className="px-3 py-3">{row.conversions.toLocaleString()}</td>
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
              Reach {row.reach.toLocaleString()} · {new Date(row.observed_at).toLocaleString()}
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
                <td className="px-4 py-3">{row.reach.toLocaleString()}</td>
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
        description="Use a platform export; Scaleezy stores an intake source rather than pretending it came from a live API."
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
