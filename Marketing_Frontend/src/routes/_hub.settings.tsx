/**
 * Settings — workspace, account and security configuration only.
 *
 * Brand identity lives in Brand Master. Everything here reads and writes a
 * real backend record: the workspace row, the billing allowance and the
 * publishing audit trail. AI provider credentials and routing live only in
 * the guarded Admin module. Panels whose controls
 * saved nowhere (publishing defaults, notifications, session toggles, the
 * static permission matrix) were removed rather than left as decoration.
 */
import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Loader2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader, StatusBadge } from "@/components/marketing/primitives";
import { UsagePanel } from "@/components/marketing/usage-panel";
import { api, apiFetch } from "@/lib/api";

export const Route = createFileRoute("/_hub/settings")({
  head: () => ({
    meta: [
      { title: "Settings — Scaleezy Marketing Hub" },
      { name: "description", content: "Workspace, plan usage and security." },
    ],
  }),
  component: SettingsPage,
});

interface WorkspaceDto {
  id: string;
  workspace_name: string;
}

interface AuditRow {
  id: string;
  date: string;
  user: string;
  platform: string;
  account: string;
  action: string;
  result: string;
  error?: string | null;
}

interface Membership {
  workspace?: string;
  workspace_id?: string;
  workspace_name?: string;
  role?: string;
}

interface Me {
  username: string;
  email: string;
  memberships: Membership[];
}

function Panel({
  label,
  title,
  children,
}: {
  label: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="surface-card p-5 sm:p-6">
      <p className="label-eyebrow">{label}</p>
      <h2 className="mt-1 mb-5 text-lg font-semibold tracking-tight">{title}</h2>
      {children}
    </section>
  );
}

const ROLE_LABEL: Record<string, string> = {
  OWNER: "Owner",
  ADMIN: "Workspace admin",
  MANAGER: "Marketing manager",
  EDITOR: "Marketing executive",
  VIEWER: "Viewer",
};

function SettingsPage() {
  const [workspace, setWorkspace] = useState<WorkspaceDto | null>(null);
  const [name, setName] = useState("");
  const [auditLogs, setAuditLogs] = useState<AuditRow[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/marketing/settings/")
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return;
        if (data.workspace) {
          setWorkspace(data.workspace);
          setName(data.workspace.workspace_name ?? "");
        }
        if (Array.isArray(data.audit_logs)) setAuditLogs(data.audit_logs);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load settings.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    api<Me>("/api/auth/me/")
      .then((data) => {
        if (!cancelled) setMe(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const myRole = me?.memberships.find(
    (m) => (m.workspace_id ?? m.workspace) === workspace?.id,
  )?.role;
  const canEditWorkspace = myRole === "ADMIN" || myRole === "OWNER";
  const dirty = workspace !== null && name.trim() !== workspace.workspace_name;

  const save = async () => {
    if (!workspace) return;
    setSaving(true);
    setError(null);
    try {
      const res = await apiFetch("/api/marketing/settings/", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: { workspace_name: name.trim() } }),
      });
      const json = await res.json().catch(() => null);
      if (!res.ok || json?.success === false) {
        throw new Error(json?.error?.message || json?.message || `Save failed (${res.status}).`);
      }
      setWorkspace(json.workspace);
      setName(json.workspace.workspace_name ?? "");
      toast.success("Workspace saved.");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Could not save the workspace.";
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="Settings"
        subtitle="Workspace, plan usage and security. Brand identity and intelligence live in Brand Master."
        backTo="/"
      />

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel label="General" title="Workspace">
          {loading ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading…
            </p>
          ) : (
            <div className="grid gap-4">
              <div>
                <Label className="text-xs tracking-wide uppercase">Workspace name</Label>
                <Input
                  className="mt-1.5"
                  value={name}
                  disabled={!canEditWorkspace && myRole !== undefined}
                  onChange={(e) => setName(e.target.value)}
                />
                <p className="mt-1.5 text-xs text-muted-foreground">
                  {canEditWorkspace || myRole === undefined
                    ? "Shown across the hub and used as the default brand name."
                    : "Only a workspace admin can rename the workspace."}
                </p>
              </div>
              {error ? <p className="text-sm text-destructive">{error}</p> : null}
              <div>
                <Button onClick={save} disabled={!dirty || saving || !name.trim()}>
                  {saving ? <Loader2 className="size-4 animate-spin" /> : null} Save changes
                </Button>
              </div>
            </div>
          )}
        </Panel>

        <Panel label="Access" title="Your access">
          {me ? (
            <div className="space-y-3 text-sm">
              <p className="text-foreground">
                Signed in as <span className="font-medium">{me.username}</span>
                {me.email ? <span className="text-muted-foreground"> · {me.email}</span> : null}
              </p>
              <ul className="space-y-2">
                {me.memberships.map((m, i) => (
                  <li
                    key={`${m.workspace_id ?? m.workspace ?? i}`}
                    className="flex items-center justify-between gap-3 rounded-xl border border-border px-4 py-3"
                  >
                    <span className="truncate">{m.workspace_name ?? "Workspace"}</span>
                    <span className="shrink-0 rounded-full border border-border bg-secondary/60 px-2.5 py-0.5 text-xs">
                      {ROLE_LABEL[m.role ?? ""] ?? m.role ?? "member"}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-muted-foreground">
                Roles are managed by a workspace admin. Viewers read, executives create and edit,
                managers approve and publish, admins configure.
              </p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Loading…</p>
          )}
        </Panel>

        <Panel label="Plan" title="Usage this period">
          <UsagePanel />
        </Panel>

      </div>

      <div className="mt-6">
        <Panel label="Security" title="Tokens & publishing audit trail">
          <div className="flex items-start gap-2 rounded-xl border border-gold/30 bg-gold/8 px-4 py-3 text-sm">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-gold" />
            <p>
              OAuth tokens are encrypted at rest on the server, never exposed to the browser and
              masked in logs. Manage connected accounts under Social Media Accounts.
            </p>
          </div>
          <div className="mt-4 rounded-xl border border-border px-4 py-3">
            <p className="text-xs tracking-wide text-muted-foreground uppercase">
              Recent publishing events
            </p>
            {auditLogs.length === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">No events recorded yet.</p>
            ) : (
              <ul className="mt-2 space-y-2 text-sm">
                {auditLogs.slice(0, 10).map((log) => (
                  <li
                    key={log.id}
                    className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2"
                  >
                    <span className="min-w-0 truncate text-foreground">
                      {new Date(log.date).toLocaleString()} · {log.platform} · {log.action}
                      {log.account ? ` · ${log.account}` : ""}
                    </span>
                    <StatusBadge
                      status={log.result}
                      tone={log.result === "Success" ? "success" : "danger"}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
