/**
 * Platform admins — who can open this console.
 *
 * Grant by username with a note saying why; revoke keeps the row (with its
 * revoked_at) so the history of who could act on the platform is never lost.
 */
import { createFileRoute } from "@tanstack/react-router";
import { RefreshCw, ShieldCheck, ShieldOff, UserPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ConfirmDialog,
  ErrorNote,
  Panel,
  PlatformPageHeader,
  StatusPill,
  type ConfirmRequest,
} from "@/components/platform/shared";
import {
  errorText,
  fetchPlatformAdmins,
  formatDateTime,
  grantPlatformAdmin,
  revokePlatformAdmin,
  type PlatformAdminRow,
} from "@/lib/platform";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/platform/admins")({
  head: () => ({ meta: [{ title: "Admins — Scaleezy Platform Console" }] }),
  component: AdminsPage,
});

function AdminsPage() {
  const [admins, setAdmins] = useState<PlatformAdminRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAdmins(await fetchPlatformAdmins());
    } catch (e: unknown) {
      setError(errorText(e, "Could not load platform admins."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const grant = () => {
    const who = username.trim();
    if (!who) return;
    setConfirm({
      title: `Grant platform admin to ${who}?`,
      description:
        "They will be able to approve clients, change limits, suspend and archive any workspace, and author standards. Every action they take is audited under their name.",
      confirmLabel: "Grant",
      run: async () => {
        await grantPlatformAdmin(who, note.trim());
        toast.success(`${who} is now a platform admin.`);
        setUsername("");
        setNote("");
        await load();
      },
    });
  };

  const revoke = (row: PlatformAdminRow) =>
    setConfirm({
      title: `Revoke platform admin from ${row.username}?`,
      description: "They lose the console immediately. Their audit history stays.",
      confirmLabel: "Revoke",
      destructive: true,
      run: async () => {
        await revokePlatformAdmin(row.user_id);
        toast.success(`${row.username} revoked.`);
        await load();
      },
    });

  const active = admins?.filter((a) => a.is_active) ?? [];
  const revoked = admins?.filter((a) => !a.is_active) ?? [];

  return (
    <div>
      <PlatformPageHeader
        eyebrow="Platform"
        title="Admins"
        subtitle="Who can open this console. Membership is a live database check on every request, never a cached claim."
        actions={
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn("size-4", loading && "animate-spin")} /> Refresh
          </Button>
        }
      />

      <ErrorNote message={error} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-6">
          <Panel title="Active admins" description={`${active.length} with access right now.`}>
            {loading && !admins ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 rounded-lg" />
                ))}
              </div>
            ) : active.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No active platform admins were returned.
              </p>
            ) : (
              <AdminTable rows={active} onRevoke={revoke} />
            )}
          </Panel>

          {revoked.length ? (
            <Panel title="Revoked" description="Kept for the record.">
              <AdminTable rows={revoked} />
            </Panel>
          ) : null}
        </div>

        <Panel
          title="Grant access"
          description="By username. A note says why, for whoever reads the audit log later."
        >
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              grant();
            }}
          >
            <div>
              <Label htmlFor="grant-username" className="text-xs tracking-wide uppercase">
                Username
              </Label>
              <Input
                id="grant-username"
                className="mt-1.5"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="off"
              />
            </div>
            <div>
              <Label htmlFor="grant-note" className="text-xs tracking-wide uppercase">
                Note
              </Label>
              <Input
                id="grant-note"
                className="mt-1.5"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. Client success lead"
              />
            </div>
            <Button type="submit" className="w-full" disabled={!username.trim()}>
              <UserPlus className="size-4" /> Grant platform admin…
            </Button>
          </form>
        </Panel>
      </div>

      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </div>
  );
}

function AdminTable({
  rows,
  onRevoke,
}: {
  rows: PlatformAdminRow[];
  onRevoke?: (row: PlatformAdminRow) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted/50 text-[0.625rem] tracking-wide text-muted-foreground uppercase">
          <tr>
            <th className="px-3 py-2 font-semibold">User</th>
            <th className="px-3 py-2 font-semibold">Note</th>
            <th className="px-3 py-2 font-semibold">Granted</th>
            <th className="px-3 py-2 font-semibold">Status</th>
            {onRevoke ? <th className="px-3 py-2 font-semibold" /> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.user_id)} className="border-t border-border align-top">
              <td className="px-3 py-2">
                <p className="flex items-center gap-1.5 font-medium text-foreground">
                  <ShieldCheck className="size-3.5 text-slate-500" /> {row.username}
                </p>
                <p className="text-xs text-muted-foreground">{row.email || "—"}</p>
              </td>
              <td className="px-3 py-2 text-xs text-muted-foreground">{row.note || "—"}</td>
              <td className="px-3 py-2 text-xs">
                <p>{formatDateTime(row.granted_at)}</p>
                <p className="text-muted-foreground">by {row.granted_by || "—"}</p>
                {row.revoked_at ? (
                  <p className="text-muted-foreground">revoked {formatDateTime(row.revoked_at)}</p>
                ) : null}
              </td>
              <td className="px-3 py-2">
                <StatusPill value={row.is_active ? "ACTIVE" : "REVOKED"} />
              </td>
              {onRevoke ? (
                <td className="px-3 py-2 text-right">
                  <Button size="sm" variant="outline" onClick={() => onRevoke(row)}>
                    <ShieldOff className="size-3.5" /> Revoke
                  </Button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
