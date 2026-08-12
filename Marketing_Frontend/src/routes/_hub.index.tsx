import { useState, useEffect } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ArrowRight,
  BarChart3,
  CalendarClock,
  CircleDollarSign,
  Coins,
  Heart,
  Layers,
  Megaphone,
  Package,
  Plus,
  Repeat,
  Send,
  Share2,
  Sparkles,
  Users,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { PageHeader, SectionTitle, StatCard } from "@/components/marketing/primitives";

export const Route = createFileRoute("/_hub/")({
  head: () => ({
    meta: [
      { title: "Marketing Overview — Scaleezy Marketing Hub" },
      {
        name: "description",
        content:
          "Marketing KPIs, campaign intelligence and connected data sources for your apparel brand.",
      },
      { property: "og:title", content: "Marketing Overview — Scaleezy Marketing Hub" },
      {
        property: "og:description",
        content: "Turn customer intelligence into personalized campaigns and measurable growth.",
      },
    ],
  }),
  component: OverviewPage,
});

const ICON_MAP: Record<string, any> = {
  Megaphone,
  CalendarClock,
  Share2,
  Send,
  Users,
  Heart,
  Repeat,
  CircleDollarSign,
};

const SOURCES = [
  {
    name: "CRM",
    icon: Users,
    points: ["Customer behavior", "Purchase history", "Customer segmentation"],
  },
  {
    name: "Inventory",
    icon: Package,
    points: ["Stock availability", "Fast-moving products", "Dead-stock opportunities"],
  },
  {
    name: "Analytics",
    icon: BarChart3,
    points: ["Campaign performance", "Conversions", "Engagement"],
  },
  {
    name: "Finance",
    icon: Coins,
    points: ["Campaign ROI", "Revenue impact", "Budget intelligence"],
  },
];

const QUICK_ACTIONS = [
  {
    label: "Create Campaign",
    description: "Build an audience-led campaign",
    icon: Megaphone,
    to: "/publishing",
  },
  {
    label: "Publish Content",
    description: "Send approved assets live",
    icon: Send,
    to: "/publishing",
  },
  {
    label: "Connect Social Account",
    description: "Add a new channel securely",
    icon: Share2,
    to: "/accounts",
  },
  {
    label: "View Analytics",
    description: "Track reach and conversions",
    icon: BarChart3,
    to: "/analytics",
  },
] as const;

