import {
  Activity,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  CircleAlert,
  Gauge,
  KeyRound,
  Loader2,
  Network,
  Plug,
  Plus,
  RefreshCw,
  Route as RouteIcon,
  ServerCog,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, apiPost } from "@/lib/api";

export const AI_ADMIN_TABS = ["overview", "providers", "routing", "activity"] as const;
export type AIAdminTab = (typeof AI_ADMIN_TABS)[number];

interface CatalogueProvider {
  id: string;
  key: string;
  display_name: string;
  capabilities: string[];
  default_model: string;
  is_available: boolean;
  adapter_installed: boolean;
  integration_type: "INSTALLED" | "OPENAI_COMPATIBLE" | "SCALEEZY_JSON";
  base_url: string;
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
  last_health_check_at: string | null;
  last_health_ok: boolean | null;
  last_error: string;
}

interface RouteRow {
  id: string;
  capability: string;
  provider: string;
  provider_key: string;
  provider_name: string;
  priority: number;
  enabled: boolean;
  strategy: string;
}

interface ResolvedRoute {
  strategy: string;
  providers: string[];
}

interface UsageSummaryRow {
  provider__key: string | null;
  capability: string;
  calls: number;
  spend: string | number | null;
  successes?: number;
  failures?: number;
  average_latency_ms?: number | null;
}

interface UsageRow {
  id: string;
  provider_key: string | null;
  capability: string;
  cost: string | number;
  latency_ms: number;
  success: boolean;
  error: string;
  strategy: string;
  selected: boolean;
  created_at: string;
}

interface RouteDraft {
  providerIds: string[];
  strategy: string;
  dirty: boolean;
}

interface Paginated<T> {
  results: T[];
}

const CUSTOM_PROVIDER_VALUE = "__custom_openai_compatible__";

function asRows<T>(value: T[] | Paginated<T>): T[] {
  return Array.isArray(value) ? value : (value.results ?? []);
}

function money(value: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value < 1 ? 4 : 2,
    maximumFractionDigits: value < 1 ? 4 : 2,
  }).format(value);
}

function when(value: string | null): string {
  if (!value) return "Not checked yet";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? "Not checked yet" : parsed.toLocaleString();
}

