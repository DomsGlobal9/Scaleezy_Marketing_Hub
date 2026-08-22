import { ArrowDown, ArrowUp, CheckCircle2, Loader2, Plug, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
 *   2. Routing   — the ordered provider set serving each capability, and how.
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
      toast.success("Credential is configured. Verify live access with a staging generation.");
      void res;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Connection failed.");
    } finally {
      await load();
      setBusy(null);
    }
  };

  const replaceRouteSet = async (
    capability: string,
    providerIds: string[],
    strategy: string,
  ) => {
    setBusy(capability);
    try {
      await apiPost("/api/marketing/ai/routes/replace-set/", {
        capability,
        strategy,
        routes: providerIds.map((provider, index) => ({
          provider,
          priority: (index + 1) * 10,
        })),
      });
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not update routing.");
    } finally {
      setBusy(null);
    }
  };

  const toggleRouteProvider = (capability: string, providerId: string, enabled: boolean) => {
    const rows = routes
      .filter((route) => route.capability === capability)
      .sort((a, b) => a.priority - b.priority);
    const current = rows.map((route) => route.provider);
    const next = enabled
      ? [...current.filter((id) => id !== providerId), providerId]
      : current.filter((id) => id !== providerId);
    void replaceRouteSet(capability, next, rows[0]?.strategy ?? "FAILOVER");
  };

  const moveRouteProvider = (capability: string, providerId: string, direction: -1 | 1) => {
    const rows = routes
      .filter((route) => route.capability === capability)
      .sort((a, b) => a.priority - b.priority);
    const ids = rows.map((route) => route.provider);
    const from = ids.indexOf(providerId);
    const to = from + direction;
    if (from < 0 || to < 0 || to >= ids.length) return;
    const next = [...ids];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved!);
    void replaceRouteSet(capability, next, rows[0]?.strategy ?? "FAILOVER");
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
                    aria-label={`${wp?.enabled ? "Disable" : "Enable"} ${p.display_name}`}
                    onCheckedChange={(v) => toggleProvider(p, v)}
                  />
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Input
                    type="password"
                    className="h-9 w-full max-w-xs"
                    aria-label={`${p.display_name} API key`}
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
                      <Plug className="size-4" /> Check configuration
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
          Assign one or more providers to each capability, then order their failover priority.
        </p>
        <div className="space-y-3">
          {capabilities.map((cap) => {
            const rows = routes
              .filter((r) => r.capability === cap.value)
              .sort((a, b) => a.priority - b.priority);
            const capable = catalogue.filter(
              (p) =>
                p.is_available &&
                p.adapter_installed &&
                p.capabilities.includes(cap.value),
            );
            const enabledCount = capable.filter((p) => connectedFor(p.id)?.enabled).length;
            return (
              <div
                key={cap.value}
                className="rounded-xl border border-border p-4"
              >
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">{cap.label}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {rows.length
                        ? `${rows.length} provider${rows.length === 1 ? "" : "s"} routed. Failover follows the order below.`
                        : enabledCount
                          ? "Select one or more providers for this capability."
                          : "No enabled provider can serve this yet."}
                    </p>
                  </div>

                  <Select
                    value={rows[0]?.strategy ?? "FAILOVER"}
                    disabled={busy === cap.value || !rows.length}
                    onValueChange={(strategy) =>
                      void replaceRouteSet(
                        cap.value,
                        rows.map((row) => row.provider),
                        strategy,
                      )
                    }
                  >
                    <SelectTrigger className="w-full sm:w-[190px]" aria-label={`${cap.label} strategy`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {strategies.map((strategy) => (
                        <SelectItem key={strategy.value} value={strategy.value}>
                          {strategy.value === "BEST_OF"
                            ? "Best of (costs N×)"
                            : strategy.label.split("—")[0]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {capable.length ? (
                  <div className="mt-4 space-y-2">
                    {capable.map((provider) => {
                      const routeIndex = rows.findIndex((row) => row.provider === provider.id);
                      const selected = routeIndex >= 0;
                      const enabled = !!connectedFor(provider.id)?.enabled;
                      return (
                        <div
                          key={provider.id}
                          className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-lg border border-border bg-background px-3 py-2.5"
                        >
                          <Checkbox
                            id={`${cap.value}-${provider.id}`}
                            checked={selected}
                            disabled={busy === cap.value || (!enabled && !selected)}
                            onCheckedChange={(value) =>
                              toggleRouteProvider(cap.value, provider.id, value === true)
                            }
                          />
                          <Label
                            htmlFor={`${cap.value}-${provider.id}`}
                            className="min-w-0 cursor-pointer text-sm font-normal"
                          >
                            <span className="block truncate">{provider.display_name}</span>
                            {selected ? (
                              <span className="block text-xs text-muted-foreground">
                                Priority {routeIndex + 1}{enabled ? "" : " · provider disabled"}
                              </span>
                            ) : !enabled ? (
                              <span className="block text-xs text-muted-foreground">
                                Enable this provider above before routing to it.
                              </span>
                            ) : null}
                          </Label>
                          {selected ? (
                            <div className="flex gap-1">
                              <Button
                                type="button"
                                size="icon"
                                variant="ghost"
                                className="size-8"
                                aria-label={`Move ${provider.display_name} up`}
                                disabled={busy === cap.value || routeIndex === 0}
                                onClick={() => moveRouteProvider(cap.value, provider.id, -1)}
                              >
                                <ArrowUp className="size-4" />
                              </Button>
                              <Button
                                type="button"
                                size="icon"
                                variant="ghost"
                                className="size-8"
                                aria-label={`Move ${provider.display_name} down`}
                                disabled={busy === cap.value || routeIndex === rows.length - 1}
                                onClick={() => moveRouteProvider(cap.value, provider.id, 1)}
                              >
                                <ArrowDown className="size-4" />
                              </Button>
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
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
