import { createFileRoute, redirect } from "@tanstack/react-router";
import { ShieldCheck } from "lucide-react";

import { AIProvidersPanel } from "@/components/marketing/ai-providers-panel";
import { PageHeader } from "@/components/marketing/primitives";
import { api } from "@/lib/api";
import { readActiveWorkspaceId } from "@/lib/workspace";

interface CurrentUser {
  memberships: Array<{
    workspace_id: string;
    role: string;
  }>;
}

export const Route = createFileRoute("/_hub/admin")({
  beforeLoad: async ({ preload }) => {
    if (preload) return;

    const activeWorkspaceId = readActiveWorkspaceId();
    const user = await api<CurrentUser>("/api/auth/me/");
    const role = user.memberships.find(
      (membership) => membership.workspace_id === activeWorkspaceId,
    )?.role;

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
  return (
    <div>
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
        <AIProvidersPanel />
      </section>
    </div>
  );
}
