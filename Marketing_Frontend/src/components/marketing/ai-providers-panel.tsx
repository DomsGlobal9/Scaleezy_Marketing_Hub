import { CheckCircle2, Loader2, Plug, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

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
import { Switch } from "@/components/ui/switch";
import { api, apiPost } from "@/lib/api";

interface CatalogueProvider {
  id: string;
  key: string;
  display_name: string;
  capabilities: string[];
  default_model: string;
  is_available: boolean;
  adapter_installed: boolean;
}
interface Vocab {
  value: string;
  label: string;
}
interface WorkspaceProvider {
  id: string;
  provider: string;
  provider_key: string;
  provider_name: string;
  capabilities: string[];
  enabled: boolean;
  has_credentials: boolean;
  model_override: string;
  last_health_ok: boolean | null;
  last_error: string;
}
interface RouteRow {
  id: string;
  capability: string;
  provider: string;
  provider_key: string;
  priority: number;
  enabled: boolean;
  strategy: string;
}

/**
 * Two tiers, matching how the decisions actually split:
 *   1. Providers — which AIs this customer has switched on, and their keys.
 *   2. Routing   — which provider serves which task, and how.
 */
export function AIProvidersPanel() {
  const [catalogue, setCatalogue] = useState<CatalogueProvider[]>([]);
  const [capabilities, setCapabilities] = useState<Vocab[]>([]);
  const [strategies, setStrategies] = useState<Vocab[]>([]);
  const [mine, setMine] = useState<WorkspaceProvider[]>([]);
  const [routes, setRoutes] = useState<RouteRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const [cat, ws, rt] = await Promise.all([
        api<{ providers: CatalogueProvider[]; capabilities: Vocab[]; strategies: Vocab[] }>(
          "/api/marketing/ai/catalogue/",
        ),
        api<WorkspaceProvider[]>("/api/marketing/ai/providers/"),
        api<RouteRow[]>("/api/marketing/ai/routes/"),
      ]);
      setCatalogue(cat.providers ?? []);
      setCapabilities(cat.capabilities ?? []);
      setStrategies(cat.strategies ?? []);
      setMine(Array.isArray(ws) ? ws : []);
      setRoutes(Array.isArray(rt) ? rt : []);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not load AI settings.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const connectedFor = (providerId: string) => mine.find((m) => m.provider === providerId);

  const toggleProvider = async (p: CatalogueProvider, on: boolean) => {
    setBusy(p.id);
    try {
      const existing = connectedFor(p.id);
      if (existing) {
        await api(`/api/marketing/ai/providers/${existing.id}/`, {
          method: "PATCH",
          body: { enabled: on },
        });
      } else {
        await apiPost("/api/marketing/ai/providers/", {
          provider: p.id,
          enabled: on,
          credentials: keys[p.id] ?? "",
        });
      }
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not update provider.");
    } finally {
      setBusy(null);
    }
  };

  const saveKey = async (p: CatalogueProvider) => {
    const existing = connectedFor(p.id);
    setBusy(p.id);
    try {
      if (existing) {
        await api(`/api/marketing/ai/providers/${existing.id}/`, {
          method: "PATCH",
          body: { credentials: keys[p.id] ?? "" },
        });
      } else {
        await apiPost("/api/marketing/ai/providers/", {
          provider: p.id,
          enabled: false,
          credentials: keys[p.id] ?? "",
        });
      }
      setKeys((k) => ({ ...k, [p.id]: "" }));
      toast.success("Key saved.");
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save key.");
    } finally {
      setBusy(null);
    }
  };

  const testProvider = async (wp: WorkspaceProvider) => {
    setBusy(wp.id);
    try {
      const res = await apiPost<unknown>(`/api/marketing/ai/providers/${wp.id}/test/`, {});
      toast.success("Connection OK.");
      void res;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Connection failed.");
    } finally {
      await load();
      setBusy(null);
    }
  };

  const setRoute = async (capability: string, providerId: string) => {
    const existing = routes.filter((r) => r.capability === capability);
    setBusy(capability);
    try {
      // One provider per capability from this UI. Multi-provider ordering and
      // BEST_OF racing are supported by the API and the admin.
      for (const r of existing) {
        await api(`/api/marketing/ai/routes/${r.id}/`, { method: "DELETE" });
      }
      if (providerId !== "none") {
        await apiPost("/api/marketing/ai/routes/", {
          capability,
          provider: providerId,
          priority: 10,
        });
      }
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not update routing.");
    } finally {
      setBusy(null);
    }
  };

  const setStrategy = async (capability: string, strategy: string) => {
    const rows = routes.filter((r) => r.capability === capability);
    if (!rows.length) return;
    setBusy(capability);
    try {
      for (const r of rows) {
        await api(`/api/marketing/ai/routes/${r.id}/`, { method: "PATCH", body: { strategy } });
      }
      await load();
    } catch {
      toast.error("Could not update strategy.");
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Loading AI settings…
      </p>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <p className="label-eyebrow">Providers</p>
        <p className="mt-1 mb-4 text-xs text-muted-foreground">
          Switch a provider on for this workspace and give it an API key.
        </p>
        <div className="space-y-3">
          {catalogue.map((p) => {
            const wp = connectedFor(p.id);
            return (
              <div key={p.id} className="rounded-xl border border-border p-4">
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-foreground">
                      {p.display_name}
                      {wp?.last_health_ok === true ? (
                        <CheckCircle2 className="ml-1.5 inline size-3.5 text-success" />
                      ) : wp?.last_health_ok === false ? (
                        <XCircle className="ml-1.5 inline size-3.5 text-destructive" />
                      ) : null}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {p.capabilities.join(" · ") || "no capabilities declared"}
                    </p>
                    {!p.adapter_installed ? (
                      <p className="mt-1 text-xs text-destructive">
                        No adapter installed for this provider.
                      </p>
                    ) : null}
                    {wp?.last_error ? (
                      <p className="mt-1 text-xs text-destructive">{wp.last_error}</p>
                    ) : null}
                  </div>
                  <Switch
                    checked={!!wp?.enabled}
                    disabled={busy === p.id || !p.adapter_installed}
                    onCheckedChange={(v) => toggleProvider(p, v)}
                  />
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Input
                    type="password"
                    className="h-9 w-full max-w-xs"
                    placeholder={wp?.has_credentials ? "•••••••• (saved)" : "API key"}
                    value={keys[p.id] ?? ""}
                    onChange={(e) => setKeys((k) => ({ ...k, [p.id]: e.target.value }))}
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy === p.id || !(keys[p.id] ?? "").trim()}
                    onClick={() => saveKey(p)}
                  >
                    Save key
                  </Button>
                  {wp ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy === p.id}
                      onClick={() => testProvider(wp)}
                    >
                      <Plug className="size-4" /> Test
                    </Button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div>
        <p className="label-eyebrow">Routing</p>
        <p className="mt-1 mb-4 text-xs text-muted-foreground">
          Choose which provider handles each task. Copy and images can use different AIs.
        </p>
        <div className="space-y-3">
          {capabilities.map((cap) => {
            const rows = routes.filter((r) => r.capability === cap.value);
            const eligible = catalogue.filter(
              (p) => p.capabilities.includes(cap.value) && connectedFor(p.id)?.enabled,
            );
            return (
              <div
                key={cap.value}
                className="grid gap-3 rounded-xl border border-border p-4 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">{cap.label}</p>
                  {!eligible.length ? (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      No enabled provider can serve this yet.
                    </p>
                  ) : null}
                </div>

                <Select
                  value={rows[0]?.provider ?? "none"}
                  disabled={busy === cap.value || !eligible.length}
                  onValueChange={(v) => setRoute(cap.value, v)}
                >
                  <SelectTrigger className="w-[190px]">
                    <SelectValue placeholder="Not routed" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Not routed</SelectItem>
                    {eligible.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Select
                  value={rows[0]?.strategy ?? "FAILOVER"}
                  disabled={busy === cap.value || !rows.length}
                  onValueChange={(v) => setStrategy(cap.value, v)}
                >
                  <SelectTrigger className="w-[150px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {strategies.map((s) => (
                      <SelectItem key={s.value} value={s.value}>
                        {s.value === "BEST_OF" ? "Best of (costs N×)" : s.label.split("—")[0]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            );
          })}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          <Label className="text-xs font-normal">
            Best of runs every routed provider and keeps the highest scoring result — it multiplies
            the cost of each generation.
          </Label>
        </p>
      </div>
    </div>
  );
}
