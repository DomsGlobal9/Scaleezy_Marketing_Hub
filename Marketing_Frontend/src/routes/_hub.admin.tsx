import { useCallback } from "react";
import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import { ShieldCheck } from "lucide-react";

import {
  AI_ADMIN_TABS,
  AIProvidersPanel,
  type AIAdminTab,
} from "@/components/marketing/ai-providers-panel";
import { PageHeader } from "@/components/marketing/primitives";
import { getSelectedWorkspace } from "@/lib/workspace";

export const Route = createFileRoute("/_hub/admin")({
  validateSearch: (search: Record<string, unknown>): { tab?: AIAdminTab } => {
    const tab = search["tab"];
    return typeof tab === "string" && (AI_ADMIN_TABS as readonly string[]).includes(tab)
      ? { tab: tab as AIAdminTab }
      : {};
  },
  beforeLoad: async ({ preload }) => {
    if (preload) return;

    const role = getSelectedWorkspace()?.role;

    if (role !== "OWNER" && role !== "ADMIN") {
      throw redirect({ to: "/", replace: true });
    }
  },
  head: () => ({
    meta: [
      { title: "Admin — Scaleezy Marketing Hub" },
      {
        name: "description",
        content: "Workspace administrator controls for AI providers and routing.",
      },
    ],
  }),
  component: AdminPage,
});

function AdminPage() {
  const navigate = useNavigate();
  const search = Route.useSearch();
  const activeTab: AIAdminTab = search.tab ?? "overview";
  const setTab = useCallback(
    (tab: AIAdminTab) => {
      void navigate({
        to: "/admin",
        search: tab === "overview" ? {} : { tab },
        replace: true,
      });
    },
    [navigate],
  );

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Workspace administration"
        title="Admin"
        subtitle="Configure provider credentials, capability routing, failover and redundancy for the selected client."
        backTo="/"
      />

      <section className="surface-card p-5 sm:p-6">
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-gold/30 bg-gold/8 px-4 py-3 text-sm">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-gold" />
          <p>
            Owner and workspace-admin access only. Product workflows request capabilities and never
            select a vendor directly.
          </p>
        </div>
        <AIProvidersPanel activeTab={activeTab} onTabChange={setTab} />
      </section>
    </div>
  );
}
