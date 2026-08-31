/**
 * One client, everything the platform knows about it, and the controls that
 * act on it.
 *
 * Every control goes through a confirm step and shows the server's message
 * on refusal. Limits are per capability (0 = unlimited); suspend / archive /
 * reactivate take a reason that lands in the audit log; the universal toggles,
 * plan, spend cap and brain recompile each call the one service that owns it.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ArrowLeft,
  Brain,
  Loader2,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  Archive,
  UserPlus,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ClientContentGallery } from "@/components/platform/client-content-gallery";
import {
  ConfirmDialog,
  ErrorNote,
  FlagChips,
  KeyValue,
  MutedNote,
  Panel,
  RecordTable,
  StatusPill,
  type ConfirmRequest,
} from "@/components/platform/shared";
import {
  archiveClient,
  attachUserToClient,
  errorText,
  fetchClient,
  formatAgo,
  formatDateTime,
  reactivateClient,
  recompileClientBrain,
  setClientLimits,
  setClientPlan,
  setClientSpendCap,
  setClientUniversal,
  suspendClient,
  type ClientDetail,
  type UsageSummary,
} from "@/lib/platform";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/platform/clients/$workspaceId")({
  head: () => ({ meta: [{ title: "Client — Scaleezy Platform Console" }] }),
  component: ClientDetailPage,
});

const ROLES = ["OWNER", "ADMIN", "MANAGER", "EDITOR", "VIEWER"] as const;
/** Capabilities offered even when the plan lists none, so a limit can always be set. */
const BASE_CAPABILITIES = ["IMAGE", "VIDEO", "TEXT"];

/* ------------------------------------------------------------------- usage */

