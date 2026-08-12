import { createFileRoute } from "@tanstack/react-router";
import {
  AlertTriangle,
  CheckCircle2,
  Link2,
  PauseCircle,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Unplug,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
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
import {
  PageHeader,
  PlatformIcon,
  SectionTitle,
  StatusBadge,
} from "@/components/marketing/primitives";
import {
  AUDIT_LOGS,
  DEMO_ACCOUNTS,
  PLATFORMS,
  type PlatformMeta,
  type SocialAccount,
} from "@/lib/marketing-data";

export const Route = createFileRoute("/_hub/accounts")({
  head: () => ({
    meta: [
      { title: "Social Media Accounts — Scaleezy Marketing Hub" },
      {
        name: "description",
        content:
          "Securely connect and manage Facebook, Instagram, LinkedIn, X, TikTok, YouTube and Google Business accounts.",
      },
      { property: "og:title", content: "Social Media Accounts — Scaleezy Marketing Hub" },
      {
        property: "og:description",
        content:
          "Connect social accounts securely with official OAuth and manage publishing access.",
      },
    ],
  }),
  component: AccountsPage,
});

type ConnectStep = "type" | "authorizing" | "select" | "permissions";

function AccountsPage() {
  const [accounts, setAccounts] = useState<SocialAccount[]>(DEMO_ACCOUNTS);
  const [connectPlatform, setConnectPlatform] = useState<PlatformMeta | null>(null);
  const [manageAccount, setManageAccount] = useState<SocialAccount | null>(null);
  const [disconnectTarget, setDisconnectTarget] = useState<SocialAccount | null>(null);

  useEffect(() => {
    fetch(import.meta.env.VITE_API_URL + '/api/marketing/social-accounts/')
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setAccounts(data);
        }
      })
      .catch(console.error);
  }, []);

  const summary = useMemo(() => {
    const connected = accounts.filter((a) => a.status === "Connected").length;
    const enabled = accounts.filter((a) => a.publishingEnabled && a.status === "Connected").length;
    const attention = accounts.filter((a) =>
      ["Token Expired", "Reauthorization Required", "Permission Missing", "Revoked"].includes(
        a.status,
      ),
    ).length;
    const paused = accounts.filter((a) => a.settings?.paused).length;
    return { connected, enabled, attention, paused };
  }, [accounts]);

  const update = (id: string, patch: Partial<SocialAccount>) =>
    setAccounts((prev) => prev.map((a) => (a.id === id ? { ...a, ...patch } : a)));

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="Social Media Accounts"
        subtitle="Connect your social accounts securely and publish approved marketing content from Scaleezy."
        backTo="/"
        actions={
          <Button onClick={() => setConnectPlatform(PLATFORMS[0] ?? null)}>
            <Plus className="size-4" /> Connect Account
          </Button>
        }
      />

      <div className="mb-4 flex items-start gap-2 rounded-xl border border-gold/30 bg-gold/8 px-4 py-3 text-sm text-foreground">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-gold" />
        <p>
          Demo workspace — connections shown here are mock states. Scaleezy never asks for social
          passwords or tokens; authorization always happens on the official platform.
        </p>
      </div>

      <section className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {[
          { label: "Connected Accounts", value: summary.connected, tone: "success" as const },
          { label: "Publishing Enabled", value: summary.enabled, tone: "success" as const },
          { label: "Needs Attention", value: summary.attention, tone: "warning" as const },
          { label: "Publishing Paused", value: summary.paused, tone: "neutral" as const },
        ].map((item) => (
          <div key={item.label} className="surface-card p-5">
            <p className="text-2xl font-semibold text-foreground">{item.value}</p>
            <p className="mt-1 text-xs tracking-wide text-muted-foreground uppercase">
              {item.label}
            </p>
          </div>
        ))}
      </section>

      <section className="mt-10">
        <SectionTitle
          label="Connected"
          title="Your connected accounts"
          description="Account details are retrieved automatically after authorization."
        />
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {accounts.map((account) => (
            <article key={account.id} className="surface-card p-5">
              <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3">
                <PlatformIcon platform={account.platform} />
                <div className="min-w-0">
                  <h3 className="truncate text-base font-semibold text-foreground">
                    {account.accountName}
                  </h3>
                  <p className="truncate text-sm text-muted-foreground">
                    {account.username} · {account.accountType}
                  </p>
                  <StatusBadge status={account.status} className="mt-2" />
                </div>
              </div>

              <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                {[
                  ["Connected by", account.connectedBy],
                  ["Role", account.role],
                  ["Token", account.tokenStatus],
                  ["Last verified", account.lastVerified],
                  ["Last published", account.lastPublished],
                  ["Connected on", account.connectedAt],
                ].map(([k, v]) => (
                  <div key={k} className="min-w-0">
                    <dt className="tracking-wide text-muted-foreground uppercase">{k}</dt>
                    <dd className="truncate font-medium text-foreground">{v}</dd>
                  </div>
                ))}
              </dl>

              <div className="mt-4 flex flex-wrap gap-1.5">
                {(account.permissions || []).map((p) => (
                  <span
                    key={p}
                    className="inline-flex items-center gap-1 rounded-full border border-border bg-secondary/60 px-2 py-0.5 text-xs text-muted-foreground"
                  >
                    <CheckCircle2 className="size-3 text-success" /> {p}
                  </span>
                ))}
              </div>

              {account.lastError ? (
                <p className="mt-3 flex items-start gap-2 rounded-lg border border-gold/30 bg-gold/8 px-3 py-2 text-xs text-foreground">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-gold" />
                  {account.lastError}
                </p>
              ) : null}

              <div className="mt-5 flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => setManageAccount(account)}>
                  <Settings2 className="size-4" /> Manage
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    update(account.id, {
                      status: "Connected",
                      tokenStatus: "Healthy",
                      publishingEnabled: true,
                      lastError: undefined,
                    });
                    toast.success(`${account.accountName} reconnected.`);
                  }}
                >
                  <RefreshCw className="size-4" /> Reconnect
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    const paused = !account.settings?.paused;
                    update(account.id, { settings: { ...account.settings, paused } });
                    toast(paused ? "Publishing paused." : "Publishing resumed.");
                  }}
                >
                  <PauseCircle className="size-4" />
                  {account.settings?.paused ? "Resume" : "Pause"} Publishing
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-destructive hover:text-destructive"
                  onClick={() => setDisconnectTarget(account)}
                >
                  <Unplug className="size-4" /> Disconnect
                </Button>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="mt-10">
        <SectionTitle
          label="Available Platforms"
          title="Add another channel"
          description="Authorization uses official platform OAuth. Scaleezy never stores your password."
        />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {PLATFORMS.map((platform) => {
            const existing = accounts.find((a) => a.platform.toLowerCase() === platform.id.toLowerCase());
            if (existing) return null;
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
                  <StatusBadge status={existing ? existing.status : "Not Connected"} />
                  <Button
                    size="sm"
                    variant={existing ? "outline" : "default"}
                    onClick={() =>
                      existing ? setManageAccount(existing) : setConnectPlatform(platform)
                    }
                  >
                    {existing ? (
                      "Manage"
                    ) : (
                      <>
                        <Link2 className="size-4" /> Connect Account
                      </>
                    )}
                  </Button>
                </div>
                <ul className="mt-4 space-y-1 text-xs text-muted-foreground">
                  {platform.fields.slice(0, 3).map((f) => (
                    <li key={f}>· {f} retrieved automatically</li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </section>

      <section className="mt-10">
        <SectionTitle
          label="Account Activity"
          title="Audit log"
          description="Every connection, permission and token event is recorded."
        />
        <AuditTable />
      </section>

      <ConnectDialog
        platform={connectPlatform}
        onClose={() => setConnectPlatform(null)}
        onConnected={(name) => {
          setConnectPlatform(null);
          toast.success(`${name} connected successfully.`);
        }}
      />

      <ManageSheet
        account={manageAccount}
        onClose={() => setManageAccount(null)}
        onChange={(patch) => manageAccount && update(manageAccount.id, patch)}
      />

      <AlertDialog open={!!disconnectTarget} onOpenChange={(o) => !o && setDisconnectTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Disconnect {disconnectTarget?.accountName}?</AlertDialogTitle>
            <AlertDialogDescription>
              Disconnecting this account will stop future publishing from Scaleezy. You can
              reconnect later.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (disconnectTarget) {
                  update(disconnectTarget.id, {
                    status: "Disconnected",
                    publishingEnabled: false,
                    tokenStatus: "Revoked",
                  });
                  toast("Account disconnected.");
                }
                setDisconnectTarget(null);
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
  const [platform, setPlatform] = useState("all");
  const [user, setUser] = useState("");
  const query = user.trim().toLowerCase();
  const rows = AUDIT_LOGS.filter(
    (r) =>
      (platform === "all" || r.platform === platform) &&
      (!query || r.user.toLowerCase().includes(query)),
  );

  return (
    <div className="surface-card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <Select value={platform} onValueChange={setPlatform}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Platform" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All platforms</SelectItem>
            {["Instagram", "Facebook", "LinkedIn", "X"].map((p) => (
              <SelectItem key={p} value={p}>
                {p}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          placeholder="Filter by user"
          className="w-[180px]"
          value={user}
          onChange={(e) => setUser(e.target.value)}
        />
      </div>

      {rows.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-muted-foreground">
          No audit events match these filters.
        </p>
      ) : null}

      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full text-sm">
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
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-border/70 last:border-0">
                <td className="px-4 py-3 whitespace-nowrap">{row.date}</td>
                <td className="px-4 py-3 whitespace-nowrap">{row.user}</td>
                <td className="px-4 py-3">{row.platform}</td>
                <td className="px-4 py-3">{row.account}</td>
                <td className="px-4 py-3">{row.action}</td>
                <td className="px-4 py-3 text-muted-foreground">{row.previous}</td>
                <td className="px-4 py-3">{row.next}</td>
                <td className="px-4 py-3">
                  <StatusBadge
                    status={row.result}
                    tone={row.result === "Success" ? "success" : "danger"}
                  />
                </td>
                <td className="px-4 py-3 text-muted-foreground">{row.error}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="divide-y divide-border lg:hidden">
        {rows.map((row, i) => (
          <div key={i} className="p-4">
            <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
              <p className="min-w-0 truncate text-sm font-medium text-foreground">{row.action}</p>
              <StatusBadge
                status={row.result}
                tone={row.result === "Success" ? "success" : "danger"}
              />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{row.date}</p>
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
              {/* Status needs the full row — "Previous → New" overflows a half-width cell. */}
              <div className="col-span-2 min-w-0">
                <dt className="text-muted-foreground uppercase">Status</dt>
                <dd className="text-foreground">
                  {row.previous} → {row.next}
                </dd>
              </div>
            </dl>
          </div>
        ))}
      </div>
    </div>
  );
}

function ConnectDialog({
  platform,
  onClose,
  onConnected,
}: {
  platform: PlatformMeta | null;
  onClose: () => void;
  onConnected: (name: string) => void;
}) {
  const [step, setStep] = useState<ConnectStep>("type");
  const [accountType, setAccountType] = useState<string>("");
  const [selected, setSelected] = useState<string>("");
  const authorizeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearAuthorizeTimer = () => {
    if (authorizeTimer.current !== null) {
      clearTimeout(authorizeTimer.current);
      authorizeTimer.current = null;
    }
  };

  useEffect(() => clearAuthorizeTimer, []);

  const reset = () => {
    // Without this, closing mid-authorization lets the pending timer advance the
    // step, so reopening the dialog starts on "select" instead of "type".
    clearAuthorizeTimer();
    setStep("type");
    setAccountType("");
    setSelected("");
  };

  const available = [
    { id: "opt-1", name: "Scaleezy Fashion", handle: "@scaleezyfashion" },
    { id: "opt-2", name: "Scaleezy Couture", handle: "@scaleezycouture" },
  ];

  return (
    <Dialog
      open={!!platform}
      onOpenChange={(o) => {
        if (!o) {
          reset();
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

        {step === "type" && platform ? (
          <div className="space-y-4">
            <Label className="text-xs tracking-wide uppercase">Account type</Label>
            <RadioGroup value={accountType} onValueChange={setAccountType} className="gap-2">
              {platform.accountTypeOptions.map((opt) => (
                <label
                  key={opt}
                  className="flex cursor-pointer items-center gap-3 rounded-xl border border-border px-4 py-3 text-sm has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/5"
                >
                  <RadioGroupItem value={opt} />
                  {opt}
                </label>
              ))}
            </RadioGroup>
            <DialogFooter>
              <Button
                disabled={!accountType || step === "authorizing"}
                onClick={() => {
                  setStep("authorizing");

                  // Let's implement this properly:
                  fetch(import.meta.env.VITE_API_URL + "/api/marketing/workspaces/")
                    .then(res => res.json())
                    .then(data => {
                        const wsId = Array.isArray(data) && data.length > 0 ? data[0].id : null;
                        return fetch(import.meta.env.VITE_API_URL + "/api/marketing/social-accounts/connect/", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                workspace_id: wsId,
                                platform: platform.name
                            })
                        });
                    })
                    .then(res => res.json())
                    .then(data => {
                        if (data.success && data.data.authorization_url) {
                            window.location.href = data.data.authorization_url;
                        } else {
                            toast.error(data.message || data.error?.message || "Failed to start connection");
                            setStep("type");
                        }
                    })
                    .catch(err => {
                        console.error(err);
                        toast.error("Network error");
                        setStep("type");
                    });
                }}
              >
                Continue with {platform.name}
              </Button>
            </DialogFooter>
          </div>
        ) : null}

        {step === "authorizing" ? (
          <div className="flex flex-col items-center gap-3 py-10 text-sm text-muted-foreground">
            <RefreshCw className="size-6 animate-spin text-primary" />
            Connecting… redirecting to the official authorization page
          </div>
        ) : null}

        {step === "select" ? (
          <div className="space-y-4">
            <p className="label-eyebrow">Select account</p>
            <RadioGroup value={selected} onValueChange={setSelected} className="gap-2">
              {available.map((acc) => (
                <label
                  key={acc.id}
                  className="flex cursor-pointer items-center gap-3 rounded-xl border border-border px-4 py-3 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/5"
                >
                  <RadioGroupItem value={acc.id} />
                  <span className="grid size-9 place-items-center rounded-full bg-secondary text-xs font-semibold">
                    {acc.name.charAt(0)}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-foreground">
                      {acc.name}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {acc.handle} · {accountType}
                    </span>
                  </span>
                </label>
              ))}
            </RadioGroup>
            <DialogFooter>
              <Button disabled={!selected} onClick={() => setStep("permissions")}>
                Continue
              </Button>
            </DialogFooter>
          </div>
        ) : null}

        {step === "permissions" && platform ? (
          <div className="space-y-4">
            <p className="label-eyebrow">Permissions requested</p>
            <ul className="space-y-2">
              {platform.requiredPermissions.map((p) => (
                <li key={p} className="flex items-center gap-2 text-sm text-foreground">
                  <CheckCircle2 className="size-4 text-success" /> {p}
                </li>
              ))}
            </ul>
            <Separator />
            <p className="text-xs tracking-wide text-muted-foreground uppercase">Optional</p>
            <div className="space-y-2">
              {platform.optionalPermissions.map((p) => (
                <label key={p} className="flex items-center gap-2 text-sm text-foreground">
                  <Checkbox /> {p}
                </label>
              ))}
            </div>
            <DialogFooter>
              <Button
                onClick={() => {
                  reset();
                  onConnected(platform.name);
                }}
              >
                Connect Account
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
  onClose,
  onChange,
}: {
  account: SocialAccount | null;
  onClose: () => void;
  onChange: (patch: Partial<SocialAccount>) => void;
}) {
  if (!account) return null;
  const s = account.settings;
  const setSetting = (patch: Partial<SocialAccount["settings"]>) =>
    onChange({ settings: { ...s, ...patch } });

  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle className="tracking-[0.08em] uppercase">{account.accountName}</SheetTitle>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-8">
          <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3">
            <PlatformIcon platform={account.platform} />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">{account.username}</p>
              <p className="truncate text-xs text-muted-foreground">{account.accountType}</p>
            </div>
          </div>

          <div className="rounded-xl border border-border p-4">
            <p className="label-eyebrow">Platform details</p>
            <dl className="mt-3 space-y-2 text-xs">
              {(account.platformDetails || []).map((d) => (
                <div key={d.label} className="grid grid-cols-2 gap-2">
                  <dt className="text-muted-foreground">{d.label}</dt>
                  <dd className="truncate text-right text-foreground">{d.value}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="space-y-4">
            <p className="label-eyebrow">Publishing</p>
            {[
              [
                "Publishing enabled",
                account.publishingEnabled,
                (v: boolean) => onChange({ publishingEnabled: v }),
              ],
              [
                "Set as default account",
                account.isDefault,
                (v: boolean) => onChange({ isDefault: v }),
              ],
              [
                "Automatic retry",
                s.automaticRetry,
                (v: boolean) => setSetting({ automaticRetry: v }),
              ],
              ["Comments access", s.comments, (v: boolean) => setSetting({ comments: v })],
              ["Analytics access", s.analytics, (v: boolean) => setSetting({ analytics: v })],
              ["Publishing paused", s.paused, (v: boolean) => setSetting({ paused: v })],
            ].map(([label, value, fn]) => (
              <div key={label as string} className="flex items-center justify-between gap-4">
                <Label className="text-sm font-normal">{label as string}</Label>
                <Switch checked={value as boolean} onCheckedChange={fn as (v: boolean) => void} />
              </div>
            ))}
          </div>

          <div className="grid gap-3">
            <div>
              <Label className="text-xs tracking-wide uppercase">Timezone</Label>
              <Select value={s.timezone} onValueChange={(v) => setSetting({ timezone: v })}>
                <SelectTrigger className="mt-1.5 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["Asia/Kolkata", "Asia/Dubai", "Europe/London", "America/New_York"].map((tz) => (
                    <SelectItem key={tz} value={tz}>
                      {tz}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs tracking-wide uppercase">Allowed from</Label>
                <Input
                  type="time"
                  className="mt-1.5"
                  value={s.allowedStart}
                  onChange={(e) => setSetting({ allowedStart: e.target.value })}
                />
              </div>
              <div>
                <Label className="text-xs tracking-wide uppercase">Allowed until</Label>
                <Input
                  type="time"
                  className="mt-1.5"
                  value={s.allowedEnd}
                  onChange={(e) => setSetting({ allowedEnd: e.target.value })}
                />
              </div>
            </div>
            <div>
              <Label className="text-xs tracking-wide uppercase">Daily publishing limit</Label>
              <Input
                type="number"
                min={1}
                className="mt-1.5"
                value={s.dailyLimit}
                onChange={(e) => setSetting({ dailyLimit: Number(e.target.value) })}
              />
            </div>
          </div>

          <Separator />
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast.success("Reconnection started.")}
            >
              <RefreshCw className="size-4" /> Reconnect Account
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="text-destructive"
              onClick={() => toast("Access revoked.")}
            >
              Revoke Access
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Access tokens are stored encrypted on the server and are never shown in the browser.
          </p>
        </div>
      </SheetContent>
    </Sheet>
  );
}
