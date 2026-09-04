/**
 * Creative research — AI discovery of cited public references, used from the
 * Brand Master Inspirations tab (moved here from the old Growth Engine page).
 *
 * The state machine is unchanged: a run is queued, every finding is
 * verified against its cited source, rights default to "unknown", and only a
 * verified, non-restricted finding can be adopted — which writes a
 * BrandInspiration row into this brand's own inspirations.
 */
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  Lightbulb,
  Loader2,
  Search,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { SectionTitle, StatusBadge } from "@/components/marketing/primitives";
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
import type { BrandDto } from "@/lib/brand-settings";
import { buildGuidedResearchText } from "@/lib/guided-workflows";

interface Finding {
  id: string;
  kind: string;
  title: string;
  source_url: string;
  preview_url: string;
  source_name: string;
  platform: string;
  excerpt: string;
  rights_status: string;
  verification_status: string;
  verification_error: string;
  adopted_inspiration: string | null;
}

interface ResearchRun {
  id: string;
  query: string;
  status: string;
  provider_name: string;
  error: string;
  created_at: string;
  findings: Finding[];
}

interface ListEnvelope<T> {
  results?: T[];
}

function rows<T>(value: T[] | ListEnvelope<T>): T[] {
  return Array.isArray(value) ? value : (value.results ?? []);
}

const ACTIVE_RESEARCH = new Set(["QUEUED", "PROCESSING"]);

