import { createFileRoute, Link } from "@tanstack/react-router";
import { Bot, Loader2, Octagon, Play, RotateCcw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { PageHeader, SectionTitle, StatusBadge } from "@/components/marketing/primitives";
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
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost } from "@/lib/api";
import { fetchCurrentBrand } from "@/lib/brand-master";

export const Route = createFileRoute("/_hub/autopilot")({
  head: () => ({ meta: [{ title: "Governed Autopilot — Scaleezy" }] }),
  component: AutopilotPage,
});

interface Policy {
  id: string;
  name: string;
  objective: string;
  campaign_brief: string;
  mode: string;
  allowed_formats: string[];
  social_connections: string[];
  daily_generation_limit: number;
  monthly_spend_cap: string;
  enabled: boolean;
  paused: boolean;
  emergency_stop: boolean;
}
interface Step {
  id: string;
  key: string;
  status: string;
  detail: Record<string, unknown>;
}
interface Run {
  id: string;
  policy_name: string;
  mode: string;
  status: string;
  content_item: string | null;
  error: string;
  created_at: string;
  steps: Step[];
}
interface Connection {
  id: string;
  platform: string;
  account_name: string;
  status: string;
}
interface ListEnvelope<T> {
  results?: T[];
}
const list = <T,>(value: T[] | ListEnvelope<T>) =>
  Array.isArray(value) ? value : (value.results ?? []);