function UsageMeter({ used, limit }: { used: number; limit: number }) {
  if (!limit) return null;
  const pct = Math.min(100, Math.round((used / limit) * 100));
  return (
    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-secondary">
      <div
        className={cn(
          "h-full rounded-full",
          pct >= 100 ? "bg-destructive" : pct >= 80 ? "bg-amber-500" : "bg-slate-700",
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function UsagePanelBody({ usage }: { usage: UsageSummary }) {
  if (!usage.subscribed) {
    return (
      <p className="text-sm text-muted-foreground">
        No subscription is attached, so generation is unlimited and there is nothing to meter.
        {usage.message ? ` ${usage.message}` : ""}
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {usage.allowed === false && usage.message ? (
        <p className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-foreground">
          {usage.message}
        </p>
      ) : null}
      {typeof usage.generations_used === "number" ? (
        <div>
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-muted-foreground">Generations this period</span>
            <span className="font-medium">
              {usage.generations_used}
              {usage.generations_limit ? ` / ${usage.generations_limit}` : " · unlimited"}
            </span>
          </div>
          <UsageMeter used={usage.generations_used} limit={usage.generations_limit ?? 0} />
        </div>
      ) : null}
      {(usage.capabilities ?? []).map((cap) => (
        <div key={cap.capability}>
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-muted-foreground">
              {cap.label}
              {cap.overridden ? (
                <span className="ml-1 rounded border border-border px-1 text-[0.5625rem] uppercase">
                  override
                </span>
              ) : null}
            </span>
            <span className="font-medium">
              {cap.used}
              {cap.limit ? ` / ${cap.limit}` : " · unlimited"}
            </span>
          </div>
          <UsageMeter used={cap.used} limit={cap.limit} />
        </div>
      ))}
      {usage.spend !== undefined ? (
        <div>
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-muted-foreground">AI spend</span>
            <span className="font-medium">
              {usage.spend}
              {Number(usage.spend_cap) ? ` / ${usage.spend_cap}` : " · uncapped"}
            </span>
          </div>
          <UsageMeter used={Number(usage.spend)} limit={Number(usage.spend_cap)} />
        </div>
      ) : null}
      {usage.period_end ? (
        <MutedNote>Period ends {formatDateTime(usage.period_end)}.</MutedNote>
      ) : null}
    </div>
  );
}

/* ----------------------------------------------------------------- controls */

function LimitsEditor({
  detail,
  onConfirm,
}: {
  detail: ClientDetail;
  onConfirm: (request: ConfirmRequest) => void;
}) {
  const capabilities = useMemo(() => {
    const fromPlan = (detail.client.usage.capabilities ?? []).map((c) => c.capability);
    return Array.from(new Set([...fromPlan, ...BASE_CAPABILITIES]));
  }, [detail]);

  const current = useMemo(() => {
    const map: Record<string, number> = {};
    for (const cap of detail.client.usage.capabilities ?? []) map[cap.capability] = cap.limit;
    return map;
  }, [detail]);

  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => {
    const next: Record<string, string> = {};
    for (const cap of capabilities) next[cap] = String(current[cap] ?? 0);
    setValues(next);
  }, [capabilities, current]);

  const dirty = capabilities.some((cap) => Number(values[cap] ?? 0) !== (current[cap] ?? 0));
  const subscribed = detail.client.usage.subscribed;

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        const limits: Record<string, number> = {};
        for (const cap of capabilities) {
          const n = Math.max(0, Math.round(Number(values[cap] ?? 0) || 0));
          limits[cap] = n;
        }
        onConfirm({
          title: "Apply these capability limits?",
          description: (
            <ul className="list-disc pl-5">
              {capabilities.map((cap) => (
                <li key={cap}>
                  {cap}: {limits[cap] ? limits[cap] : "unlimited"}
                </li>
              ))}
            </ul>
          ),
          confirmLabel: "Apply limits",
          run: async () => {
            await setClientLimits(detail.client.workspace_id, limits);
            toast.success("Limits updated.");
          },
        });
      }}
    >
      {!subscribed ? (
        <MutedNote>
          No subscription is attached. The server decides whether limits can be set without one;
          a refusal is shown here verbatim.
        </MutedNote>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-3">
        {capabilities.map((cap) => (
          <div key={cap}>
            <Label htmlFor={`limit-${cap}`} className="text-[0.625rem] tracking-wide uppercase">
              {cap}
            </Label>
            <Input
              id={`limit-${cap}`}
              type="number"
              min={0}
              step={1}
              className="mt-1 h-8 text-xs"
              value={values[cap] ?? "0"}
              onChange={(e) => setValues((v) => ({ ...v, [cap]: e.target.value }))}
            />
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between gap-2">
        <MutedNote>0 = unlimited. Per-period, on top of the plan.</MutedNote>
        <Button type="submit" size="sm" disabled={!dirty}>
          Apply limits…
        </Button>
      </div>
    </form>
  );
}

function AttachUser({
  workspaceId,
  clientName,
  onConfirm,
}: {
  workspaceId: string;
  clientName: string;
  onConfirm: (request: ConfirmRequest) => void;
}) {
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<string>("EDITOR");
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const name = username.trim();
        if (!name) return;
        onConfirm({
          title: `Attach ${name} to ${clientName}?`,
          description: `They join as ${role}. The server checks the user exists and the role is allowed.`,
          confirmLabel: "Attach",
          run: async () => {
            const result = await attachUserToClient(workspaceId, name, role);
            toast.success(`${name} attached as ${result.role}.`);
            setUsername("");
          },
        });
      }}
    >
      <div className="min-w-[180px] flex-1">
        <Label htmlFor="attach-username" className="text-[0.625rem] tracking-wide uppercase">
          Username or email
        </Label>
        <Input
          id="attach-username"
          className="mt-1 h-8 text-xs"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
      </div>
      <Select value={role} onValueChange={setRole}>
        <SelectTrigger className="h-8 w-28 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ROLES.map((r) => (
            <SelectItem key={r} value={r}>
              {r}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button type="submit" size="sm" variant="outline" disabled={!username.trim()}>
        <UserPlus className="size-3.5" /> Attach…
      </Button>
    </form>
  );
}

/* --------------------------------------------------------------------- page */

function ClientDetailPage() {
  const { workspaceId } = Route.useParams();
  const [detail, setDetail] = useState<ClientDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [planKey, setPlanKey] = useState("");
  const [spendCap, setSpendCap] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await fetchClient(workspaceId);
      setDetail(next);
      setPlanKey(next.client.plan?.key ?? "");
      setSpendCap(next.client.usage.spend_cap ?? "");
    } catch (e: unknown) {
      setError(errorText(e, "Could not load this client."));
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Every control reloads the page's data after the server accepts it. */
  const ask = (request: ConfirmRequest) =>
    setConfirm({
      ...request,
      run: async (reason) => {
        await request.run(reason);
        await load();
      },
    });

  if (loading && !detail) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-40 rounded-xl" />
        <div className="grid gap-4 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div>
        <BackLink />
        <ErrorNote message={error} />
        <Button className="mt-4" variant="outline" onClick={() => void load()}>
          Try again
        </Button>
      </div>
    );
  }

  if (!detail) return null;
  const { client, brain, universal } = detail;
  const status = client.status;

  return (
    <div>
      <BackLink />
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-xs text-muted-foreground">{client.client_code}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            {client.name || "Untitled client"}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusPill value={status} />
            {client.brand ? <StatusPill value={`brand ${client.brand.status}`.toUpperCase()} /> : null}
            <FlagChips flags={client.flags} />
          </div>
          {client.status_reason ? (
            <p className="mt-2 text-xs text-muted-foreground">Reason on record: {client.status_reason}</p>
          ) : null}
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={cn("size-4", loading && "animate-spin")} /> Refresh
        </Button>
      </header>

      <ErrorNote message={error} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Brand">
          {client.brand ? (
            <>
              <KeyValue label="Name" value={client.brand.name} />
              <KeyValue label="Industry" value={client.brand.industry || "—"} />
              <KeyValue
                label="Website"
                value={
                  client.brand.website ? (
                    <a
                      href={client.brand.website}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="break-all underline-offset-2 hover:underline"
                    >
                      {client.brand.website}
                    </a>
                  ) : (
                    "—"
                  )
                }
              />
              <KeyValue label="Brand status" value={<StatusPill value={client.brand.status} />} />
              <KeyValue label="Created" value={formatDateTime(client.created_at)} />
              <KeyValue label="Last active" value={formatAgo(client.last_active_at)} />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">This workspace has no brand.</p>
          )}
        </Panel>

        <Panel title="Setup & readiness">
          <KeyValue
            label="Onboarding stage"
            value={client.onboarding ? client.onboarding.current_stage.replaceAll("_", " ") : "—"}
          />
          <KeyValue label="Onboarding status" value={client.onboarding?.status ?? "—"} />
          <KeyValue
            label="Readiness"
            value={client.readiness ? `${client.readiness.score}/100 · ${client.readiness.level}` : "—"}
          />
          <KeyValue label="Knowledge sources" value={client.counts.knowledge_sources} />
          <KeyValue label="Confirmed facts" value={client.counts.confirmed_facts} />
          <KeyValue label="Inspirations" value={client.counts.inspirations} />
          <KeyValue label="Rules / preferences" value={`${client.counts.rules} / ${client.counts.preferences}`} />
          <KeyValue label="Team" value={client.counts.team} />
        </Panel>

        <Panel title="Brand Brain">
          {brain ? (
            <>
              <KeyValue label="Version" value={brain.version || "—"} />
              <KeyValue label="Compiled" value={formatDateTime(brain.compiled_at)} />
              <KeyValue
                label="State"
                value={
                  brain.stale ? (
                    <span className="text-amber-700">stale</span>
                  ) : brain.compiled_at ? (
                    "current"
                  ) : (
                    "never compiled"
                  )
                }
              />
              {brain.last_error ? (
                <p className="mt-2 rounded-lg border border-destructive/30 bg-destructive/5 px-2 py-1.5 text-xs text-destructive">
                  {brain.last_error}
                </p>
              ) : null}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">No brain to report — no brand.</p>
          )}
          {client.brand ? (
            <Button
              className="mt-4"
              size="sm"
              variant="outline"
              onClick={() =>
                ask({
                  title: "Recompile this client's Brand Brain?",
                  description:
                    "Rebuilds the compiled brain from the brand's own knowledge, rules and preferences. Nothing is added or removed; the next generation reads the fresh compile.",
                  confirmLabel: "Recompile",
                  run: async () => {
                    await recompileClientBrain(client.workspace_id);
                    toast.success("Brain recompiled.");
                  },
                })
              }
            >
              <Brain className="size-3.5" /> Recompile brain…
            </Button>
          ) : null}
        </Panel>

        <Panel title="Content">
          <KeyValue label="Total" value={client.content.total} />
          {Object.entries(client.content.by_status).map(([key, value]) => (
            <KeyValue key={key} label={key.replaceAll("_", " ").toLowerCase()} value={value} />
          ))}
        </Panel>

        <Panel title="Publishing">
          <KeyValue label="Published" value={client.publishing.published} />
          <KeyValue label="Scheduled" value={client.publishing.scheduled} />
          <KeyValue label="Queued" value={client.publishing.queued} />
          <KeyValue
            label="Failed"
            value={
              <span className={cn(client.publishing.failed > 0 && "text-destructive")}>
                {client.publishing.failed}
              </span>
            }
          />
        </Panel>

        <Panel
          title="Plan & usage"
          description={
            client.plan
              ? `${client.plan.name} (${client.plan.key})${client.subscription_status ? ` · ${client.subscription_status}` : ""}`
              : "No plan attached"
          }
        >
          <UsagePanelBody usage={client.usage} />
        </Panel>
      </div>

      {/* ---------------------------------------------------- control panel */}
      <section className="mt-8 rounded-xl border border-slate-300 bg-slate-100/60 p-5">
        <div className="mb-4">
          <p className="text-[0.6875rem] font-semibold tracking-[0.14em] text-slate-500 uppercase">
            Master controls
          </p>
          <h2 className="mt-1 text-lg font-semibold tracking-tight text-foreground">
            Act on this client
          </h2>
          <p className="text-xs text-muted-foreground">
            Each control asks you to confirm and is recorded in the platform audit log under your
            name. Reasons you type are kept with the record.
          </p>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Lifecycle" description="Suspend stops writes and scheduled work; archive also tears down routing and billing. Reads stay open.">
            <div className="flex flex-wrap gap-2">
              {status === "ACTIVE" ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    ask({
                      title: `Suspend ${client.name}?`,
                      description:
                        "The client can still sign in and read their data, but nothing can be created, edited, generated or published until reactivated.",
                      confirmLabel: "Suspend",
                      destructive: true,
                      reason: { label: "Reason", required: true, placeholder: "Shown to the client" },
                      run: async (reason) => {
                        await suspendClient(client.workspace_id, reason);
                        toast.success("Suspended.");
                      },
                    })
                  }
                >
                  <PauseCircle className="size-3.5" /> Suspend…
                </Button>
              ) : null}
              {status === "SUSPENDED" || status === "ARCHIVED" ? (
                <Button
                  size="sm"
                  onClick={() =>
                    ask({
                      title: `Reactivate ${client.name}?`,
                      description: "Writes, generation and scheduled work resume.",
                      confirmLabel: "Reactivate",
                      reason: { label: "Reason", placeholder: "Optional" },
                      run: async (reason) => {
                        await reactivateClient(client.workspace_id, reason);
                        toast.success("Reactivated.");
                      },
                    })
                  }
                >
                  <PlayCircle className="size-3.5" /> Reactivate…
                </Button>
              ) : null}
              {status !== "ARCHIVED" ? (
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() =>
                    ask({
                      title: `Archive ${client.name}?`,
                      description:
                        "Stops all work, tears down AI routing and billing for this workspace. Data is kept and readable; the client code is never reused.",
                      confirmLabel: "Archive",
                      destructive: true,
                      reason: { label: "Reason", required: true },
                      run: async (reason) => {
                        await archiveClient(client.workspace_id, reason);
                        toast.success("Archived.");
                      },
                    })
                  }
                >
                  <Archive className="size-3.5" /> Archive…
                </Button>
              ) : null}
            </div>
          </Panel>

          <Panel title="Universal layer" description="Scaleezy standards and the curated library. Off means this client's generations never see them.">
            <div className="space-y-3">
              <label className="flex items-center justify-between gap-3 text-sm">
                <span>
                  Standards
                  <span className="block text-xs text-muted-foreground">
                    Craft rules at universal rank, below every brand rule.
                  </span>
                </span>
                <Switch
                  checked={universal.standards_enabled}
                  onCheckedChange={(next) =>
                    ask({
                      title: `${next ? "Enable" : "Disable"} Scaleezy standards for ${client.name}?`,
                      confirmLabel: next ? "Enable" : "Disable",
                      run: async () => {
                        await setClientUniversal(client.workspace_id, { standards: next });
                        toast.success(`Standards ${next ? "enabled" : "disabled"}.`);
                      },
                    })
                  }
                />
              </label>
              <label className="flex items-center justify-between gap-3 text-sm">
                <span>
                  Library
                  <span className="block text-xs text-muted-foreground">
                    Whether the curated references appear in this client's gallery.
                  </span>
                </span>
                <Switch
                  checked={universal.inspirations_enabled}
                  onCheckedChange={(next) =>
                    ask({
                      title: `${next ? "Enable" : "Disable"} the Scaleezy library for ${client.name}?`,
                      confirmLabel: next ? "Enable" : "Disable",
                      run: async () => {
                        await setClientUniversal(client.workspace_id, { inspirations: next });
                        toast.success(`Library ${next ? "enabled" : "disabled"}.`);
                      },
                    })
                  }
                />
              </label>
            </div>
          </Panel>

          <Panel title="Capability limits" description="Overrides on top of the plan's limits for this billing period.">
            <LimitsEditor detail={detail} onConfirm={ask} />
          </Panel>

          <Panel title="Plan & spend cap">
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                const key = planKey.trim();
                if (!key) return;
                ask({
                  title: `Move ${client.name} to plan "${key}"?`,
                  description: "The plan's limits apply from now; usage this period is kept.",
                  confirmLabel: "Change plan",
                  run: async () => {
                    await setClientPlan(client.workspace_id, key);
                    toast.success(`Plan set to ${key}.`);
                  },
                });
              }}
            >
              <div className="min-w-[160px] flex-1">
                <Label htmlFor="plan-key" className="text-[0.625rem] tracking-wide uppercase">
                  Plan key
                </Label>
                <Input
                  id="plan-key"
                  className="mt-1 h-8 text-xs"
                  value={planKey}
                  onChange={(e) => setPlanKey(e.target.value)}
                  placeholder="e.g. starter"
                />
              </div>
              <Button type="submit" size="sm" variant="outline" disabled={!planKey.trim() || planKey.trim() === (client.plan?.key ?? "")}>
                Change plan…
              </Button>
            </form>
            <form
              className="mt-4 flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                const cap = spendCap.trim();
                if (!cap || Number.isNaN(Number(cap)) || Number(cap) < 0) return;
                ask({
                  title: `Set the AI spend cap to ${cap}?`,
                  description: Number(cap) === 0 ? "0 removes the cap." : "Generation stops for the period once spend reaches it.",
                  confirmLabel: "Set spend cap",
                  run: async () => {
                    await setClientSpendCap(client.workspace_id, cap);
                    toast.success("Spend cap updated.");
                  },
                });
              }}
            >
              <div className="min-w-[160px] flex-1">
                <Label htmlFor="spend-cap" className="text-[0.625rem] tracking-wide uppercase">
                  Spend cap (money, per period)
                </Label>
                <Input
                  id="spend-cap"
                  className="mt-1 h-8 text-xs"
                  inputMode="decimal"
                  value={spendCap}
                  onChange={(e) => setSpendCap(e.target.value)}
                  placeholder="0 = uncapped"
                />
              </div>
              <Button
                type="submit"
                size="sm"
                variant="outline"
                disabled={!spendCap.trim() || Number.isNaN(Number(spendCap)) || spendCap.trim() === (client.usage.spend_cap ?? "")}
              >
                Set cap…
              </Button>
            </form>
            <MutedNote>Plan keys must exist on the server; an unknown key is refused, not guessed.</MutedNote>
          </Panel>

          <Panel title="Attach a user" description="The remedy for a colleague blocked by the duplicate-enrolment guard." className="lg:col-span-2">
            <AttachUser workspaceId={client.workspace_id} clientName={client.name} onConfirm={ask} />
          </Panel>
        </div>
      </section>

      {/* ----------------------------------------------------- recent activity */}
      <div className="mt-8 grid gap-4">
        <Panel title="Team" description="Members as the server lists them.">
          <RecordTable rows={detail.team} empty="No team rows were returned." />
        </Panel>
        <Panel
          title="Recent content"
          description="The last 20 pieces this client generated, and which of them taught the brand anything."
        >
          <ClientContentGallery rows={detail.recent_content} empty="No content yet." />
        </Panel>
        <Panel title="Recent publishing">
          <RecordTable rows={detail.recent_publishing} empty="No publishing jobs yet." />
        </Panel>
        <Panel title="Recent AI calls">
          <RecordTable rows={detail.recent_ai_calls} empty="No AI calls logged." />
        </Panel>
        <Panel title="Platform audit trail" description="What Scaleezy has done to this client.">
          <RecordTable rows={detail.audit} empty="No platform actions recorded for this client." />
        </Panel>
        {detail.onboarding ? (
          <Panel title="Onboarding record">
            <RecordTable rows={[detail.onboarding]} empty="—" />
          </Panel>
        ) : null}
      </div>

      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
      {loading ? (
        <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Refreshing…
        </p>
      ) : null}
    </div>
  );
}

function BackLink() {
  return (
    <Link
      to="/platform/clients"
      className="mb-4 inline-flex items-center gap-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
    >
      <ArrowLeft className="size-4" /> All clients
    </Link>
  );
}