export function CreativeResearchPanel({
  brand,
  onAdopted,
}: {
  brand: BrandDto;
  onAdopted?: () => void;
}) {
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const payload = await apiGet<ResearchRun[] | ListEnvelope<ResearchRun>>(
      `/api/marketing/research-runs/?brand_id=${brand.id}`,
    );
    setRuns(rows(payload));
  }, [brand.id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    load()
      .catch((cause: unknown) => {
        if (!cancelled)
          setError(cause instanceof Error ? cause.message : "Could not load creative research.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const shouldPoll = useMemo(() => runs.some((run) => ACTIVE_RESEARCH.has(run.status)), [runs]);

  useEffect(() => {
    if (!shouldPoll) return;
    const timer = window.setInterval(() => void load().catch(() => undefined), 3000);
    return () => window.clearInterval(timer);
  }, [load, shouldPoll]);

  async function act<T>(key: string, request: () => Promise<T>, success: string) {
    setWorking(key);
    try {
      await request();
      toast.success(success);
      await load();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Action failed.");
    } finally {
      setWorking("");
    }
  }

  const guided = buildGuidedResearchText(brand);
  const [query, setQuery] = useState(guided.query);
  const [objectives, setObjectives] = useState(guided.objectives);
  const [sources, setSources] = useState("");
  // Every run in the payload carries its full findings, so history is a
  // selection, not another fetch. New runs land at the front of the list.
  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? runs[0];

  const start = () =>
    act(
      "research",
      async () => {
        await apiPost("/api/marketing/research-runs/", {
          brand: brand.id,
          query,
          objectives: objectives
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
          sources: sources
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
        });
        // Show the freshly queued run rather than whichever old run was open.
        setSelectedRunId("");
      },
      "Research queued. Scaleezy will verify every cited source.",
    );

  return (
    <section>
      <SectionTitle
        label="Research the web"
        title="Let Scaleezy find references"
        description="AI research that returns cited public references. Verify the source, set its rights, and adopt the good ones — they become part of your own inspirations above."
      />

      {error ? (
        <div className="mb-6 flex items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <CircleAlert className="size-5" /> {error}
        </div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <section className="surface-card h-fit p-5 xl:sticky xl:top-6">
          <p className="label-eyebrow">Creative discovery</p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight">Start with a ready brief.</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Scaleezy drafted this from Brand Master. Edit anything, or run it as-is to discover
            cited public references from any industry. You decide what enters Brand Master.
          </p>
          <div className="mt-5 space-y-4">
            <div>
              <Label htmlFor="research-query">What should Scaleezy find?</Label>
              <Textarea
                id="research-query"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Example: bold ecommerce launch posters in premium skincare, including unconventional references outside our industry"
                className="mt-2 min-h-28"
              />
            </div>
            <details className="rounded-xl border p-4">
              <summary className="cursor-pointer text-sm font-semibold">
                Fine-tune focus or preferred sources (optional)
              </summary>
              <div className="mt-4 space-y-4">
                <div>
                  <Label htmlFor="research-objectives">Focus areas</Label>
                  <Input
                    id="research-objectives"
                    value={objectives}
                    onChange={(event) => setObjectives(event.target.value)}
                    placeholder="layout, hook, product staging"
                    className="mt-2"
                  />
                </div>
                <div>
                  <Label htmlFor="research-sources">Preferred places</Label>
                  <Input
                    id="research-sources"
                    value={sources}
                    onChange={(event) => setSources(event.target.value)}
                    placeholder="Leave blank to search the unrestricted public web"
                    className="mt-2"
                  />
                </div>
              </div>
            </details>
            <Button
              className="w-full"
              disabled={query.trim().length < 3 || working === "research"}
              onClick={start}
            >
              {working === "research" ? <Loader2 className="animate-spin" /> : <Search />}
              Find ideas for {brand.name || "this brand"}
            </Button>
            <p className="text-xs leading-5 text-muted-foreground">
              References default to “rights unknown.” Scaleezy does not copy or grant rights to
              third-party work.
            </p>
          </div>
        </section>

        <section>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="label-eyebrow">Cited reference board</p>
              <h2 className="mt-1 text-2xl font-bold">Industry-wide inspiration</h2>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {runs.length > 1 ? (
                <Select value={selectedRun?.id ?? ""} onValueChange={setSelectedRunId}>
                  <SelectTrigger className="w-64" aria-label="Research history">
                    <SelectValue placeholder="Run history" />
                  </SelectTrigger>
                  <SelectContent>
                    {runs.map((run) => (
                      <SelectItem key={run.id} value={run.id}>
                        {new Date(run.created_at).toLocaleDateString()} ·{" "}
                        {run.query.length > 60 ? `${run.query.slice(0, 60)}…` : run.query}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : null}
              {selectedRun ? (
                <StatusBadge status={selectedRun.status.replaceAll("_", " ")} />
              ) : null}
            </div>
          </div>
          {loading ? (
            <div className="surface-card p-10 text-center text-sm text-muted-foreground">
              Loading research…
            </div>
          ) : !selectedRun ? (
            <div className="surface-card p-10 text-center">
              <Lightbulb className="mx-auto size-8 text-primary" />
              <p className="mt-3 font-semibold">Your first reference board starts here.</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Describe anything you want to explore.
              </p>
            </div>
          ) : selectedRun.error ? (
            <div className="surface-card border-destructive/30 p-5 text-sm text-destructive">
              {selectedRun.error}
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
              {selectedRun.findings.map((finding) => (
                <FindingCard
                  key={finding.id}
                  finding={finding}
                  working={working}
                  act={act}
                  onAdopted={onAdopted}
                />
              ))}
              {!selectedRun.findings.length ? (
                <div className="surface-card col-span-full p-10 text-center text-sm text-muted-foreground">
                  {ACTIVE_RESEARCH.has(selectedRun.status)
                    ? "Research is running in the background. You can leave this page."
                    : "No source passed verification. Try a broader query or route a web-enabled research provider."}
                </div>
              ) : null}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

function FindingCard({
  finding,
  working,
  act,
  onAdopted,
}: {
  finding: Finding;
  working: string;
  act: <T>(key: string, request: () => Promise<T>, success: string) => Promise<void>;
  onAdopted?: (() => void) | undefined;
}) {
  const verified = finding.verification_status === "VERIFIED";
  return (
    <article className="surface-card overflow-hidden">
      <div className="aspect-[4/3] bg-black/5">
        {finding.preview_url ? (
          <img
            src={finding.preview_url}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            className="size-full object-cover"
          />
        ) : (
          <div className="grid size-full place-items-center text-muted-foreground">
            <Sparkles className="size-8" />
          </div>
        )}
      </div>
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <span className="text-xs font-semibold tracking-wide text-primary uppercase">
            {finding.kind.replaceAll("_", " ")}
          </span>
          <StatusBadge
            status={finding.verification_status}
            tone={verified ? "success" : "danger"}
          />
        </div>
        <h3 className="mt-2 line-clamp-2 font-semibold">{finding.title}</h3>
        <p className="mt-2 line-clamp-3 text-sm leading-6 text-muted-foreground">
          {finding.excerpt}
        </p>
        <a
          href={finding.source_url}
          target="_blank"
          rel="noreferrer"
          className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-primary"
        >
          {finding.source_name || finding.platform || "Open source"}{" "}
          <ArrowUpRight className="size-3.5" />
        </a>
        <div className="mt-4">
          <Select
            value={finding.rights_status}
            disabled={!!finding.adopted_inspiration}
            onValueChange={(rights_status) =>
              void act(
                `rights-${finding.id}`,
                () =>
                  apiPost(`/api/marketing/research-findings/${finding.id}/set-rights/`, {
                    rights_status,
                  }),
                "Rights status updated.",
              )
            }
          >
            <SelectTrigger aria-label="Rights status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="UNKNOWN">Rights unknown</SelectItem>
              <SelectItem value="PUBLIC_REFERENCE">Public reference only</SelectItem>
              <SelectItem value="OWNED">Owned by this client</SelectItem>
              <SelectItem value="LICENSED">Licensed for reuse</SelectItem>
              <SelectItem value="RESTRICTED">Restricted — do not use</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button
          variant={finding.adopted_inspiration ? "outline" : "default"}
          className="mt-3 w-full"
          disabled={
            !verified ||
            !!finding.adopted_inspiration ||
            working === `adopt-${finding.id}` ||
            finding.rights_status === "RESTRICTED"
          }
          onClick={() =>
            void act(
              `adopt-${finding.id}`,
              async () => {
                await apiPost(`/api/marketing/research-findings/${finding.id}/adopt/`, {});
                onAdopted?.();
              },
              "Added to your inspirations.",
            )
          }
        >
          {finding.adopted_inspiration ? <Check /> : <Lightbulb />}
          {finding.adopted_inspiration ? "In your inspirations" : "Use as inspiration"}
        </Button>
      </div>
    </article>
  );
}
