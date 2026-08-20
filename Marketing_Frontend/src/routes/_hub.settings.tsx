import { useState, useEffect, useRef } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Check, ImagePlus, Phone, ShieldCheck, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader, SectionTitle, StatusBadge } from "@/components/marketing/primitives";
import { PERMISSION_MATRIX } from "@/lib/marketing-data";
import { useBrandSettings } from "@/lib/brand-settings";
import { AIProvidersPanel } from "@/components/marketing/ai-providers-panel";
import { apiFetch } from "@/lib/api";

export const Route = createFileRoute("/_hub/settings")({
  head: () => ({
    meta: [
      { title: "Marketing Settings — Scaleezy Marketing Hub" },
      {
        name: "description",
        content:
          "Configure workspace defaults, publishing rules, role permissions, notifications and security.",
      },
      { property: "og:title", content: "Marketing Settings — Scaleezy Marketing Hub" },
      {
        property: "og:description",
        content: "Marketing Hub configuration, permissions and security controls.",
      },
    ],
  }),
  component: SettingsPage,
});

const PERMISSION_COLUMNS = [
  "view",
  "create",
  "edit",
  "approve",
  "publish",
  "disconnect",
  "admin",
] as const;

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

const MAX_LOGO_BYTES = 2 * 1024 * 1024;

/**
 * Brand logo + contact details reused by the poster generator.
 *
 * Backed by the Brand record. The logo is uploaded straight to the Supabase
 * bucket, so `logoUrl` is only ever set once storage genuinely accepted it.
 */