function humanize(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function MetricCard({
  title,
  value,
  hint,
  icon,
}: {
  title: string;
  value: string;
  hint: string;
  icon: ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0 pb-2">
        <CardDescription>{title}</CardDescription>
        <span className="text-muted-foreground">{icon}</span>
      </CardHeader>
      <CardContent>
        <p className="font-display text-3xl font-semibold">{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  );
}

/**
 * Workspace AI administration. Catalogue, membership, ordered route sets and
 * activity all come from the backend; no provider name or two-provider limit
 * is encoded in this UI.
 */
export function AIProvidersPanel({
  activeTab,
  onTabChange,
}: {
  activeTab: AIAdminTab;
  onTabChange: (tab: AIAdminTab) => void;
}) {
  const [catalogue, setCatalogue] = useState<CatalogueProvider[]>([]);
  const [capabilities, setCapabilities] = useState<Vocab[]>([]);
  const [strategies, setStrategies] = useState<Vocab[]>([]);
  const [mine, setMine] = useState<WorkspaceProvider[]>([]);
  const [resolved, setResolved] = useState<Record<string, ResolvedRoute>>({});
  const [usageSummary, setUsageSummary] = useState<UsageSummaryRow[]>([]);
  const [usage, setUsage] = useState<UsageRow[]>([]);
  const [routeDrafts, setRouteDrafts] = useState<Record<string, RouteDraft>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [providerFilter, setProviderFilter] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [addProviderId, setAddProviderId] = useState("");
  const [addCredential, setAddCredential] = useState("");
  const [addModel, setAddModel] = useState("");
  const [addCustomName, setAddCustomName] = useState("");
  const [addBaseUrl, setAddBaseUrl] = useState("");
  const [addIntegrationType, setAddIntegrationType] = useState("");
  const [addCapabilities, setAddCapabilities] = useState<string[]>([]);
  const [addEnabled, setAddEnabled] = useState(true);

  const buildDrafts = useCallback((caps: Vocab[], rows: RouteRow[]) => {
    const next: Record<string, RouteDraft> = {};
    for (const capability of caps) {
      const members = rows
        .filter((row) => row.capability === capability.value)
        .sort((a, b) => a.priority - b.priority);
      next[capability.value] = {
        providerIds: members.map((row) => row.provider),
        strategy: members[0]?.strategy ?? "FAILOVER",
        dirty: false,
      };
    }
    setRouteDrafts(next);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [cat, workspaceProviders, routeRows, activeRoutes, summary, recent] = await Promise.all(
        [
          api<{ providers: CatalogueProvider[]; capabilities: Vocab[]; strategies: Vocab[] }>(
            "/api/marketing/ai/catalogue/",
          ),
          api<WorkspaceProvider[] | Paginated<WorkspaceProvider>>("/api/marketing/ai/providers/"),
          api<RouteRow[] | Paginated<RouteRow>>("/api/marketing/ai/routes/"),
          api<Record<string, ResolvedRoute>>("/api/marketing/ai/routes/resolved/"),
          api<UsageSummaryRow[]>("/api/marketing/ai/usage/summary/"),
          api<UsageRow[] | Paginated<UsageRow>>("/api/marketing/ai/usage/"),
        ],
      );

      const providerRows = asRows(workspaceProviders);
      const routingRows = asRows(routeRows);
      setCatalogue(cat.providers ?? []);
      setCapabilities(cat.capabilities ?? []);
      setStrategies(cat.strategies ?? []);
      setMine(providerRows);
      setResolved(activeRoutes ?? {});
      setUsageSummary(Array.isArray(summary) ? summary : []);
      setUsage(asRows(recent));
      buildDrafts(cat.capabilities ?? [], routingRows);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not load the Admin console.");
    } finally {
      setLoading(false);
    }
  }, [buildDrafts]);

  useEffect(() => {
    void load();
  }, [load]);

  const connectedFor = useCallback(
    (providerId: string) => mine.find((row) => row.provider === providerId),
    [mine],
  );

  const availableToAdd = useMemo(
    () =>
      catalogue.filter(
        (provider) =>
          provider.adapter_installed &&
          provider.is_available &&
          !mine.some((row) => row.provider === provider.id),
      ),
    [catalogue, mine],
  );

  const openAddProvider = () => {
    setAddProviderId("");
    setAddCredential("");
    setAddModel("");
    setAddCustomName("");
    setAddBaseUrl("");
    setAddIntegrationType("");
    setAddCapabilities([]);
    setAddEnabled(true);
    setAddOpen(true);
  };

  const addProvider = async () => {
    const custom = addProviderId === CUSTOM_PROVIDER_VALUE;
    const provider = availableToAdd.find((row) => row.id === addProviderId);
    if (!custom && !provider) return;
    setBusy("add-provider");
    try {
      if (custom) {
        await apiPost("/api/marketing/ai/providers/custom/", {
          display_name: addCustomName.trim(),
          base_url: addBaseUrl.trim(),
          credentials: addCredential.trim(),
          model: addModel.trim(),
          integration_type: addIntegrationType,
          capabilities: addCapabilities,
          enabled: addEnabled,
        });
      } else if (provider) {
        await apiPost("/api/marketing/ai/providers/", {
          provider: provider.id,
          enabled: addEnabled,
          credentials: addCredential.trim(),
          model_override: addModel.trim(),
        });
      }
      toast.success(
        `${custom ? addCustomName.trim() : provider?.display_name} added to this client.`,
      );
      setAddOpen(false);
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not add the provider.");
    } finally {
      setBusy(null);
    }
  };

  const toggleProvider = async (provider: CatalogueProvider, enabled: boolean) => {
    setBusy(`provider:${provider.id}`);
    try {
      const existing = connectedFor(provider.id);
      if (existing) {
        await api(`/api/marketing/ai/providers/${existing.id}/`, {
          method: "PATCH",
          body: { enabled },
        });
      } else {
        await apiPost("/api/marketing/ai/providers/", {
          provider: provider.id,
          enabled,
          credentials: keys[provider.id] ?? "",
        });
      }
      toast.success(`${provider.display_name} ${enabled ? "enabled" : "disabled"}.`);
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not update provider.");
    } finally {
      setBusy(null);
    }
  };

  const saveKey = async (provider: CatalogueProvider) => {
    const credential = (keys[provider.id] ?? "").trim();
    if (!credential) return;
    setBusy(`provider:${provider.id}`);
    try {
      const existing = connectedFor(provider.id);
      if (existing) {
        await api(`/api/marketing/ai/providers/${existing.id}/`, {
          method: "PATCH",
          body: { credentials: credential },
        });
      } else {
        await apiPost("/api/marketing/ai/providers/", {
          provider: provider.id,
          enabled: false,
          credentials: credential,
        });
      }
      setKeys((current) => ({ ...current, [provider.id]: "" }));
      toast.success(`${provider.display_name} key saved securely.`);
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save the provider key.");
    } finally {
      setBusy(null);
    }
  };

  const clearKey = async (provider: CatalogueProvider, workspaceProvider: WorkspaceProvider) => {
    setBusy(`provider:${provider.id}`);
    try {
      await api(`/api/marketing/ai/providers/${workspaceProvider.id}/`, {
        method: "PATCH",
        body: { credentials: "", enabled: false },
      });
      toast.success(`${provider.display_name} key removed and provider disabled.`);
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not remove the provider key.");
    } finally {
      setBusy(null);
    }
  };

  const testProvider = async (workspaceProvider: WorkspaceProvider) => {
    setBusy(`health:${workspaceProvider.id}`);
    try {
      await apiPost(`/api/marketing/ai/providers/${workspaceProvider.id}/test/`, {});
      toast.success(`${workspaceProvider.provider_name} connection verified.`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Provider connection failed.");
    } finally {
      await load();
      setBusy(null);
    }
  };

  const updateDraft = (capability: string, change: Partial<RouteDraft>) => {
    setRouteDrafts((current) => ({
      ...current,
      [capability]: {
        providerIds: current[capability]?.providerIds ?? [],
        strategy: current[capability]?.strategy ?? "FAILOVER",
        dirty: true,
        ...change,
      },
    }));
  };

  const toggleRouteProvider = (capability: string, providerId: string, enabled: boolean) => {
    const current = routeDrafts[capability]?.providerIds ?? [];
    updateDraft(capability, {
      providerIds: enabled
        ? [...current.filter((id) => id !== providerId), providerId]
        : current.filter((id) => id !== providerId),
    });
  };

  const toggleAddedCapability = (capability: string, enabled: boolean) => {
    setAddCapabilities((current) =>
      enabled
        ? [...current.filter((value) => value !== capability), capability]
        : current.filter((value) => value !== capability),
    );
  };

  const moveRouteProvider = (capability: string, providerId: string, direction: -1 | 1) => {
    const ids = [...(routeDrafts[capability]?.providerIds ?? [])];
    const from = ids.indexOf(providerId);
    const to = from + direction;
    if (from < 0 || to < 0 || to >= ids.length) return;
    const [moved] = ids.splice(from, 1);
    if (!moved) return;
    ids.splice(to, 0, moved);
    updateDraft(capability, { providerIds: ids });
  };

  const saveRoute = async (capability: string) => {
    const draft = routeDrafts[capability];
    if (!draft) return;
    setBusy(`route:${capability}`);
    try {
      await apiPost("/api/marketing/ai/routes/replace-set/", {
        capability,
        strategy: draft.strategy,
        routes: draft.providerIds.map((provider, index) => ({
          provider,
          priority: (index + 1) * 10,
        })),
      });
      toast.success(`${humanize(capability)} route saved.`);
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save the route.");
    } finally {
      setBusy(null);
    }
  };

  const filteredCatalogue = useMemo(() => {
    const needle = providerFilter.trim().toLowerCase();
    if (!needle) return catalogue;
    return catalogue.filter((provider) =>
      [provider.display_name, provider.key, ...provider.capabilities]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [catalogue, providerFilter]);

  const enabledProviders = mine.filter((provider) => provider.enabled);
  const healthyProviders = enabledProviders.filter((provider) => provider.last_health_ok === true);
  const routedCapabilities = capabilities.filter(
    (capability) => (resolved[capability.value]?.providers.length ?? 0) > 0,
  );
  const missingCapabilities = capabilities.filter(
    (capability) => (resolved[capability.value]?.providers.length ?? 0) === 0,
  );
  const totalCalls = usageSummary.reduce((sum, row) => sum + Number(row.calls || 0), 0);
  const totalSpend = usageSummary.reduce((sum, row) => sum + Number(row.spend || 0), 0);
  const recentFailures = usage.filter((row) => !row.success).length;
  const averageLatency = usage.length
    ? Math.round(usage.reduce((sum, row) => sum + row.latency_ms, 0) / usage.length)
    : 0;

  if (loading) {
    return (
      <div className="flex min-h-64 items-center justify-center rounded-xl border border-border">
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Loading the Admin console…
        </p>
      </div>
    );
  }

  if (loadError) {
    return (
      <Alert variant="destructive">
        <CircleAlert className="size-4" />
        <AlertTitle>Admin console could not load</AlertTitle>
        <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
          <span>{loadError}</span>
          <Button size="sm" variant="outline" onClick={() => void load()}>
            <RefreshCw className="size-4" /> Retry
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <Tabs
      value={activeTab}
      onValueChange={(value) => onTabChange(value as AIAdminTab)}
      className="space-y-6"
    >
      <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1">
        <TabsTrigger value="overview" className="gap-1.5">
          <Gauge className="size-3.5" /> Overview
        </TabsTrigger>
        <TabsTrigger value="providers" className="gap-1.5">
          <ServerCog className="size-3.5" /> Providers
        </TabsTrigger>
        <TabsTrigger value="routing" className="gap-1.5">
          <RouteIcon className="size-3.5" /> Routing &amp; redundancy
        </TabsTrigger>
        <TabsTrigger value="activity" className="gap-1.5">
          <Activity className="size-3.5" /> Activity
        </TabsTrigger>
      </TabsList>

      <TabsContent value="overview" className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            title="Enabled providers"
            value={String(enabledProviders.length)}
            hint={`${catalogue.length} installed integration${catalogue.length === 1 ? "" : "s"} available`}
            icon={<ServerCog className="size-4" />}
          />
          <MetricCard
            title="Healthy now"
            value={`${healthyProviders.length}/${enabledProviders.length}`}
            hint="Based on the latest authenticated connection check"
            icon={<ShieldCheck className="size-4" />}
          />
          <MetricCard
            title="Capabilities routed"
            value={`${routedCapabilities.length}/${capabilities.length}`}
            hint="Each capability owns an independent provider set"
            icon={<Network className="size-4" />}
          />
          <MetricCard
            title="Recorded calls"
            value={String(totalCalls)}
            hint={`${money(totalSpend)} attributed spend`}
            icon={<Activity className="size-4" />}
          />
        </div>

        {missingCapabilities.length ? (
          <Alert>
            <CircleAlert className="size-4" />
            <AlertTitle>{missingCapabilities.length} capabilities are not routed</AlertTitle>
            <AlertDescription className="mt-2 flex flex-wrap items-center justify-between gap-3">
              <span>{missingCapabilities.map((capability) => capability.label).join(", ")}</span>
              <Button size="sm" variant="outline" onClick={() => onTabChange("routing")}>
                Complete routing
              </Button>
            </AlertDescription>
          </Alert>
        ) : (
          <Alert>
            <CheckCircle2 className="size-4 text-success" />
            <AlertTitle>Every installed capability has an active route</AlertTitle>
            <AlertDescription>
              Product workflows remain provider-neutral; this policy decides execution.
            </AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Live routing readiness</CardTitle>
            <CardDescription>
              Providers the router can use now, after availability and workspace enablement.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            {capabilities.map((capability) => {
              const active = resolved[capability.value];
              return (
                <div key={capability.value} className="rounded-xl border border-border p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium">{capability.label}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {active?.providers.length
                          ? active.providers.join(" → ")
                          : "No active provider"}
                      </p>
                    </div>
                    <Badge variant={active?.providers.length ? "secondary" : "destructive"}>
                      {active?.providers.length ? active.strategy : "Unrouted"}
                    </Badge>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="providers" className="space-y-5">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <p className="label-eyebrow">AI provider catalogue</p>
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
              Onboard installed or custom AI integrations with the model and credentials you choose.
              There is no provider limit; product features request capabilities instead of vendors.
            </p>
          </div>
          <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
            <Input
              className="w-full sm:w-64"
              aria-label="Filter providers"
              placeholder="Find a provider or capability"
              value={providerFilter}
              onChange={(event) => setProviderFilter(event.target.value)}
            />
            <Button onClick={openAddProvider}>
              <Plus className="size-4" /> Add provider
            </Button>
          </div>
        </div>

        <Dialog open={addOpen} onOpenChange={setAddOpen}>
          <DialogContent className="max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>Add AI provider</DialogTitle>
              <DialogDescription>
                Choose an installed integration or enter any custom AI provider. You choose its
                protocol, capabilities and model; Scaleezy does not preselect them.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="add-ai-provider">Provider</Label>
                <Select value={addProviderId} onValueChange={setAddProviderId}>
                  <SelectTrigger id="add-ai-provider">
                    <SelectValue placeholder="Choose an installed integration or custom AI" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={CUSTOM_PROVIDER_VALUE}>
                      Custom AI provider — enter your own
                    </SelectItem>
                    {availableToAdd.map((provider) => (
                      <SelectItem key={provider.id} value={provider.id}>
                        {provider.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {addProviderId === CUSTOM_PROVIDER_VALUE ? (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="add-ai-protocol">API protocol</Label>
                    <Select
                      value={addIntegrationType}
                      onValueChange={(value) => {
                        setAddIntegrationType(value);
                        setAddCapabilities((current) =>
                          value === "OPENAI_COMPATIBLE"
                            ? current.filter(
                                (capability) =>
                                  capability !== "VIDEO" && capability !== "VIDEO_ANALYSIS",
                              )
                            : current,
                        );
                      }}
                    >
                      <SelectTrigger id="add-ai-protocol">
                        <SelectValue placeholder="Choose the endpoint protocol" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="OPENAI_COMPATIBLE">OpenAI-compatible API</SelectItem>
                        <SelectItem value="SCALEEZY_JSON">Scaleezy universal JSON API</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="add-ai-name">Provider name</Label>
                    <Input
                      id="add-ai-name"
                      placeholder="Your provider name"
                      value={addCustomName}
                      onChange={(event) => setAddCustomName(event.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="add-ai-base-url">API base URL</Label>
                    <Input
                      id="add-ai-base-url"
                      inputMode="url"
                      placeholder="https://provider.example.com/v1"
                      value={addBaseUrl}
                      onChange={(event) => setAddBaseUrl(event.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      {addIntegrationType === "SCALEEZY_JSON"
                        ? "Enter the exact public HTTPS endpoint that accepts Scaleezy's capability, model and brief JSON contract."
                        : "Enter the public HTTPS API base URL, normally ending in /v1."}
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label>Capabilities this AI supports</Label>
                    <div className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-2">
                      {capabilities.map((capability) => {
                        const unavailable =
                          addIntegrationType === "OPENAI_COMPATIBLE" &&
                          (capability.value === "VIDEO" || capability.value === "VIDEO_ANALYSIS");
                        return (
                          <div key={capability.value} className="flex items-start gap-2">
                            <Checkbox
                              id={`add-capability-${capability.value}`}
                              checked={addCapabilities.includes(capability.value)}
                              disabled={!addIntegrationType || unavailable}
                              onCheckedChange={(checked) =>
                                toggleAddedCapability(capability.value, checked === true)
                              }
                            />
                            <Label
                              htmlFor={`add-capability-${capability.value}`}
                              className="text-sm font-normal"
                            >
                              {capability.label}
                              {unavailable ? " — use universal JSON" : ""}
                            </Label>
                          </div>
                        );
                      })}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Select only functions exposed by this endpoint. Each selected function becomes
                      available in Routing &amp; redundancy; no route is selected automatically.
                    </p>
                  </div>
                </>
              ) : null}

              <div className="space-y-2">
                <Label htmlFor="add-ai-key">API key</Label>
                <Input
                  id="add-ai-key"
                  type="password"
                  autoComplete="new-password"
                  placeholder={
                    addProviderId === CUSTOM_PROVIDER_VALUE
                      ? "API key or token, if this endpoint requires one"
                      : "Optional when a platform key is available"
                  }
                  value={addCredential}
                  onChange={(event) => setAddCredential(event.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="add-ai-model">Model</Label>
                <Input
                  id="add-ai-model"
                  placeholder="Enter the exact model identifier"
                  value={addModel}
                  onChange={(event) => setAddModel(event.target.value)}
                />
              </div>

              <div className="flex items-center justify-between rounded-lg border border-border p-3">
                <div>
                  <Label htmlFor="enable-added-ai">Enable after adding</Label>
                  <p className="text-xs text-muted-foreground">
                    You can route capabilities after the provider is enabled.
                  </p>
                </div>
                <Switch id="enable-added-ai" checked={addEnabled} onCheckedChange={setAddEnabled} />
              </div>
            </div>

            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline">Cancel</Button>
              </DialogClose>
              <Button
                disabled={
                  !addProviderId ||
                  !addModel.trim() ||
                  (addProviderId === CUSTOM_PROVIDER_VALUE &&
                    (!addCustomName.trim() ||
                      !addBaseUrl.trim() ||
                      !addIntegrationType ||
                      addCapabilities.length === 0)) ||
                  busy === "add-provider"
                }
                onClick={() => void addProvider()}
              >
                {busy === "add-provider" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Plus className="size-4" />
                )}
                Add provider
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {!catalogue.length ? (
          <Alert>
            <CircleAlert className="size-4" />
            <AlertTitle>No provider adapters are installed</AlertTitle>
            <AlertDescription>
              A platform operator must install at least one provider adapter before a workspace can
              configure credentials or routes.
            </AlertDescription>
          </Alert>
        ) : !filteredCatalogue.length ? (
          <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
            No installed provider matches that filter.
          </p>
        ) : (
          <div className="space-y-3">
            {filteredCatalogue.map((provider) => {
              const workspaceProvider = connectedFor(provider.id);
              const providerBusy = busy === `provider:${provider.id}`;
              const healthBusy = workspaceProvider && busy === `health:${workspaceProvider.id}`;
              return (
                <Card key={provider.id}>
                  <CardHeader className="pb-4">
                    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
                      <div className="min-w-0">
                        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                          <span>{provider.display_name}</span>
                          {workspaceProvider?.last_health_ok === true ? (
                            <Badge variant="secondary" className="gap-1 text-success">
                              <CheckCircle2 className="size-3" /> Connected
                            </Badge>
                          ) : workspaceProvider?.last_health_ok === false ? (
                            <Badge variant="destructive" className="gap-1">
                              <XCircle className="size-3" /> Connection failed
                            </Badge>
                          ) : null}
                        </CardTitle>
                        <CardDescription className="mt-1">
                          {provider.capabilities.map(humanize).join(" · ") ||
                            "No capabilities declared"}
                        </CardDescription>
                      </div>
                      <div className="flex items-center gap-2">
                        <Label htmlFor={`provider-${provider.id}`} className="text-xs font-normal">
                          {workspaceProvider?.enabled ? "Enabled" : "Disabled"}
                        </Label>
                        <Switch
                          id={`provider-${provider.id}`}
                          checked={!!workspaceProvider?.enabled}
                          disabled={
                            providerBusy || !provider.adapter_installed || !provider.is_available
                          }
                          onCheckedChange={(value) => void toggleProvider(provider, value)}
                        />
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {!provider.adapter_installed || !provider.is_available ? (
                      <p className="text-sm text-destructive">
                        {!provider.adapter_installed
                          ? "Adapter not installed in this deployment."
                          : "This provider is unavailable at platform level."}
                      </p>
                    ) : null}

                    <div className="flex flex-wrap items-center gap-2">
                      <Input
                        type="password"
                        autoComplete="new-password"
                        className="h-9 w-full max-w-sm"
                        aria-label={`${provider.display_name} API key`}
                        placeholder={
                          workspaceProvider?.has_credentials ? "•••••••• (saved)" : "API key"
                        }
                        value={keys[provider.id] ?? ""}
                        onChange={(event) =>
                          setKeys((current) => ({
                            ...current,
                            [provider.id]: event.target.value,
                          }))
                        }
                      />
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={providerBusy || !(keys[provider.id] ?? "").trim()}
                        onClick={() => void saveKey(provider)}
                      >
                        <KeyRound className="size-4" /> Save key
                      </Button>
                      {workspaceProvider?.has_credentials ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={providerBusy}
                          onClick={() => void clearKey(provider, workspaceProvider)}
                        >
                          Remove key
                        </Button>
                      ) : null}
                      {workspaceProvider ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={providerBusy || !!healthBusy}
                          onClick={() => void testProvider(workspaceProvider)}
                        >
                          {healthBusy ? (
                            <Loader2 className="size-4 animate-spin" />
                          ) : (
                            <Plug className="size-4" />
                          )}
                          Test connection
                        </Button>
                      ) : null}
                    </div>

                    {workspaceProvider ? (
                      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
                        <span>Last check: {when(workspaceProvider.last_health_check_at)}</span>
                        <span>
                          Model:{" "}
                          {workspaceProvider.model_override ||
                            provider.default_model ||
                            "Provider default"}
                        </span>
                        {workspaceProvider.last_error ? (
                          <span className="text-destructive">{workspaceProvider.last_error}</span>
                        ) : null}
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </TabsContent>

      <TabsContent value="routing" className="space-y-5">
        <div>
          <p className="label-eyebrow">Capability routing</p>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Select as many enabled providers as needed for each purpose, order them, choose a
            strategy, then save the complete route atomically.
          </p>
        </div>

        <div className="space-y-4">
          {capabilities.map((capability) => {
            const draft = routeDrafts[capability.value] ?? {
              providerIds: [],
              strategy: "FAILOVER",
              dirty: false,
            };
            const capable = catalogue.filter(
              (provider) =>
                provider.is_available &&
                provider.adapter_installed &&
                provider.capabilities.includes(capability.value),
            );
            const routeBusy = busy === `route:${capability.value}`;

            return (
              <Card key={capability.value}>
                <CardHeader>
                  <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                    <div>
                      <CardTitle className="text-base">{capability.label}</CardTitle>
                      <CardDescription className="mt-1">
                        {draft.providerIds.length
                          ? `${draft.providerIds.length} provider${draft.providerIds.length === 1 ? "" : "s"} selected. Execution follows the order below.`
                          : "No provider selected for this capability."}
                      </CardDescription>
                    </div>
                    <Select
                      value={draft.strategy}
                      disabled={routeBusy || !draft.providerIds.length}
                      onValueChange={(strategy) => updateDraft(capability.value, { strategy })}
                    >
                      <SelectTrigger
                        className="w-full sm:w-56"
                        aria-label={`${capability.label} routing strategy`}
                      >
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
                </CardHeader>
                <CardContent className="space-y-3">
                  {!capable.length ? (
                    <p className="rounded-lg border border-dashed border-border p-5 text-sm text-muted-foreground">
                      No installed provider adapter declares this capability yet.
                    </p>
                  ) : (
                    capable.map((provider) => {
                      const selectedIndex = draft.providerIds.indexOf(provider.id);
                      const selected = selectedIndex >= 0;
                      const enabled = !!connectedFor(provider.id)?.enabled;
                      return (
                        <div
                          key={provider.id}
                          className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-lg border border-border bg-background px-3 py-2.5"
                        >
                          <Checkbox
                            id={`${capability.value}-${provider.id}`}
                            checked={selected}
                            disabled={routeBusy || (!enabled && !selected)}
                            onCheckedChange={(value) =>
                              toggleRouteProvider(capability.value, provider.id, value === true)
                            }
                          />
                          <Label
                            htmlFor={`${capability.value}-${provider.id}`}
                            className="min-w-0 cursor-pointer text-sm font-normal"
                          >
                            <span className="block truncate">{provider.display_name}</span>
                            <span className="block text-xs text-muted-foreground">
                              {selected
                                ? `Priority ${selectedIndex + 1}${enabled ? "" : " · provider disabled"}`
                                : enabled
                                  ? "Available to add"
                                  : "Enable this provider in the Providers tab first"}
                            </span>
                          </Label>
                          {selected ? (
                            <div className="flex gap-1">
                              <Button
                                type="button"
                                size="icon"
                                variant="ghost"
                                className="size-8"
                                aria-label={`Move ${provider.display_name} up`}
                                disabled={routeBusy || selectedIndex === 0}
                                onClick={() => moveRouteProvider(capability.value, provider.id, -1)}
                              >
                                <ArrowUp className="size-4" />
                              </Button>
                              <Button
                                type="button"
                                size="icon"
                                variant="ghost"
                                className="size-8"
                                aria-label={`Move ${provider.display_name} down`}
                                disabled={
                                  routeBusy || selectedIndex === draft.providerIds.length - 1
                                }
                                onClick={() => moveRouteProvider(capability.value, provider.id, 1)}
                              >
                                <ArrowDown className="size-4" />
                              </Button>
                            </div>
                          ) : null}
                        </div>
                      );
                    })
                  )}

                  <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
                    <p className="text-xs text-muted-foreground">
                      {draft.strategy === "BEST_OF"
                        ? "Best of runs every selected provider and keeps the highest-scoring result."
                        : draft.strategy === "ROUND_ROBIN"
                          ? "Round robin rotates the first provider while retaining failover."
                          : "Failover tries providers in priority order until one succeeds."}
                    </p>
                    <Button
                      size="sm"
                      disabled={routeBusy || !draft.dirty}
                      onClick={() => void saveRoute(capability.value)}
                    >
                      {routeBusy ? <Loader2 className="size-4 animate-spin" /> : null}
                      Save route
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </TabsContent>

      <TabsContent value="activity" className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            title="Total calls"
            value={String(totalCalls)}
            hint="All recorded provider attempts"
            icon={<Activity className="size-4" />}
          />
          <MetricCard
            title="Attributed spend"
            value={money(totalSpend)}
            hint="Across every provider and capability"
            icon={<Gauge className="size-4" />}
          />
          <MetricCard
            title="Recent failures"
            value={String(recentFailures)}
            hint={`Across ${usage.length} recent attempts`}
            icon={<XCircle className="size-4" />}
          />
          <MetricCard
            title="Recent latency"
            value={`${averageLatency} ms`}
            hint="Average of the visible activity"
            icon={<Network className="size-4" />}
          />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Usage by provider and capability</CardTitle>
            <CardDescription>Workspace-scoped calls and attributed provider cost.</CardDescription>
          </CardHeader>
          <CardContent>
            {!usageSummary.length ? (
              <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                No AI usage has been recorded for this client yet.
              </p>
            ) : (
              <div className="space-y-2">
                {usageSummary.map((row) => (
                  <div
                    key={`${row.provider__key ?? "removed"}-${row.capability}`}
                    className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center"
                  >
                    <div>
                      <p className="text-sm font-medium">
                        {row.provider__key ?? "Removed provider"}
                      </p>
                      <p className="text-xs text-muted-foreground">{humanize(row.capability)}</p>
                    </div>
                    <p className="text-sm text-muted-foreground">{row.calls} calls</p>
                    <p className="text-sm font-medium">{money(Number(row.spend || 0))}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent provider activity</CardTitle>
            <CardDescription>
              Every attempt is logged, including failover and best-of candidates.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!usage.length ? (
              <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                Activity will appear after the first AI-backed task.
              </p>
            ) : (
              <div className="space-y-2">
                {usage.slice(0, 25).map((row) => (
                  <div
                    key={row.id}
                    className="grid gap-2 rounded-lg border border-border p-3 lg:grid-cols-[auto_minmax(0,1fr)_auto_auto] lg:items-center"
                  >
                    {row.success ? (
                      <CheckCircle2 className="size-4 text-success" />
                    ) : (
                      <XCircle className="size-4 text-destructive" />
                    )}
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {row.provider_key ?? "Removed provider"} · {humanize(row.capability)}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {row.error ||
                          `${humanize(row.strategy || "failover")}${row.selected ? " · selected" : " · candidate"}`}
                      </p>
                    </div>
                    <p className="text-xs text-muted-foreground">{row.latency_ms} ms</p>
                    <p className="text-xs text-muted-foreground">{when(row.created_at)}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  );
}
