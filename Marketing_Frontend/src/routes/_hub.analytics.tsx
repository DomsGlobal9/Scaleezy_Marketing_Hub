import { useState, useEffect } from "react";
import { createFileRoute } from "@tanstack/react-router";
import {
  BarChart3,
  CircleDollarSign,
  Eye,
  Heart,
  MousePointerClick,
  Send,
  Target,
} from "lucide-react";
import {
  Area,
  AreaChart,
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

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader, SectionTitle, StatCard } from "@/components/marketing/primitives";
import { apiFetch } from "@/lib/api";

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



const axis = {
  stroke: "var(--muted-foreground)",
  fontSize: 12,
  tickLine: false,
  axisLine: false,
};

// Long numeric ticks get dropped by recharts when they collide, which leaves a
// misleading non-uniform axis (0, 3000, 6000, 12000). Compact labels all fit.
const compact = (value: number) =>
  value >= 1000 ? `${(value / 1000).toFixed(value % 1000 === 0 ? 0 : 1)}k` : String(value);

const tooltipStyle = {
  contentStyle: {
    borderRadius: 12,
    border: "1px solid var(--border)",
    background: "var(--card)",
    fontSize: 12,
    color: "var(--foreground)",
  },
};

function ChartCard({
  title,
  source,
  children,
}: {
  title: string;
  source: string;
  children: React.ReactNode;
}) {
  return (
    <div className="surface-card p-5">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
        <h3 className="truncate text-sm font-semibold text-foreground">{title}</h3>
        <span className="shrink-0 rounded-full border border-border bg-secondary/60 px-2.5 py-0.5 text-xs text-muted-foreground">
          {source}
        </span>
      </div>
      <div className="mt-4 h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {children as React.ReactElement}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function AnalyticsPage() {
  const [trend, setTrend] = useState<any[]>([]);
  const [platformPerf, setPlatformPerf] = useState<any[]>([]);
  const [roi, setRoi] = useState<any[]>([]);

  useEffect(() => {
    apiFetch('/api/marketing/analytics/dashboard/')
      .then(res => res.json())
      .then(data => {
        if (data.trend) setTrend(data.trend);
        if (data.platform_perf) setPlatformPerf(data.platform_perf);
        if (data.roi) setRoi(data.roi);
      })
      .catch(console.error);
  }, []);

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="Analytics"
        subtitle="Understand how your marketing performs across connected channels."
        backTo="/"
      />

      <div className="mb-6 flex flex-wrap gap-2">
        {[
          { label: "Last 30 days", options: ["Last 7 days", "Last 30 days", "Last 90 days"] },
          {
            label: "All platforms",
            options: ["All platforms", "Instagram", "Facebook", "LinkedIn"],
          },
          {
            label: "All campaigns",
            options: ["All campaigns", "Festive Premium Revival", "Monsoon Kurta Clearance"],
          },
          {
            label: "All accounts",
            options: ["All accounts", "@scaleezyfashion", "Scaleezy Fashion India"],
          },
        ].map((filter) => (
          <Select key={filter.label} defaultValue={filter.label}>
            <SelectTrigger className="w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {filter.options.map((o) => (
                <SelectItem key={o} value={o}>
                  {o}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ))}
      </div>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total Reach" value="24.8K" icon={Eye} hint="Last 30 days" />
        <StatCard label="Engagement" value="1,686" icon={Heart} accent="gold" />
        <StatCard label="Clicks" value="4,396" icon={MousePointerClick} />
        <StatCard label="Conversions" value="264" icon={Target} accent="gold" />
        <StatCard label="Published Posts" value="126" icon={Send} />
        <StatCard label="Campaign Performance" value="+18.4%" icon={BarChart3} accent="gold" />
        <StatCard label="Marketing ROI" value="3.8x" icon={CircleDollarSign} />
        <StatCard label="Engagement Rate" value="6.8%" icon={Heart} accent="gold" />
      </section>

      <section className="mt-10 grid gap-4 xl:grid-cols-2">
        <ChartCard title="Reach over time" source="CRM-powered">
          <AreaChart data={trend}>
            <defs>
              <linearGradient id="reachFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--primary)" stopOpacity={0.35} />
                <stop offset="100%" stopColor="var(--primary)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="month" {...axis} />
            <YAxis {...axis} width={44} />
            <Tooltip {...tooltipStyle} />
            <Area
              type="monotone"
              dataKey="reach"
              stroke="var(--primary)"
              strokeWidth={2}
              fill="url(#reachFill)"
            />
          </AreaChart>
        </ChartCard>

        <ChartCard title="Engagement over time" source="Try-On influenced">
          <LineChart data={trend}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="month" {...axis} />
            <YAxis {...axis} width={44} />
            <Tooltip {...tooltipStyle} />
            <Line
              type="monotone"
              dataKey="engagement"
              stroke="var(--gold)"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ChartCard>

        <ChartCard title="Platform Performance" source="API data">
          <BarChart data={platformPerf}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="month" {...axis} />
            <YAxis {...axis} width={44} />
            <Tooltip {...tooltipStyle} />
            <Bar dataKey="posts" fill="var(--primary)" radius={[6, 6, 0, 0]} maxBarSize={34} />
          </BarChart>
        </ChartCard>

        <ChartCard title="Platform comparison" source="Inventory-powered">
          <BarChart data={platformPerf} layout="vertical" margin={{ left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
            <XAxis type="number" {...axis} tickFormatter={compact} />
            <YAxis type="category" dataKey="platform" {...axis} width={100} />
            <Tooltip {...tooltipStyle} />
            <Bar dataKey="reach" fill="var(--gold)" radius={[0, 6, 6, 0]} maxBarSize={18} />
          </BarChart>
        </ChartCard>

        <ChartCard title="Conversion trend" source="CRM-powered">
          <LineChart data={trend}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="month" {...axis} />
            <YAxis {...axis} width={44} />
            <Tooltip {...tooltipStyle} />
            <Line
              type="monotone"
              dataKey="conversions"
              stroke="var(--primary)"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ChartCard>

        <ChartCard title="Campaign ROI" source="Finance-informed">
          {/* Campaign names are too long to sit side by side on an X axis — they
              collided even at desktop width — so they run down the Y axis instead. */}
          <BarChart data={roi} layout="vertical" margin={{ left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
            <XAxis type="number" {...axis} />
            <YAxis type="category" dataKey="campaign" {...axis} width={130} />
            <Tooltip {...tooltipStyle} />
            <Bar dataKey="roi" fill="var(--primary)" radius={[0, 6, 6, 0]} maxBarSize={22} />
          </BarChart>
        </ChartCard>
      </section>

      <section className="mt-10">
        <SectionTitle
          label="Campaign Performance"
          title="Platform performance"
          description="CRM audience · Inventory availability · Marketing engagement · Revenue impact"
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
                {platformPerf.map((row) => (
                  <tr key={row.platform} className="border-b border-border/70 last:border-0">
                    <td className="px-4 py-3 font-medium text-foreground">{row.platform}</td>
                    <td className="px-4 py-3">{row.reach.toLocaleString("en-IN")}</td>
                    <td className="px-4 py-3">{row.engagement}</td>
                    <td className="px-4 py-3">{row.clicks}</td>
                    <td className="px-4 py-3">{row.conversions}</td>
                    <td className="px-4 py-3 font-semibold text-primary">{row.roi}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="divide-y divide-border lg:hidden">
            {platformPerf.map((row) => (
              <div key={row.platform} className="p-4">
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
                  <p className="truncate text-sm font-semibold text-foreground">{row.platform}</p>
                  <span className="text-sm font-semibold text-primary">{row.roi}</span>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  {[
                    ["Reach", row.reach.toLocaleString("en-IN")],
                    ["Engagement", String(row.engagement)],
                    ["Clicks", String(row.clicks)],
                    ["Conversions", String(row.conversions)],
                  ].map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-muted-foreground uppercase">{k}</dt>
                      <dd className="text-foreground">{v}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