function BrandKitPanel() {
  const { settings, update, uploadLogo, removeLogo, loading, error } = useBrandSettings();
  const logoInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const handleLogoPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // let the same file be re-picked after a remove
    if (!file) return;

    if (!file.type.startsWith("image/")) {
      toast.error("Logo must be an image (PNG, JPG or SVG).");
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      toast.error("Logo must be 2 MB or smaller.");
      return;
    }

    setUploading(true);
    try {
      // Uploaded straight to the bucket — the URL is only stored once the
      // upload genuinely succeeded.
      await uploadLogo(file);
      toast.success("Logo uploaded.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Logo upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleRemoveLogo = async () => {
    try {
      await removeLogo();
      toast("Logo removed.");
    } catch {
      toast.error("Could not remove the logo.");
    }
  };

  const hasLogo = !!settings.logoUrl;

  return (
    <Panel label="Brand Kit" title="Logo & contact details">
      {error ? (
        <p className="mb-4 rounded-xl border border-destructive/30 bg-destructive/8 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="grid gap-5">
        <div>
          <Label className="text-xs tracking-wide uppercase">Brand logo</Label>
          <p className="mt-1 text-xs text-muted-foreground">
            Used on AI-generated posters. PNG with a transparent background works best.
          </p>

          <div className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-4">
            <div className="grid size-20 shrink-0 place-items-center overflow-hidden rounded-xl border border-border bg-secondary/40">
              {hasLogo ? (
                <img
                  src={settings.logoUrl}
                  alt="Brand logo"
                  className="size-full object-contain p-2"
                />
              ) : (
                <ImagePlus className="size-6 text-muted-foreground" />
              )}
            </div>

            <div className="min-w-0">
              {hasLogo ? (
                <p className="truncate text-sm font-medium text-foreground">
                  {settings.logoFileName || "Brand logo"}
                </p>
              ) : (
                <p className="text-sm text-muted-foreground">No logo uploaded yet.</p>
              )}
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={loading || uploading}
                  onClick={() => logoInputRef.current?.click()}
                >
                  <ImagePlus className="size-4" />
                  {uploading ? "Uploading…" : hasLogo ? "Replace" : "Upload logo"}
                </Button>
                {hasLogo ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={handleRemoveLogo}
                  >
                    <Trash2 className="size-4" /> Remove
                  </Button>
                ) : null}
              </div>
            </div>
          </div>

          <input
            ref={logoInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleLogoPick}
          />
        </div>

        <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
          <div className="min-w-0">
            <Label className="text-sm font-normal">Show logo on generated posters</Label>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Can be overridden per poster in Publishing.
            </p>
          </div>
          <Switch
            checked={settings.showLogoOnPosters}
            disabled={!hasLogo}
            onCheckedChange={(v) => update({ showLogoOnPosters: v }, { immediate: true })}
          />
        </div>

        <div>
          <Label className="text-xs tracking-wide uppercase">Contact phone number</Label>
          <div className="relative mt-1.5">
            <Phone className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="tel"
              className="pl-9"
              placeholder="+91 98765 43210"
              value={settings.phoneNumber}
              onChange={(e) => update({ phoneNumber: e.target.value })}
            />
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">
            Optionally printed at the bottom of a poster after it is generated.
          </p>
        </div>

        <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
          <div className="min-w-0">
            <Label className="text-sm font-normal">Show phone number on posters</Label>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Can be overridden per poster in Publishing.
            </p>
          </div>
          <Switch
            checked={settings.showPhoneOnPosters}
            disabled={!settings.phoneNumber.trim()}
            onCheckedChange={(v) => update({ showPhoneOnPosters: v }, { immediate: true })}
          />
        </div>
      </div>
    </Panel>
  );
}

function SettingsPage() {
  const [workspace, setWorkspace] = useState<any>(null);
  const [auditLogs, setAuditLogs] = useState<any[]>([]);

  useEffect(() => {
    apiFetch("/api/marketing/settings/")
      .then((res) => res.json())
      .then((data) => {
        if (data.workspace) setWorkspace(data.workspace);
        if (data.audit_logs) setAuditLogs(data.audit_logs);
      })
      .catch(console.error);
  }, []);

  const handleSave = () => {
    apiFetch("/api/marketing/settings/", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace }),
    })
      .then(() => toast.success("Settings saved."))
      .catch(() => toast.error("Failed to save settings."));
  };

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="Marketing Settings"
        subtitle="Configure workspace defaults, publishing rules, permissions, notifications and security for your marketing operation."
        backTo="/"
        actions={<Button onClick={handleSave}>Save changes</Button>}
      />

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel label="General" title="Workspace">
          <div className="grid gap-4">
            <div>
              <Label className="text-xs tracking-wide uppercase">Workspace name</Label>
              <Input className="mt-1.5" defaultValue={workspace?.workspace_name || ""} />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="text-xs tracking-wide uppercase">Timezone</Label>
                <Select defaultValue={workspace?.timezone || "Asia/Kolkata"}>
                  <SelectTrigger className="mt-1.5 w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["Asia/Kolkata", "Asia/Dubai", "Europe/London"].map((tz) => (
                      <SelectItem key={tz} value={tz}>
                        {tz}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs tracking-wide uppercase">Default language</Label>
                <Select defaultValue={workspace?.default_language || "English (India)"}>
                  <SelectTrigger className="mt-1.5 w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["English (India)", "Hindi", "Telugu", "Tamil"].map((l) => (
                      <SelectItem key={l} value={l}>
                        {l}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        </Panel>

        <Panel label="Publishing" title="Publishing defaults">
          <div className="grid gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="text-xs tracking-wide uppercase">Default behavior</Label>
                <Select defaultValue="Publish now">
                  <SelectTrigger className="mt-1.5 w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["Publish now", "Schedule", "Save as draft"].map((o) => (
                      <SelectItem key={o} value={o}>
                        {o}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs tracking-wide uppercase">Default account</Label>
                <Select defaultValue="@scaleezyfashion">
                  <SelectTrigger className="mt-1.5 w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["@scaleezyfashion", "Scaleezy Fashion India", "Scaleezy Apparel"].map((a) => (
                      <SelectItem key={a} value={a}>
                        {a}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs tracking-wide uppercase">Allowed from</Label>
                <Input type="time" className="mt-1.5" defaultValue="09:00" />
              </div>
              <div>
                <Label className="text-xs tracking-wide uppercase">Allowed until</Label>
                <Input type="time" className="mt-1.5" defaultValue="21:00" />
              </div>
              <div>
                <Label className="text-xs tracking-wide uppercase">Daily post limit</Label>
                <Input type="number" className="mt-1.5" defaultValue={5} min={1} />
              </div>
            </div>
            <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
              <Label className="text-sm font-normal">Automatic retry on failure</Label>
              <Switch defaultChecked />
            </div>
          </div>
        </Panel>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <BrandKitPanel />
        <Panel label="AI" title="Providers & routing">
          <AIProvidersPanel />
        </Panel>
      </div>

      <div className="mt-6">
        <SectionTitle
          label="Permissions"
          title="Role permissions"
          description="Control who can view, create, edit, approve, publish, disconnect and administer."
        />
        <div className="surface-card overflow-hidden">
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs tracking-wide text-muted-foreground uppercase">
                  <th className="px-4 py-3 font-medium">Role</th>
                  {PERMISSION_COLUMNS.map((c) => (
                    <th key={c} className="px-4 py-3 font-medium">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {PERMISSION_MATRIX.map((row) => (
                  <tr key={row.role} className="border-b border-border/70 last:border-0">
                    <td className="px-4 py-3 font-medium text-foreground">{row.role}</td>
                    {PERMISSION_COLUMNS.map((c) => (
                      <td key={c} className="px-4 py-3">
                        {row[c] ? (
                          <Check className="size-4 text-success" />
                        ) : (
                          <X className="size-4 text-muted-foreground" />
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="divide-y divide-border lg:hidden">
            {PERMISSION_MATRIX.map((row) => (
              <div key={row.role} className="p-4">
                <p className="text-sm font-semibold text-foreground">{row.role}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {PERMISSION_COLUMNS.filter((c) => row[c]).map((c) => (
                    <span
                      key={c}
                      className="rounded-full border border-border bg-secondary/60 px-2 py-0.5 text-xs text-muted-foreground capitalize"
                    >
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Panel label="Notifications" title="Alerts">
          <div className="space-y-3">
            {[
              ["Publishing success", false],
              ["Publishing failure", true],
              ["Token expiry", true],
              ["Account disconnected", true],
              ["Permission changes", false],
            ].map(([label, on]) => (
              <div
                key={label as string}
                className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3"
              >
                <Label className="text-sm font-normal">{label as string}</Label>
                <Switch defaultChecked={on as boolean} />
              </div>
            ))}
          </div>
        </Panel>

        <Panel label="Security" title="Access & sessions">
          <div className="flex items-start gap-2 rounded-xl border border-gold/30 bg-gold/8 px-4 py-3 text-sm">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-gold" />
            <p>
              OAuth tokens are encrypted at rest on the server, never exposed to the browser and
              masked in logs.
            </p>
          </div>

          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
              <Label className="text-sm font-normal">Require reauthorization every 60 days</Label>
              <Switch defaultChecked />
            </div>
            <div className="rounded-xl border border-border px-4 py-3">
              <p className="text-xs tracking-wide text-muted-foreground uppercase">
                Active sessions
              </p>
              <ul className="mt-2 space-y-2 text-sm">
                {[
                  ["Anjali Manager · Chrome, Hyderabad", "Current session"],
                  ["Rohit Sharma · Safari, Mumbai", "2 hours ago"],
                ].map(([who, when]) => (
                  <li key={who} className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
                    <span className="truncate text-foreground">{who}</span>
                    <span className="text-xs text-muted-foreground">{when}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-xl border border-border px-4 py-3">
              <p className="text-xs tracking-wide text-muted-foreground uppercase">
                OAuth connection history
              </p>
              <ul className="mt-2 space-y-2 text-sm">
                {auditLogs.slice(0, 3).map((log, i) => (
                  <li key={i} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
                    <span className="min-w-0 truncate text-foreground">
                      {log.platform} · {log.action}
                    </span>
                    <StatusBadge
                      status={log.result}
                      tone={log.result === "Success" ? "success" : "danger"}
                    />
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
