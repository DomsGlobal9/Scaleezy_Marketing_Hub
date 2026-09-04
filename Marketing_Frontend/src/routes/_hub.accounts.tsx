/**
 * Social Media Accounts — connections the backend actually holds.
 *
 * Every row comes from /social-accounts/; every button calls the endpoint
 * that owns the action (OAuth connect, verify, PATCH publishing/default,
 * disconnect). Controls the backend has no persistence for — per-account
 * hours, limits, comment access — were removed rather than left saving into
 * React state.
 */
import { createFileRoute } from "@tanstack/react-router";
import {
  AlertTriangle,
  CheckCircle2,
  Link2,
  Loader2,
  PauseCircle,
  PlayCircle,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Unplug,
} from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, apiFetch, apiPost } from "@/lib/api";
import { readSelectedWorkspaceId, useWorkspaces } from "@/lib/workspace";
import {
  EmptyState,
  PageHeader,
  PlatformIcon,
  SectionTitle,
  StatusBadge,
} from "@/components/marketing/primitives";
import { PLATFORMS, type PlatformMeta } from "@/lib/marketing-data";

export const Route = createFileRoute("/_hub/accounts")({
  head: () => ({
    meta: [
      { title: "Social Media Accounts — Scaleezy Marketing Hub" },
      {
        name: "description",
        content: "Securely connect and manage the social accounts Scaleezy publishes to.",
      },
    ],
  }),
  component: AccountsPage,
});

/** A SocialConnection row as the API returns it. */
interface Connection {
  id: string;
  platform: string;
  account_type: string | null;
  external_account_id: string;
  account_name: string;
  username: string | null;
  profile_url: string | null;
  profile_image_url: string | null;
  status: string;
  publishing_enabled: boolean;
  is_default_account: boolean;
  last_verified_at: string | null;
  last_published_at: string | null;
  last_error: string | null;
  connected_at: string;
  reauthorization_required: boolean;
}

interface AuditRow {
  id: string;
  date: string;
  user: string;
  platform: string;
  account: string;
  action: string;
  previous_state: string | null;
  next_state: string | null;
  result: string;
  error: string | null;
}

const isNullableString = (value: unknown): value is string | null =>
  value === null || typeof value === "string";

function isConnection(value: unknown): value is Connection {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row["id"] === "string" &&
    typeof row["platform"] === "string" &&
    isNullableString(row["account_type"]) &&
    typeof row["external_account_id"] === "string" &&
    typeof row["account_name"] === "string" &&
    isNullableString(row["username"]) &&
    isNullableString(row["profile_url"]) &&
    isNullableString(row["profile_image_url"]) &&
    typeof row["status"] === "string" &&
    typeof row["publishing_enabled"] === "boolean" &&
    typeof row["is_default_account"] === "boolean" &&
    isNullableString(row["last_verified_at"]) &&
    isNullableString(row["last_published_at"]) &&
    isNullableString(row["last_error"]) &&
    typeof row["connected_at"] === "string" &&
    typeof row["reauthorization_required"] === "boolean"
  );
}

function parseConnections(payload: unknown): Connection[] {
  const rows = Array.isArray(payload)
    ? payload
    : payload &&
        typeof payload === "object" &&
        Array.isArray((payload as { results?: unknown }).results)
      ? (payload as { results: unknown[] }).results
      : null;

  if (!rows || !rows.every(isConnection)) {
    throw new Error("The accounts service returned an invalid account list.");
  }
  return rows;
}

const ATTENTION = new Set([
  "TOKEN_EXPIRED",
  "REAUTHORIZATION_REQUIRED",
  "PERMISSION_MISSING",
  "REVOKED",
  "CONNECTION_FAILED",
]);

const statusLabel = (status: string) =>
  status
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

const platformId = (platform: string) => platform.toLowerCase().replaceAll("_", "-");

const fmtDate = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString() : "—";

/** The workspace the user is actually looking at.
 *
 * This used to take the first row of /workspaces/, which is only correct for
 * someone with exactly one client. The id is bound into the OAuth state and
 * decides which workspace the resulting connection lands in, so guessing it
 * wrong connects a customer's social account to a different client. */
function workspaceId(): string | null {
  return readSelectedWorkspaceId();
}

