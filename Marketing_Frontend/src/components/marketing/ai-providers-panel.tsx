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
  configured_models?: string[];
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
  model_override?: string;
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
  targetKeys: string[];
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

function sameValues(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value) => right.includes(value));
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
  const [providerCapabilityDrafts, setProviderCapabilityDrafts] = useState<
    Record<string, string[]>
  >({});
  const [providerModelDrafts, setProviderModelDrafts] = useState<Record<string, string>>({});
  const [providerModelsDrafts, setProviderModelsDrafts] = useState<Record<string, string[]>>({});
  const [newModelInputs, setNewModelInputs] = useState<Record<string, string>>({});
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
        targetKeys: members.map((row) => `${row.provider}::${row.model_override || ""}`),
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
      setProviderCapabilityDrafts(
        Object.fromEntries(providerRows.map((row) => [row.provider, row.capabilities ?? []])),
      );
      setProviderModelDrafts(
        Object.fromEntries(providerRows.map((row) => [row.provider, row.model_override ?? ""])),
      );
      setProviderModelsDrafts(
        Object.fromEntries(
          providerRows.map((row) => {
            const models =
              row.configured_models && row.configured_models.length > 0
                ? row.configured_models
                : row.model_override
                  ? [row.model_override]
                  : [];
            return [row.provider, models];
          }),
        ),
      );
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

  const selectedProviderToAdd = availableToAdd.find((row) => row.id === addProviderId);

  const assignableCapabilities = useCallback(
    (provider: CatalogueProvider) => {
      if (provider.integration_type === "SCALEEZY_JSON") {
        return capabilities.map((capability) => capability.value);
      }
      if (
        provider.integration_type === "OPENAI_COMPATIBLE" ||
        provider.key === "openrouter" ||
        provider.key === "together"
      ) {
        return capabilities
          .map((capability) => capability.value)
          .filter((value) => value !== "VIDEO" && value !== "VIDEO_ANALYSIS");
      }
      return provider.capabilities;
    },
    [capabilities],
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
          capabilities: addCapabilities,
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
        openAddProvider();
        setAddProviderId(provider.id);
        return;
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
        openAddProvider();
        setAddProviderId(provider.id);
        setAddCredential(credential);
        return;
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

  const toggleProviderCapability = (providerId: string, capability: string, enabled: boolean) => {
    setProviderCapabilityDrafts((current) => {
      const selected = current[providerId] ?? [];
      return {
        ...current,
        [providerId]: enabled
          ? [...selected.filter((value) => value !== capability), capability]
          : selected.filter((value) => value !== capability),
      };
    });
  };

  const addModelToProvider = (providerId: string) => {
    const val = (newModelInputs[providerId] || "").trim();
    if (!val) return;
    setProviderModelsDrafts((current) => {
      const existing = current[providerId] || [];
      if (existing.includes(val)) return current;
      return { ...current, [providerId]: [...existing, val] };
    });
    setNewModelInputs((current) => ({ ...current, [providerId]: "" }));
  };

  const removeModelFromProvider = (providerId: string, modelToRemove: string) => {
    setProviderModelsDrafts((current) => {
      const existing = current[providerId] || [];
      return { ...current, [providerId]: existing.filter((m) => m !== modelToRemove) };
    });
  };

  const saveProviderTasks = async (
    provider: CatalogueProvider,
    workspaceProvider: WorkspaceProvider,
  ) => {
    setBusy(`provider:${provider.id}`);
    try {
      const models =
        providerModelsDrafts[provider.id] ??
        (workspaceProvider.configured_models && workspaceProvider.configured_models.length > 0
          ? workspaceProvider.configured_models
          : workspaceProvider.model_override
            ? [workspaceProvider.model_override]
            : []);
      const primaryModel = (models[0] ?? providerModelDrafts[provider.id] ?? "").trim();
      await api(`/api/marketing/ai/providers/${workspaceProvider.id}/`, {
        method: "PATCH",
        body: {
          capabilities: providerCapabilityDrafts[provider.id] ?? [],
          model_override: primaryModel,
          configured_models: models,
        },
      });
      toast.success(`${provider.display_name} models and tasks saved.`);
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save provider tasks.");
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
        targetKeys: current[capability]?.targetKeys ?? [],
        strategy: current[capability]?.strategy ?? "FAILOVER",
        dirty: true,
        ...change,
      },
    }));
  };

  const toggleRouteTarget = (capability: string, targetKey: string, enabled: boolean) => {
    const current = routeDrafts[capability]?.targetKeys ?? [];
    updateDraft(capability, {
      targetKeys: enabled
        ? [...current.filter((k) => k !== targetKey), targetKey]
        : current.filter((k) => k !== targetKey),
    });
  };

  const toggleAddedCapability = (capability: string, enabled: boolean) => {
    setAddCapabilities((current) =>
      enabled
        ? [...current.filter((value) => value !== capability), capability]
        : current.filter((value) => value !== capability),
    );
  };

  const moveRouteTarget = (capability: string, targetKey: string, direction: -1 | 1) => {
    const keys = [...(routeDrafts[capability]?.targetKeys ?? [])];
    const from = keys.indexOf(targetKey);
    const to = from + direction;
    if (from < 0 || to < 0 || to >= keys.length) return;
    const [moved] = keys.splice(from, 1);
    if (!moved) return;
    keys.splice(to, 0, moved);
    updateDraft(capability, { targetKeys: keys });
  };

  const saveRoute = async (capability: string) => {
    const draft = routeDrafts[capability];
    if (!draft) return;
    setBusy(`route:${capability}`);
    try {
      await apiPost("/api/marketing/ai/routes/replace-set/", {
        capability,
        strategy: draft.strategy,
        routes: draft.targetKeys.map((targetKey, index) => {
          const [providerId, model] = targetKey.split("::");
          return {
            provider: providerId,
            model_override: model || "",
            priority: (index + 1) * 10,
          };
        }),
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
                <Select
                  value={addProviderId}
                  onValueChange={(value) => {
                    setAddProviderId(value);
                    setAddCapabilities([]);
                    setAddIntegrationType("");
                  }}
                >
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
                </>
              ) : null}

              {addProviderId ? (
                <>
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
                    <Label htmlFor="add-ai-model">Exact model name</Label>
                    <Input
                      id="add-ai-model"
                      placeholder="Enter the exact model identifier"
                      value={addModel}
                      onChange={(event) => setAddModel(event.target.value)}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>Tasks this model will perform</Label>
                    <div className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-2">
                      {capabilities.map((capability) => {
                        const supported =
                          addProviderId === CUSTOM_PROVIDER_VALUE
                            ? addIntegrationType === "SCALEEZY_JSON" ||
                              (addIntegrationType === "OPENAI_COMPATIBLE" &&
                                capability.value !== "VIDEO" &&
                                capability.value !== "VIDEO_ANALYSIS")
                            : !!selectedProviderToAdd?.capabilities.includes(capability.value);
                        return (
                          <div key={capability.value} className="flex items-start gap-2">
                            <Checkbox
                              id={`add-capability-${capability.value}`}
                              checked={addCapabilities.includes(capability.value)}
                              disabled={!supported}
                              onCheckedChange={(checked) =>
                                toggleAddedCapability(capability.value, checked === true)
                              }
                            />
                            <Label
                              htmlFor={`add-capability-${capability.value}`}
                              className="text-sm font-normal"
                            >
                              {capability.label}
                              {!supported && addProviderId === CUSTOM_PROVIDER_VALUE
                                ? " — choose a compatible protocol"
                                : !supported
                                  ? " — not supported by this adapter"
                                  : ""}
                            </Label>
                          </div>
                        );
                      })}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Nothing is preselected. Only checked tasks become available in Routing &amp;
                      redundancy.
                    </p>
                  </div>

                  <div className="flex items-center justify-between rounded-lg border border-border p-3">
                    <div>
                      <Label htmlFor="enable-added-ai">Enable after adding</Label>
                      <p className="text-xs text-muted-foreground">
                        Routes remain empty until you choose them in Routing &amp; redundancy.
                      </p>
                    </div>
                    <Switch
                      id="enable-added-ai"
                      checked={addEnabled}
                      onCheckedChange={setAddEnabled}
                    />
                  </div>
                </>
              ) : (
                <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
                  Choose an installed integration or “Custom AI provider” above. The complete model,
                  connection and task controls will then appear here.
                </p>
              )}
            </div>

            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline">Cancel</Button>
              </DialogClose>
              <Button
                disabled={
                  !addProviderId ||
                  !addModel.trim() ||
                  addCapabilities.length === 0 ||
                  (addProviderId === CUSTOM_PROVIDER_VALUE &&
                    (!addCustomName.trim() || !addBaseUrl.trim() || !addIntegrationType)) ||
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
              const supportedTasks = assignableCapabilities(provider);
              const taskDraft =
                providerCapabilityDrafts[provider.id] ?? workspaceProvider?.capabilities ?? [];
              const modelDraft =
                providerModelDrafts[provider.id] ?? workspaceProvider?.model_override ?? "";
              const configurationDirty =
                !!workspaceProvider &&
                (!sameValues(taskDraft, workspaceProvider.capabilities) ||
                  modelDraft !== workspaceProvider.model_override);
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
                          {workspaceProvider
                            ? `Assigned tasks: ${workspaceProvider.capabilities.map(humanize).join(" · ") || "None"}`
                            : `Supported tasks: ${provider.capabilities.map(humanize).join(" · ") || "None"}`}
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
                      <div className="space-y-4 rounded-lg border border-border p-4">
                        <div>
                          <Label>Tasks this provider performs</Label>
                          <p className="text-xs text-muted-foreground">
                            Choose what this provider gateway may do. Deselecting removes all its models from that capability route.
                          </p>
                        </div>
                        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                          {capabilities.map((capability) => {
                            const supported = supportedTasks.includes(capability.value);
                            return (
                              <div key={capability.value} className="flex items-start gap-2">
                                <Checkbox
                                  id={`provider-${provider.id}-capability-${capability.value}`}
                                  checked={taskDraft.includes(capability.value)}
                                  disabled={providerBusy || !supported}
                                  onCheckedChange={(checked) =>
                                    toggleProviderCapability(
                                      provider.id,
                                      capability.value,
                                      checked === true,
                                    )
                                  }
                                />
                                <Label
                                  htmlFor={`provider-${provider.id}-capability-${capability.value}`}
                                  className="text-sm font-normal"
                                >
                                  {capability.label}
                                  {!supported ? " — unavailable" : ""}
                                </Label>
                              </div>
                            );
                          })}
                        </div>

                        {/* MULTI-MODEL CONFIGURATION */}
                        <div className="space-y-2.5 border-t border-border pt-3">
                          <div>
                            <Label>Configured Gateway Models</Label>
                            <p className="text-xs text-muted-foreground">
                              Add models available under this provider key. Each model appears as an individual routing target in Capability Routing.
                            </p>
                          </div>
                          <div className="flex flex-wrap items-center gap-1.5 min-h-[32px]">
                            {(providerModelsDrafts[provider.id] || []).map((m) => (
                              <span
                                key={m}
                                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-secondary/80 px-2.5 py-1 text-xs font-medium text-foreground"
                              >
                                <span>{m}</span>
                                <button
                                  type="button"
                                  onClick={() => removeModelFromProvider(provider.id, m)}
                                  className="text-muted-foreground hover:text-destructive text-sm leading-none ml-1"
                                  title="Remove model"
                                >
                                  ×
                                </button>
                              </span>
                            ))}
                            {!(providerModelsDrafts[provider.id] || []).length && (
                              <span className="text-xs text-muted-foreground italic">No models configured yet.</span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <Input
                              placeholder="Enter model name (e.g. minimax/minimax-m3, stealth/ox-alpha)"
                              value={newModelInputs[provider.id] || ""}
                              disabled={providerBusy}
                              onChange={(e) =>
                                setNewModelInputs((current) => ({
                                  ...current,
                                  [provider.id]: e.target.value,
                                }))
                              }
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  e.preventDefault();
                                  addModelToProvider(provider.id);
                                }
                              }}
                              className="h-8 text-xs"
                            />
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="h-8 text-xs gap-1 shrink-0"
                              disabled={providerBusy || !(newModelInputs[provider.id] || "").trim()}
                              onClick={() => addModelToProvider(provider.id)}
                            >
                              <Plus className="size-3.5" /> Add model
                            </Button>
                          </div>
                          <div className="flex justify-end pt-2">
                            <Button
                              type="button"
                              disabled={providerBusy}
                              onClick={() => void saveProviderTasks(provider, workspaceProvider)}
                            >
                              {providerBusy ? <Loader2 className="size-4 animate-spin" /> : null}
                              Save models &amp; tasks
                            </Button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                          openAddProvider();
                          setAddProviderId(provider.id);
                        }}
                      >
                        <Plus className="size-4" /> Configure model &amp; tasks
                      </Button>
                    )}

                    {workspaceProvider ? (
                      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
                        <span>Last check: {when(workspaceProvider.last_health_check_at)}</span>
                        <span>
                          Models:{" "}
                          {(providerModelsDrafts[provider.id] || []).join(", ") ||
                            workspaceProvider.model_override ||
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
            Select as many enabled providers and models as needed for each purpose, order them by priority, choose a
            failover strategy, then save the complete route atomically.
          </p>
        </div>

        <div className="space-y-4">
          {capabilities.map((capability) => {
            const draft = routeDrafts[capability.value] ?? {
              targetKeys: [],
              strategy: "FAILOVER",
              dirty: false,
            };

            const capableItems: {
              targetKey: string;
              providerId: string;
              providerName: string;
              model: string;
              enabled: boolean;
            }[] = [];

            catalogue.forEach((provider) => {
              const configured = connectedFor(provider.id);
              if (
                provider.is_available &&
                provider.adapter_installed &&
                !!configured &&
                configured.capabilities.includes(capability.value)
              ) {
                const models =
                  configured.configured_models && configured.configured_models.length > 0
                    ? configured.configured_models
                    : configured.model_override
                      ? [configured.model_override]
                      : [provider.default_model || ""];

                models.forEach((m) => {
                  const modelName = (m || "").trim();
                  const targetKey = `${provider.id}::${modelName}`;
                  capableItems.push({
                    targetKey,
                    providerId: provider.id,
                    providerName: provider.display_name,
                    model: modelName,
                    enabled: !!configured.enabled,
                  });
                });
              }
            });

            // Sort candidates: selected items first in order of draft.targetKeys, then alphabetical
            capableItems.sort((left, right) => {
              const leftIndex = draft.targetKeys.indexOf(left.targetKey);
              const rightIndex = draft.targetKeys.indexOf(right.targetKey);
              if (leftIndex >= 0 && rightIndex >= 0) return leftIndex - rightIndex;
              if (leftIndex >= 0) return -1;
              if (rightIndex >= 0) return 1;
              return `${left.providerName} ${left.model}`.localeCompare(
                `${right.providerName} ${right.model}`,
              );
            });

            const routeBusy = busy === `route:${capability.value}`;

            return (
              <Card key={capability.value}>
                <CardHeader>
                  <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                    <div>
                      <CardTitle className="text-base">{capability.label}</CardTitle>
                      <CardDescription className="mt-1">
                        {draft.targetKeys.length
                          ? `${draft.targetKeys.length} target${draft.targetKeys.length === 1 ? "" : "s"} selected. Execution follows the order below.`
                          : "No model selected for this capability."}
                      </CardDescription>
                    </div>
                    <Select
                      value={draft.strategy}
                      disabled={routeBusy || !draft.targetKeys.length}
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
                  {!capableItems.length ? (
                    <p className="rounded-lg border border-dashed border-border p-5 text-sm text-muted-foreground">
                      No configured model is assigned this task yet. Configure models under the Providers tab
                      first.
                    </p>
                  ) : (
                    capableItems.map((item) => {
                      const selectedIndex = draft.targetKeys.indexOf(item.targetKey);
                      const selected = selectedIndex >= 0;
                      return (
                        <div
                          key={item.targetKey}
                          className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-lg border border-border bg-background px-3 py-2.5"
                        >
                          <Checkbox
                            id={`${capability.value}-${item.targetKey}`}
                            checked={selected}
                            disabled={routeBusy || (!item.enabled && !selected)}
                            onCheckedChange={(value) =>
                              toggleRouteTarget(capability.value, item.targetKey, value === true)
                            }
                          />
                          <Label
                            htmlFor={`${capability.value}-${item.targetKey}`}
                            className="min-w-0 cursor-pointer text-sm font-normal"
                          >
                            <span className="flex flex-wrap items-center gap-2 truncate font-medium">
                              <span>{item.providerName}</span>
                              {item.model ? (
                                <span className="rounded bg-secondary px-2 py-0.5 text-xs font-normal text-foreground border border-border/80">
                                  {item.model}
                                </span>
                              ) : null}
                            </span>
                            <span className="block text-xs text-muted-foreground mt-0.5">
                              {selected
                                ? `Priority ${selectedIndex + 1}${item.enabled ? "" : " · provider disabled"}`
                                : item.enabled
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
                                aria-label={`Move ${item.providerName} up`}
                                disabled={routeBusy || selectedIndex === 0}
                                onClick={() => moveRouteTarget(capability.value, item.targetKey, -1)}
                              >
                                <ArrowUp className="size-4" />
                              </Button>
                              <Button
                                type="button"
                                size="icon"
                                variant="ghost"
                                className="size-8"
                                aria-label={`Move ${item.providerName} down`}
                                disabled={
                                  routeBusy || selectedIndex === draft.targetKeys.length - 1
                                }
                                onClick={() => moveRouteTarget(capability.value, item.targetKey, 1)}
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