function OverviewPage() {
  const [kpis, setKpis] = useState<any[]>([]);

  useEffect(() => {
    fetch('http://localhost:8000/api/marketing/analytics/kpis/')
      .then(res => res.json())
      .then(data => {
        if (data.kpis) {
          const mappedKpis = data.kpis.map((kpi: any) => ({
            ...kpi,
            icon: ICON_MAP[kpi.icon] || Megaphone
          }));
          setKpis(mappedKpis);
        }
      })
      .catch(console.error);
  }, []);

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="AI-Driven Marketing Automation"
        subtitle="Turn customer intelligence into personalized campaigns and measurable growth."
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/publishing">
                <Plus className="size-4" /> Create Campaign
              </Link>
            </Button>
            <Button asChild>
              <Link to="/publishing">
                <Send className="size-4" /> Publish
              </Link>
            </Button>
          </>
        }
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {kpis.map((kpi) => (
          <StatCard key={kpi.label} {...kpi} />
        ))}
      </section>

      <section className="mt-10">
        <div className="surface-card overflow-hidden">
          <div className="border-b border-border px-6 py-5">
            <p className="label-eyebrow">Smart Marketing Intelligence</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight">
              Signals become personalized marketing action
            </h2>
          </div>
          <div className="grid gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <div>
              <div className="grid gap-2 sm:grid-cols-2">
                {[
                  "CRM & Behavior Data",
                  "Real-Time Inventory",
                  "Seasonality Trends",
                  "Geographic Insights",
                ].map((input) => (
                  <div
                    key={input}
                    className="rounded-xl border border-border bg-secondary/50 px-4 py-3 text-sm font-medium text-foreground"
                  >
                    {input}
                  </div>
                ))}
              </div>
              <div className="mt-4 flex flex-col items-center gap-3">
                <span className="text-muted-foreground">↓</span>
                <div className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-dark px-4 py-3 text-sm font-semibold tracking-[0.14em] text-brand-dark-foreground uppercase">
                  <Sparkles className="size-4 text-gold" /> Scaleezy Intelligence
                </div>
                <span className="text-muted-foreground">↓</span>
                <div className="w-full rounded-xl border border-primary/25 bg-primary/8 px-4 py-3 text-center text-sm font-semibold text-primary">
                  Personalized Marketing Action
                </div>
              </div>
            </div>
            <div className="rounded-xl border border-border bg-secondary/40 p-5">
              <p className="label-eyebrow">Example insight</p>
              <p className="mt-3 font-display text-lg leading-relaxed text-foreground">
                “Customers from Hyderabad who purchased bridal wear above ₹25,000 can be targeted
                with premium festive collection campaigns based on regional and pricing
                preferences.”
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                {["CRM-powered", "Inventory-aware", "Finance-informed"].map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mt-10">
        <SectionTitle
          label="Connected Intelligence"
          title="Marketing learns from every connected data source"
          description="These modules are read-only data inputs to the Marketing Hub."
        />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {SOURCES.map((source) => (
            <div key={source.name} className="surface-card p-5">
              <span className="grid size-9 place-items-center rounded-lg bg-gold/15 text-gold">
                <source.icon className="size-4.5" strokeWidth={1.75} />
              </span>
              <h3 className="mt-4 text-base font-semibold text-foreground">{source.name}</h3>
              <ul className="mt-3 space-y-1.5 text-sm text-muted-foreground">
                {source.points.map((point) => (
                  <li key={point} className="flex items-start gap-2">
                    <span className="mt-1.5 size-1 rounded-full bg-primary" />
                    {point}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="surface-card mt-4 p-6">
          <div className="grid items-center gap-6 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
            <ul className="space-y-2">
              {["CRM", "Inventory", "Analytics", "Finance", "Try-On"].map((mod) => (
                <li
                  key={mod}
                  className="flex items-center justify-between rounded-lg border border-border bg-secondary/50 px-3 py-2 text-sm text-foreground"
                >
                  {mod}
                  <ArrowRight className="size-4 text-gold" />
                </li>
              ))}
            </ul>
            <div className="hidden h-full w-px bg-border md:block" />
            <div className="rounded-xl bg-brand-dark px-5 py-6 text-center">
              <p className="font-display text-xl font-semibold text-brand-dark-foreground">
                Marketing Hub
              </p>
              <p className="mt-2 text-xs tracking-[0.16em] text-gold uppercase">
                Shared Intelligence Data Layer
              </p>
              <p className="mt-3 text-xs leading-relaxed text-brand-dark-foreground/70">
                Conceptual integration only — no other module UI is exposed here.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="mt-10">
        <SectionTitle label="Quick Actions" title="Move faster on today's marketing work" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {QUICK_ACTIONS.map((action) => (
            <Link
              key={action.label}
              to={action.to}
              className="surface-card group flex items-start gap-3 p-5 transition-transform duration-200 hover:-translate-y-0.5"
            >
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
                <action.icon className="size-4.5" strokeWidth={1.75} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-foreground">{action.label}</span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {action.description}
                </span>
              </span>
            </Link>
          ))}
        </div>
      </section>

      <section className="mt-10">
        <SectionTitle label="Campaigns" title="Active campaign performance" />
        <div className="grid gap-4 lg:grid-cols-2">
          {[
            {
              name: "Festive Premium Revival",
              audience: "High-value bridal buyers · Hyderabad, Chennai",
              reach: "14.2K",
              conv: "312",
              roi: "4.1x",
            },
            {
              name: "Monsoon Kurta Clearance",
              audience: "Repeat buyers · Slow-moving inventory",
              reach: "10.6K",
              conv: "196",
              roi: "3.2x",
            },
          ].map((c) => (
            <div key={c.name} className="surface-card p-5">
              <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
                <div className="min-w-0">
                  <h3 className="truncate text-base font-semibold text-foreground">{c.name}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{c.audience}</p>
                </div>
                <span className="shrink-0 rounded-full border border-success/25 bg-success/10 px-2.5 py-0.5 text-xs font-medium text-success">
                  Active
                </span>
              </div>
              <dl className="mt-5 grid grid-cols-3 gap-3">
                {[
                  ["Reach", c.reach],
                  ["Conversions", c.conv],
                  ["ROI", c.roi],
                ].map(([k, v]) => (
                  <div
                    key={k}
                    className="rounded-lg border border-border bg-secondary/50 px-3 py-2"
                  >
                    <dt className="text-[0.625rem] tracking-widest text-muted-foreground uppercase">
                      {k}
                    </dt>
                    <dd className="mt-1 text-lg font-semibold text-foreground">{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
          <Layers className="size-4 text-gold" />
          Campaign data blends CRM segments, inventory availability and finance ROI signals.
        </div>
      </section>
    </div>
  );
}