/** Starts the official OAuth flow; the browser leaves for the platform. */
async function startOAuth(platform: string) {
  const wsId = workspaceId();
  if (!wsId) throw new Error("Select a client before connecting an account.");
  const data = await apiPost<{ authorization_url?: string }>(
    "/api/marketing/social-accounts/connect/",
    { workspace_id: wsId, platform: platform.toUpperCase().replaceAll("-", "_") },
  );
  if (!data?.authorization_url)
    throw new Error("The platform did not return an authorization URL.");
  window.location.href = data.authorization_url;
}

function AccountsPage() {
  const [accounts, setAccounts] = useState<Connection[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [connectPlatform, setConnectPlatform] = useState<PlatformMeta | null>(null);
  const [manageId, setManageId] = useState<string | null>(null);
  const [disconnectTarget, setDisconnectTarget] = useState<Connection | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const platformChooserRef = useRef<HTMLElement>(null);

  // Account configuration is an ADMIN concern. Keep an unresolved role
  // fail-closed while workspace membership is still loading or failed.
  const workspaceState = useWorkspaces();
  const activeRole = workspaceState.workspaces.find(
    (workspace) => workspace.id === workspaceState.selectedId,
  )?.role;
  const canManageAccounts = activeRole === "ADMIN" || activeRole === "OWNER";

  const load = useCallback(async () => {
    setLoadingAccounts(true);
    setLoadError(null);
    try {
      const rows = await api<unknown>("/api/marketing/social-accounts/");
      setAccounts(parseConnections(rows));
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Could not load accounts.");
    } finally {
      setLoadingAccounts(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const list = useMemo(() => accounts ?? [], [accounts]);
  const summary = useMemo(
    () => ({
      connected: list.filter((a) => a.status === "CONNECTED").length,
      enabled: list.filter((a) => a.publishing_enabled && a.status === "CONNECTED").length,
      attention: list.filter((a) => ATTENTION.has(a.status) || a.reauthorization_required).length,
      disabled: list.filter((a) => !a.publishing_enabled && a.status === "CONNECTED").length,
    }),
    [list],
  );

  const requireAccountAdmin = () => {
    if (canManageAccounts) return true;
    toast.error("Only a workspace owner or admin can manage social accounts.");
    return false;
  };

  const patch = async (
    account: Connection,
    body: Partial<Pick<Connection, "publishing_enabled">>,
  ) => {
    if (!requireAccountAdmin()) return;
    setBusy(account.id);
    try {
      await api(`/api/marketing/social-accounts/${account.id}/`, { method: "PATCH", body });
      await load();
      toast.success("Saved.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setBusy(null);
    }
  };

  const verify = async (account: Connection) => {
    if (!requireAccountAdmin()) return;
    setBusy(account.id);
    try {
      await apiPost(`/api/marketing/social-accounts/${account.id}/verify/`, {});
      toast.success("Connection verified.");
    } catch (e) {
      toast.error(
        e instanceof Error
          ? e.message
          : "Verification is unavailable. Retry to check this account.",
      );
    } finally {
      await load();
      setBusy(null);
    }
  };

  const reconnect = async (account: Connection) => {
    if (!requireAccountAdmin()) return;
    setBusy(account.id);
    try {
      await startOAuth(account.platform);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not start reconnection.");
      setBusy(null);
    }
  };

  const disconnect = async (account: Connection) => {
    if (!requireAccountAdmin()) return;
    setBusy(account.id);
    try {
      const result = await apiPost<{ remote_revocation_confirmed: boolean }>(
        `/api/marketing/social-accounts/${account.id}/disconnect/`,
        {},
      );
      if (result.remote_revocation_confirmed) {
        toast.success("Account disconnected and remote access revoked.");
      } else {
        toast.warning(
          "Disconnected from Scaleezy. Remote revocation was not confirmed; remove access in the social platform's settings if needed.",
        );
      }
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to disconnect.");
    } finally {
      setBusy(null);
      setDisconnectTarget(null);
    }
  };

  const manageAccount = list.find((a) => a.id === manageId) ?? null;

  const showPlatformChooser = () => {
    platformChooserRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    platformChooserRef.current?.focus({ preventScroll: true });
  };

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="Social Media Accounts"
        subtitle="Connect your social accounts securely and publish approved marketing content from Scaleezy."
        backTo="/"
        actions={
          <Button onClick={showPlatformChooser}>
            <Plus className="size-4" /> Connect Account
          </Button>
        }
      />

      <div className="mb-4 flex items-start gap-2 rounded-xl border border-gold/30 bg-gold/8 px-4 py-3 text-sm text-foreground">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-gold" />
        <p>
          Scaleezy never asks for social passwords or tokens — authorization always happens on the
          official platform via secure OAuth.
        </p>
      </div>

      <section className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {[
          { label: "Connected Accounts", value: summary.connected },
          { label: "Publishing Enabled", value: summary.enabled },
          { label: "Needs Attention", value: summary.attention },
          { label: "Publishing Disabled", value: summary.disabled },
        ].map((item) => (
          <div key={item.label} className="surface-card p-5">
            <p className="text-2xl font-semibold text-foreground">
              {accounts === null ? "—" : item.value}
            </p>
            <p className="mt-1 text-xs tracking-wide text-muted-foreground uppercase">
              {item.label}
            </p>
          </div>
        ))}
      </section>

      <section className="mt-10" aria-busy={loadingAccounts}>
        <SectionTitle
          label="Connected"
          title="Your connected accounts"
          description="Account details are retrieved automatically after authorization."
        />
        {loadError ? (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          >
            <p>
              {loadError}
              {accounts !== null ? " The last loaded account list is still shown." : ""}
            </p>
            <Button size="sm" variant="outline" onClick={() => void load()}>
              <RefreshCw className="size-4" /> Try again
            </Button>
          </div>
        ) : null}
        {loadingAccounts && accounts !== null ? (
          <p role="status" aria-live="polite" className="py-3 text-sm text-muted-foreground">
            Refreshing accounts…
          </p>
        ) : null}
        {accounts === null ? (
          loadingAccounts ? (
            <p
              role="status"
              aria-live="polite"
              className="flex items-center gap-2 py-8 text-sm text-muted-foreground"
            >
              <Loader2 className="size-4 animate-spin" /> Loading accounts…
            </p>
          ) : null
        ) : list.length === 0 ? (
          <EmptyState
            icon={Link2}
            title="No accounts connected"
            description="Connect a channel below. Publishing needs at least one connected account."
          />
        ) : (
          <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
            {list.map((account) => {
              const needsReauth =
                ATTENTION.has(account.status) ||
                account.reauthorization_required ||
                account.status === "DISCONNECTED";
              return (
                <article key={account.id} className="surface-card p-5">
                  <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3">
                    <PlatformIcon platform={platformId(account.platform)} />
                    <div className="min-w-0">
                      <h3 className="truncate text-base font-semibold text-foreground">
                        {account.account_name}
                      </h3>
                      <p className="truncate text-sm text-muted-foreground">
                        {account.username
                          ? `@${account.username.replace(/^@/, "")}`
                          : account.external_account_id}
                        {account.account_type ? ` · ${account.account_type}` : ""}
                      </p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <StatusBadge status={statusLabel(account.status)} />
                        {account.is_default_account ? (
                          <span className="rounded-full border border-border bg-secondary/60 px-2 py-0.5 text-xs text-muted-foreground">
                            Default
                          </span>
                        ) : null}
                        {!account.publishing_enabled && account.status === "CONNECTED" ? (
                          <span className="rounded-full border border-border bg-secondary/60 px-2 py-0.5 text-xs text-muted-foreground">
                            Publishing disabled
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </div>

                  <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                    {[
                      ["Connected on", fmtDate(account.connected_at)],
                      ["Last verified", fmtDate(account.last_verified_at)],
                      ["Last published", fmtDate(account.last_published_at)],
                      ["Account ID", account.external_account_id],
                    ].map(([k, v]) => (
                      <div key={k} className="min-w-0">
                        <dt className="tracking-wide text-muted-foreground uppercase">{k}</dt>
                        <dd className="truncate font-medium text-foreground">{v}</dd>
                      </div>
                    ))}
                  </dl>

                  {account.last_error ? (
                    <p
                      role="status"
                      className="mt-3 flex items-start gap-2 rounded-lg border border-gold/30 bg-gold/8 px-3 py-2 text-xs text-foreground"
                    >
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-gold" />
                      {account.last_error}
                    </p>
                  ) : null}

                  <div className="mt-5 flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" onClick={() => setManageId(account.id)}>
                      <Settings2 className="size-4" /> Manage
                    </Button>
                    {canManageAccounts ? (
                      <>
                        {needsReauth ? (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy === account.id}
                            onClick={() => reconnect(account)}
                          >
                            <RefreshCw className="size-4" /> Reconnect
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy === account.id}
                            onClick={() => verify(account)}
                          >
                            <RefreshCw className="size-4" /> Verify
                          </Button>
                        )}
                        {account.status === "CONNECTED" ? (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy === account.id}
                            onClick={() =>
                              patch(account, { publishing_enabled: !account.publishing_enabled })
                            }
                          >
                            {account.publishing_enabled ? (
                              <PauseCircle className="size-4" />
                            ) : (
                              <PlayCircle className="size-4" />
                            )}
                            {account.publishing_enabled
                              ? "Disable publishing"
                              : "Enable publishing"}
                          </Button>
                        ) : null}
                        {account.status !== "DISCONNECTED" ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-destructive hover:text-destructive"
                            onClick={() => setDisconnectTarget(account)}
                          >
                            <Unplug className="size-4" /> Disconnect
                          </Button>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section
        ref={platformChooserRef}
        tabIndex={-1}
        aria-label="Available platforms"
        className="mt-10 focus:outline-none"
      >
        <SectionTitle
          label="Available Platforms"
          title="Add another channel"
          description="Authorization uses official platform OAuth. Scaleezy never stores your password."
        />
        {!canManageAccounts ? (
          <p className="mb-4 text-sm text-muted-foreground">
            {activeRole == null
              ? "Account controls are unavailable until your workspace role is confirmed."
              : "Only a workspace owner or admin can connect social accounts."}
          </p>
        ) : null}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {PLATFORMS.map((platform) => {
            const connectedCount = list.filter(
              (a) => platformId(a.platform) === platform.id && a.status !== "DISCONNECTED",
            ).length;
            const accountStateKnown = accounts !== null;
            return (
              <div key={platform.id} className="surface-card p-5">
                <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3">
                  <PlatformIcon platform={platform.id} />
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-foreground">
                      {platform.name}
                    </h3>
                    <p className="truncate text-xs text-muted-foreground">{platform.accountType}</p>
                  </div>
                </div>
                <div className="mt-4 flex items-center justify-between gap-3">
                  <StatusBadge
                    status={
                      !platform.supported
                        ? "Platform Unavailable"
                        : !accountStateKnown
                          ? "Status Unavailable"
                          : connectedCount > 0
                            ? "Connected"
                            : "Not Connected"
                    }
                  />
                  {platform.supported ? (
                    <Button
                      size="sm"
                      disabled={!canManageAccounts || !accountStateKnown || !!loadError}
                      onClick={() => setConnectPlatform(platform)}
                    >
                      <Link2 className="size-4" />
                      {connectedCount > 0 ? "Add Another" : "Connect Account"}
                    </Button>
                  ) : (
                    <span className="text-xs text-muted-foreground">Not available yet</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="mt-10">
        <SectionTitle
          label="Account Activity"
          title="Audit log"
          description="Publishing and connection events recorded for this workspace."
        />
        <AuditTable />
      </section>

      <ConnectDialog
        platform={connectPlatform}
        canManageAccounts={canManageAccounts}
        onClose={() => setConnectPlatform(null)}
      />

      <ManageSheet
        account={manageAccount}
        busy={busy === manageAccount?.id}
        canManageAccounts={canManageAccounts}
        onClose={() => setManageId(null)}
        onPatch={(body) => manageAccount && patch(manageAccount, body)}
        onVerify={() => manageAccount && verify(manageAccount)}
        onReconnect={() => manageAccount && reconnect(manageAccount)}
        onDisconnect={() => {
          if (manageAccount) setDisconnectTarget(manageAccount);
          setManageId(null);
        }}
      />

      <AlertDialog open={!!disconnectTarget} onOpenChange={(o) => !o && setDisconnectTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Disconnect {disconnectTarget?.account_name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Disconnecting this account stops future publishing from Scaleezy and clears its
              tokens. You can reconnect later.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={!!busy || !canManageAccounts}
              onClick={(e) => {
                e.preventDefault();
                if (disconnectTarget) void disconnect(disconnectTarget);
              }}
            >
              Disconnect
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function AuditTable() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [platform, setPlatform] = useState("all");
  const [user, setUser] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const platformFilterId = useId();
  const userFilterId = useId();

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/marketing/settings/")
      .then((res) => {
        // apiFetch resolves on HTTP errors too; a failed request must show as
        // a failure, not as "no events recorded".
        if (!res.ok) throw new Error(`Request failed (${res.status})`);
        return res.json();
      })
      .then((data) => {
        if (!cancelled) {
          setRows(Array.isArray(data?.audit_logs) ? data.audit_logs : []);
          setLoadError(null);
        }
      })
      .catch(() => {
        if (!cancelled) setLoadError("Could not load the audit log.");
      });
    return () => {
      cancelled = true;
    };
  }, [loadAttempt]);

  const retry = () => {
    setRows(null);
    setLoadError(null);
    setLoadAttempt((attempt) => attempt + 1);
  };

  const platforms = useMemo(
    () => Array.from(new Set((rows ?? []).map((r) => r.platform).filter(Boolean))).sort(),
    [rows],
  );
  const query = user.trim().toLowerCase();
  const visible = (rows ?? []).filter(
    (r) =>
      (platform === "all" || r.platform === platform) &&
      (!query || (r.user ?? "").toLowerCase().includes(query)),
  );

  return (
    <div className="surface-card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <Label htmlFor={platformFilterId} className="sr-only">
          Filter audit log by platform
        </Label>
        <Select value={platform} onValueChange={setPlatform}>
          <SelectTrigger id={platformFilterId} className="w-[180px]">
            <SelectValue placeholder="Platform" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All platforms</SelectItem>
            {platforms.map((p) => (
              <SelectItem key={p} value={p}>
                {p}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Label htmlFor={userFilterId} className="sr-only">
          Filter audit log by user
        </Label>
        <Input
          id={userFilterId}
          placeholder="Filter by user"
          className="w-[180px]"
          value={user}
          onChange={(e) => setUser(e.target.value)}
        />
      </div>

      {loadError ? (
        <div role="alert" className="px-4 py-10 text-center text-sm text-destructive">
          <p>{loadError}</p>
          <Button className="mt-3" size="sm" variant="outline" onClick={retry}>
            <RefreshCw className="size-4" /> Try again
          </Button>
        </div>
      ) : rows === null ? (
        <p
          role="status"
          aria-live="polite"
          className="px-4 py-10 text-center text-sm text-muted-foreground"
        >
          Loading audit log…
        </p>
      ) : visible.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-muted-foreground">
          {rows.length === 0 ? "No events recorded yet." : "No audit events match these filters."}
        </p>
      ) : null}

      {visible.length > 0 ? (
        <>
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full text-sm">
              <caption className="sr-only">Social account activity for this workspace</caption>
              <thead>
                <tr className="border-b border-border text-left text-xs tracking-wide text-muted-foreground uppercase">
                  {[
                    "Date & Time",
                    "User",
                    "Platform",
                    "Account",
                    "Action",
                    "Previous",
                    "New",
                    "Result",
                    "Error",
                  ].map((h) => (
                    <th key={h} className="px-4 py-3 font-medium whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr key={row.id} className="border-b border-border/70 last:border-0">
                    <td className="px-4 py-3 whitespace-nowrap">{fmtDate(row.date)}</td>
                    <td className="px-4 py-3 whitespace-nowrap">{row.user}</td>
                    <td className="px-4 py-3">{row.platform}</td>
                    <td className="px-4 py-3">{row.account}</td>
                    <td className="px-4 py-3">{row.action}</td>
                    <td className="px-4 py-3 text-muted-foreground">{row.previous_state ?? "—"}</td>
                    <td className="px-4 py-3">{row.next_state ?? "—"}</td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        status={row.result}
                        tone={row.result === "Success" ? "success" : "danger"}
                      />
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{row.error ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="divide-y divide-border lg:hidden">
            {visible.map((row) => (
              <div key={row.id} className="p-4">
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
                  <p className="min-w-0 truncate text-sm font-medium text-foreground">
                    {row.action}
                  </p>
                  <StatusBadge
                    status={row.result}
                    tone={row.result === "Success" ? "success" : "danger"}
                  />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{fmtDate(row.date)}</p>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  {[
                    ["User", row.user],
                    ["Platform", row.platform],
                    ["Account", row.account],
                  ].map(([k, v]) => (
                    <div key={k} className="min-w-0">
                      <dt className="text-muted-foreground uppercase">{k}</dt>
                      <dd className="truncate text-foreground">{v}</dd>
                    </div>
                  ))}
                  <div className="col-span-2 min-w-0">
                    <dt className="text-muted-foreground uppercase">Status</dt>
                    <dd className="text-foreground">
                      {row.previous_state ?? "—"} → {row.next_state ?? "—"}
                    </dd>
                  </div>
                </dl>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

function ConnectDialog({
  platform,
  canManageAccounts,
  onClose,
}: {
  platform: PlatformMeta | null;
  canManageAccounts: boolean;
  onClose: () => void;
}) {
  const [authorizing, setAuthorizing] = useState(false);

  const start = async () => {
    if (!platform || !canManageAccounts) return;
    setAuthorizing(true);
    try {
      await startOAuth(platform.id);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to start connection.");
      setAuthorizing(false);
    }
  };

  return (
    <Dialog
      open={!!platform}
      onOpenChange={(o) => {
        if (!o) {
          setAuthorizing(false);
          onClose();
        }
      }}
    >
      <DialogContent className="max-h-[92vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="tracking-[0.08em] uppercase">
            Connect {platform?.name}
          </DialogTitle>
          <DialogDescription>
            You'll authorize on {platform?.name}'s official page. Scaleezy never sees your password.
          </DialogDescription>
        </DialogHeader>
        {platform ? (
          <div className="space-y-4">
            <div>
              <p className="label-eyebrow">Permissions requested</p>
              <ul className="mt-2 space-y-2">
                {platform.requiredPermissions.map((p) => (
                  <li key={p} className="flex items-center gap-2 text-sm text-foreground">
                    <CheckCircle2 className="size-4 text-success" /> {p}
                  </li>
                ))}
              </ul>
            </div>
            <Separator />
            <p className="text-xs text-muted-foreground">
              The account type ({platform.accountTypeOptions.join(" or ")}) and its details are read
              from {platform.name} after you authorize.
            </p>
            <DialogFooter>
              <Button disabled={authorizing || !canManageAccounts} onClick={start}>
                {authorizing ? (
                  <>
                    <RefreshCw className="size-4 animate-spin" /> Redirecting to {platform.name}…
                  </>
                ) : (
                  <>Continue with {platform.name}</>
                )}
              </Button>
            </DialogFooter>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function ManageSheet({
  account,
  busy,
  canManageAccounts,
  onClose,
  onPatch,
  onVerify,
  onReconnect,
  onDisconnect,
}: {
  account: Connection | null;
  busy: boolean;
  canManageAccounts: boolean;
  onClose: () => void;
  onPatch: (body: Partial<Pick<Connection, "publishing_enabled">>) => void;
  onVerify: () => void;
  onReconnect: () => void;
  onDisconnect: () => void;
}) {
  const publishingEnabledId = useId();
  if (!account) return null;
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle className="tracking-[0.08em] uppercase">{account.account_name}</SheetTitle>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-8">
          <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3">
            <PlatformIcon platform={platformId(account.platform)} />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">
                {account.username ?? account.external_account_id}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {account.account_type ?? statusLabel(account.platform)} ·{" "}
                {statusLabel(account.status)}
              </p>
            </div>
          </div>

          <div className="rounded-xl border border-border p-4">
            <p className="label-eyebrow">Details</p>
            <dl className="mt-3 space-y-2 text-xs">
              {[
                ["Account ID", account.external_account_id],
                ["Profile", account.profile_url ?? "—"],
                ["Connected", fmtDate(account.connected_at)],
                ["Last verified", fmtDate(account.last_verified_at)],
                ["Last published", fmtDate(account.last_published_at)],
              ].map(([k, v]) => (
                <div key={k} className="grid grid-cols-2 gap-2">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="truncate text-right text-foreground">{v}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="space-y-4">
            <p className="label-eyebrow">Publishing</p>
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor={publishingEnabledId} className="text-sm font-normal">
                Publishing enabled
              </Label>
              <Switch
                id={publishingEnabledId}
                checked={account.publishing_enabled}
                disabled={busy || !canManageAccounts || account.status !== "CONNECTED"}
                onCheckedChange={(v) => onPatch({ publishing_enabled: v })}
              />
            </div>
          </div>

          <Separator />
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={busy || !canManageAccounts}
              onClick={onVerify}
            >
              <RefreshCw className="size-4" /> Verify connection
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy || !canManageAccounts}
              onClick={onReconnect}
            >
              <Link2 className="size-4" /> Reconnect
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="text-destructive"
              disabled={busy || !canManageAccounts}
              onClick={onDisconnect}
            >
              <Unplug className="size-4" /> Disconnect
            </Button>
          </div>
          {!canManageAccounts ? (
            <p className="text-xs text-muted-foreground">
              Only a workspace owner or admin can change account settings.
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Access tokens are stored encrypted on the server and are never shown in the browser.
          </p>
        </div>
      </SheetContent>
    </Sheet>
  );
}