function AutopilotPage() {
  const [brandId, setBrandId] = useState("");
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({
    name: "",
    objective: "",
    campaign_brief: "",
    mode: "APPROVAL_REQUIRED",
    format: "POSTER",
    connection: "",
    daily_generation_limit: "1",
    monthly_spend_cap: "0",
  });

  const load = useCallback(async () => {
    const brand = await fetchCurrentBrand();
    setBrandId(brand.id);
    const [policyPayload, runPayload, connectionPayload] = await Promise.all([
      apiGet<Policy[] | ListEnvelope<Policy>>(
        `/api/marketing/autopilot/policies/?brand_id=${brand.id}`,
      ),
      apiGet<Run[] | ListEnvelope<Run>>("/api/marketing/autopilot/runs/"),
      apiGet<Connection[] | ListEnvelope<Connection>>("/api/marketing/social-accounts/"),
    ]);
    setPolicies(list(policyPayload));
    setRuns(list(runPayload));
    const active = list(connectionPayload).filter((row) => row.status === "CONNECTED");
    setConnections(active);
    setDraft((current) => ({ ...current, connection: current.connection || active[0]?.id || "" }));
  }, []);

  useEffect(() => {
    load().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "Autopilot could not load."),
    );
  }, [load]);

  const create = async () => {
    setWorking("create");
    try {
      await apiPost("/api/marketing/autopilot/policies/", {
        brand: brandId,
        name: draft.name,
        objective: draft.objective,
        campaign_brief: draft.campaign_brief,
        mode: draft.mode,
        allowed_formats: [draft.format],
        social_connections: draft.connection ? [draft.connection] : [],
        daily_generation_limit: Number(draft.daily_generation_limit || 1),
        monthly_spend_cap: draft.monthly_spend_cap || "0",
        enabled: true,
      });
      setDraft((current) => ({ ...current, name: "", objective: "", campaign_brief: "" }));
      toast.success("Governed policy created");
      await load();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Policy could not be created");
    } finally {
      setWorking("");
    }
  };
  const act = async (policy: Policy, action: "trigger" | "emergency-stop" | "resume") => {
    setWorking(`${action}:${policy.id}`);
    try {
      await apiPost(`/api/marketing/autopilot/policies/${policy.id}/${action}/`, {});
      toast.success(
        action === "trigger"
          ? "Generation queued"
          : action === "resume"
            ? "Policy resumed"
            : "Emergency stop applied",
      );
      await load();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Action failed");
    } finally {
      setWorking("");
    }
  };

  if (error)
    return (
      <p className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        {error}
      </p>
    );
  return (
    <div>
      <PageHeader
        eyebrow="Admin · Client policy"
        title="Governed Autopilot"
        subtitle="Reusable operating policies that generate through Brand Brain, Context Gateway and your configured AI routes."
        backTo="/admin"
      />
      <div className="grid gap-5 xl:grid-cols-[minmax(20rem,0.65fr)_minmax(0,1.35fr)]">
        <section className="surface-card p-5">
          <SectionTitle
            label="New policy"
            title="Define the mission"
            description="This version starts only when an admin clicks Run. It creates a draft or review item; it never posts externally without the publishing gate."
          />
          <div className="mt-5 space-y-4">
            <Field
              id="policy-name"
              label="Policy name"
              value={draft.name}
              onChange={(name) => setDraft({ ...draft, name })}
            />
            <div>
              <Label htmlFor="policy-objective">Objective</Label>
              <Textarea
                id="policy-objective"
                className="mt-2"
                value={draft.objective}
                onChange={(event) => setDraft({ ...draft, objective: event.target.value })}
                placeholder="What valuable outcome should this content create?"
              />
            </div>
            <div>
              <Label htmlFor="policy-brief">Creative direction</Label>
              <Textarea
                id="policy-brief"
                className="mt-2"
                value={draft.campaign_brief}
                onChange={(event) => setDraft({ ...draft, campaign_brief: event.target.value })}
                placeholder="Audience insight, offer, message and constraints"
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Choice
                label="Mode"
                value={draft.mode}
                onChange={(mode) => setDraft({ ...draft, mode })}
                items={[
                  { value: "APPROVAL_REQUIRED", label: "Review required" },
                  { value: "ASSISTED", label: "Draft only" },
                ]}
              />
              <Choice
                label="Format"
                value={draft.format}
                onChange={(format) => setDraft({ ...draft, format })}
                items={[
                  { value: "POSTER", label: "Poster" },
                  { value: "CAROUSEL", label: "Carousel" },
                  { value: "VIDEO", label: "Video" },
                ]}
              />
            </div>
            <Choice
              label="Target account context"
              value={draft.connection}
              onChange={(connection) => setDraft({ ...draft, connection })}
              items={connections.map((row) => ({
                value: row.id,
                label: `${row.platform} · ${row.account_name}`,
              }))}
              placeholder="No account context"
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                id="daily-limit"
                label="Daily run limit"
                type="number"
                value={draft.daily_generation_limit}
                onChange={(daily_generation_limit) =>
                  setDraft({ ...draft, daily_generation_limit })
                }
              />
              <Field
                id="spend-cap"
                label="Monthly policy cap"
                type="number"
                value={draft.monthly_spend_cap}
                onChange={(monthly_spend_cap) => setDraft({ ...draft, monthly_spend_cap })}
              />
            </div>
            <Button
              className="w-full"
              onClick={create}
              disabled={
                !brandId || !draft.name.trim() || !draft.objective.trim() || working === "create"
              }
            >
              {working === "create" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <ShieldCheck className="size-4" />
              )}{" "}
              Create policy
            </Button>
          </div>
        </section>

        <div className="space-y-5">
          <section className="surface-card p-5">
            <SectionTitle
              label="Policies"
              title="Control centre"
              description="Run, stop or resume without changing provider, context or publishing ownership."
            />
            <div className="mt-5 grid gap-4">
              {policies.map((policy) => (
                <article key={policy.id} className="rounded-xl border p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-semibold">{policy.name}</h3>
                        <StatusBadge
                          status={
                            policy.emergency_stop
                              ? "STOPPED"
                              : policy.paused
                                ? "PAUSED"
                                : policy.enabled
                                  ? "ACTIVE"
                                  : "DISABLED"
                          }
                        />
                      </div>
                      <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
                        {policy.objective}
                      </p>
                      <p className="mt-2 text-xs text-muted-foreground">
                        {policy.mode.replaceAll("_", " ")} ·{" "}
                        {policy.allowed_formats.join(", ") || "POSTER"} · limit{" "}
                        {policy.daily_generation_limit}/day · cap {policy.monthly_spend_cap}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {policy.emergency_stop ? (
                        <Button
                          variant="outline"
                          onClick={() => act(policy, "resume")}
                          disabled={working === `resume:${policy.id}`}
                        >
                          <RotateCcw className="size-4" /> Resume
                        </Button>
                      ) : (
                        <>
                          <Button
                            onClick={() => act(policy, "trigger")}
                            disabled={!policy.enabled || policy.paused || Boolean(working)}
                          >
                            {working === `trigger:${policy.id}` ? (
                              <Loader2 className="size-4 animate-spin" />
                            ) : (
                              <Play className="size-4" />
                            )}{" "}
                            Run
                          </Button>
                          <Button
                            variant="destructive"
                            onClick={() => act(policy, "emergency-stop")}
                            disabled={Boolean(working)}
                          >
                            <Octagon className="size-4" /> Stop
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                </article>
              ))}
              {!policies.length && (
                <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                  No policies yet. Create the first governed mission.
                </p>
              )}
            </div>
          </section>
          <section className="surface-card p-5">
            <SectionTitle
              label="Execution ledger"
              title="Recent runs"
              description="Every stage is inspectable; failures keep their exact reason."
            />
            <div className="mt-5 space-y-3">
              {runs.slice(0, 12).map((run) => (
                <article
                  key={run.id}
                  className="flex flex-wrap items-center justify-between gap-4 rounded-lg border p-4"
                >
                  <div>
                    <p className="font-semibold">{run.policy_name}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {new Date(run.created_at).toLocaleString()} ·{" "}
                      {run.steps.map((step) => `${step.key}: ${step.status}`).join(" → ") ||
                        "Queued"}
                    </p>
                    {run.error && <p className="mt-2 text-xs text-destructive">{run.error}</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={run.status} />
                    {run.content_item ? (
                      <Button asChild size="sm" variant="outline">
                        <Link to="/review">Open content</Link>
                      </Button>
                    ) : null}
                  </div>
                </article>
              ))}
              {!runs.length && <p className="text-sm text-muted-foreground">No runs yet.</p>}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "number";
}) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        className="mt-2"
        type={type}
        min={type === "number" ? "0" : undefined}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}
function Choice({
  label,
  value,
  onChange,
  items,
  placeholder = "Choose",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  items: { value: string; label: string }[];
  placeholder?: string;
}) {
  return (
    <div>
      <Label>{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="mt-2 w-full">
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
