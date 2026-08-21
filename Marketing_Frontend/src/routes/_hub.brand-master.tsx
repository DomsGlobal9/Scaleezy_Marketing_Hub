/**
 * Brand Master — what Scaleezy knows about a brand, and how it learned it.
 *
 * Every number on this page comes from a backend that owns it. Nothing is
 * computed in the browser and nothing is filled in optimistically: if a layer
 * is empty the tab says so plainly, because a dashboard that invents a full
 * bar for an empty brand is how a user gets talked out of the work that makes
 * the product good.
 */
import { useCallback, useEffect, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  BookOpen,
  Brain,
  Check,
  Image as ImageIcon,
  Lightbulb,
  Loader2,
  RefreshCw,
  Scale,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  TrendingUp,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader, SectionTitle } from "@/components/marketing/primitives";
import {
  READINESS_COPY,
  confirmSignal,
  fetchBrain,
  fetchCurrentBrand,
  fetchInspirations,
  fetchKnowledge,
  fetchOverview,
  fetchPreferences,
  fetchRules,
  fetchSignals,
  rebuildBrain,
  rejectSignal,
  type BrandBrain,
  type BrandConflict,
  type BrandMasterOverview,
  type BrandPreferenceRow,
  type BrandRuleRow,
  type Inspiration,
  type InspirationSignalRow,
  type KnowledgeSource,
} from "@/lib/brand-master";

export const Route = createFileRoute("/_hub/brand-master")({
  head: () => ({
    meta: [
      { title: "Brand Master — Scaleezy Marketing Hub" },
      {
        name: "description",
        content: "What Scaleezy knows about your brand, and how it learned it.",
      },
    ],
  }),
  component: BrandMasterPage,
});

/* ------------------------------------------------------------------ shared */

function Empty({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="rounded-xl border border-dashed p-10 text-center">
      <p className="font-medium text-foreground">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{hint}</p>
    </div>
  );
}

function Failed({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center">
      <p className="text-sm font-medium text-destructive">{message}</p>
      <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-16 w-full rounded-xl" />
      ))}
    </div>
  );
}

/** A tab that fetches its own slice, so one slow layer never blocks the rest. */
function useSlice<T>(load: () => Promise<T>, enabled: boolean) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    load()
      .then((value) => {
        if (!cancelled) setData(value);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // `load` is recreated per render by design; nonce is the retry trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, nonce]);

  return { data, error, loading, reload: () => setNonce((n) => n + 1) };
}

function Chip({ tone, children }: { tone: "hard" | "soft" | "user" | "ai"; children: React.ReactNode }) {
  const styles = {
    hard: "border-foreground/25 bg-foreground/5 text-foreground",
    soft: "border-border bg-muted/60 text-muted-foreground",
    user: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700",
    ai: "border-sky-500/30 bg-sky-500/10 text-sky-700",
  } as const;
  return (
    <span className={`rounded-full border px-2.5 py-0.5 text-[0.6875rem] font-medium ${styles[tone]}`}>
      {children}
    </span>
  );
}

/* ---------------------------------------------------------------- overview */

function ReadinessCard({ overview }: { overview: BrandMasterOverview }) {
  const { readiness } = overview;
  const copy = READINESS_COPY[readiness.readiness_level];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-base">
          <span>Brand readiness</span>
          <Badge variant="secondary">{copy.label}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="font-display text-4xl leading-none font-semibold">
              {readiness.readiness_score}
            </span>
            <span className="text-sm text-muted-foreground">/ 100</span>
          </div>
          <Progress value={readiness.readiness_score} className="mt-3" />
          <p className="mt-2 text-sm text-muted-foreground">{copy.blurb}</p>
        </div>

        <div className="space-y-2">
          {readiness.dimensions.map((dimension) => (
            <div key={dimension.key} className="flex items-center gap-3">
              <span className="w-44 shrink-0 truncate text-sm text-muted-foreground">
                {dimension.label}
              </span>
              <Progress value={dimension.score * 100} className="h-1.5 flex-1" />
              <span className="w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                {Math.round(dimension.score * 100)}%
              </span>
            </div>
          ))}
        </div>

        <div className="rounded-xl border bg-muted/40 p-4">
          <p className="label-eyebrow mb-1">Do this next</p>
          <p className="text-sm font-medium text-foreground">
            {readiness.recommended_next_action.label}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {readiness.recommended_next_action.detail}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function CountTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border p-4">
      <p className="font-display text-2xl leading-none font-semibold">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

function OverviewTab({
  overview,
  onRebuild,
  rebuilding,
}: {
  overview: BrandMasterOverview;
  onRebuild: () => void;
  rebuilding: boolean;
}) {
  const { brand, brain, readiness } = overview;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="space-y-6">
        <Card>
          <CardContent className="flex flex-wrap items-start gap-5 pt-6">
            {brand.logo_url ? (
              <img
                src={brand.logo_url}
                alt=""
                className="size-16 shrink-0 rounded-xl border object-contain"
              />
            ) : (
              <span className="grid size-16 shrink-0 place-items-center rounded-xl border border-dashed text-muted-foreground">
                <ImageIcon className="size-5" />
              </span>
            )}
            <div className="min-w-0 flex-1">
              <h2 className="font-display text-2xl font-semibold tracking-tight">
                {brand.name}
              </h2>
              <p className="text-sm text-muted-foreground">
                {brand.industry || "No industry set"}
              </p>
              {brand.tagline ? (
                <p className="mt-2 text-sm text-foreground">{brand.tagline}</p>
              ) : null}
              {brand.brand_tone ? (
                <p className="mt-1 text-sm text-muted-foreground">
                  Tone: {brand.brand_tone}
                </p>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <div>
          <SectionTitle title="What Scaleezy is working from" />
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <CountTile label="Knowledge sources" value={readiness.counts.sources} />
            <CountTile label="Confirmed facts" value={readiness.counts.memories} />
            <CountTile label="Inspirations" value={readiness.counts.inspirations} />
            <CountTile label="Learned preferences" value={readiness.counts.preferences} />
            <CountTile label="Active rules" value={readiness.counts.rules} />
            <CountTile label="Open conflicts" value={readiness.counts.unresolved_conflicts} />
          </div>
        </div>

        {brain.positioning?.statements?.length ? (
          <div>
            <SectionTitle title="Positioning" />
            <ul className="mt-3 space-y-2">
              {brain.positioning.statements.map((statement) => (
                <li key={statement} className="rounded-xl border p-3 text-sm">
                  {statement}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      <div className="space-y-6">
        <ReadinessCard overview={overview} />
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Brand Brain</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {brain.compiled ? (
              <>
                <Row label="Version" value={brain.brain_version.slice(0, 12)} mono />
                <Row
                  label="Last compiled"
                  value={
                    brain.compiled_at
                      ? new Date(brain.compiled_at).toLocaleString()
                      : "—"
                  }
                />
              </>
            ) : (
              <p className="text-muted-foreground">
                Not compiled yet. Rebuild to snapshot what Scaleezy currently knows.
              </p>
            )}
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={onRebuild}
              disabled={rebuilding}
            >
              {rebuilding ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-2 size-4" />
              )}
              Rebuild Brand Brain
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className={mono ? "font-mono text-xs" : ""}>{value}</span>
    </div>
  );
}

/* --------------------------------------------------------------- knowledge */

function KnowledgeTab({ brandId }: { brandId: string }) {
  const slice = useSlice<KnowledgeSource[]>(() => fetchKnowledge(brandId), true);

  if (slice.loading) return <Loading />;
  if (slice.error) return <Failed message={slice.error} onRetry={slice.reload} />;
  if (!slice.data?.length) {
    return (
      <Empty
        title="No knowledge yet"
        hint="Upload a brand deck, a transcript or a product document and Scaleezy will read it."
      />
    );
  }

  return (
    <div className="space-y-3">
      {slice.data.map((source) => (
        <div
          key={source.id}
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"
        >
          <div className="min-w-0">
            <p className="truncate font-medium">{source.title}</p>
            <p className="text-xs text-muted-foreground">
              {source.source_type.replaceAll("_", " ").toLowerCase()}
              {source.file_name ? ` · ${source.file_name}` : ""}
            </p>
          </div>
          <Badge variant={source.status === "ARCHIVED" ? "outline" : "secondary"}>
            {source.status.replaceAll("_", " ").toLowerCase()}
          </Badge>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------ inspirations */

function InspirationsTab({ brandId }: { brandId: string }) {
  const inspirations = useSlice<Inspiration[]>(() => fetchInspirations(brandId), true);
  const signals = useSlice<InspirationSignalRow[]>(() => fetchSignals(brandId), true);
  const [busy, setBusy] = useState<string | null>(null);

  const act = useCallback(
    async (signalId: string, action: "confirm" | "reject") => {
      setBusy(signalId);
      try {
        await (action === "confirm" ? confirmSignal(signalId) : rejectSignal(signalId));
        signals.reload();
      } finally {
        setBusy(null);
      }
    },
    [signals],
  );

  if (inspirations.loading || signals.loading) return <Loading />;
  if (inspirations.error) {
    return <Failed message={inspirations.error} onRetry={inspirations.reload} />;
  }
  if (!inspirations.data?.length) {
    return (
      <Empty
        title="No inspirations yet"
        hint="Add references — a screenshot, a competitor post, a reel — and say what you like about them."
      />
    );
  }

  const byInspiration = new Map<string, InspirationSignalRow[]>();
  for (const signal of signals.data ?? []) {
    const list = byInspiration.get(signal.inspiration) ?? [];
    list.push(signal);
    byInspiration.set(signal.inspiration, list);
  }

  return (
    <div className="space-y-4">
      {inspirations.data.map((inspiration) => {
        const noticed = byInspiration.get(inspiration.id) ?? [];
        const archived = inspiration.lifecycle_status === "ARCHIVED";
        return (
          <Card key={inspiration.id} className={archived ? "opacity-60" : ""}>
            <CardContent className="space-y-4 pt-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium">{inspiration.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {inspiration.inspiration_type.replaceAll("_", " ").toLowerCase()}
                    {inspiration.external_platform ? ` · ${inspiration.external_platform}` : ""}
                  </p>
                  {inspiration.annotation ? (
                    <p className="mt-2 text-sm">“{inspiration.annotation}”</p>
                  ) : null}
                </div>
                {archived ? <Badge variant="outline">archived</Badge> : null}
              </div>

              {inspiration.usage_scope === "SPECIFIC_ELEMENTS" &&
              inspiration.focus_areas.length ? (
                <p className="text-xs text-muted-foreground">
                  Use only: {inspiration.focus_areas.join(", ").toLowerCase()}
                </p>
              ) : null}

              <div>
                <p className="label-eyebrow mb-2">What Scaleezy noticed</p>
                {noticed.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Nothing extracted yet — analysis arrives in a later release.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {noticed.map((signal) => (
                      <li
                        key={signal.id}
                        className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
                      >
                        <span className="min-w-0">
                          <span className="text-sm font-medium">
                            {signal.category.replaceAll("_", " ").toLowerCase()}
                          </span>
                          <span className="text-sm text-muted-foreground">
                            {" "}
                            — {signal.value || signal.attribute}
                          </span>
                        </span>
                        <span className="flex items-center gap-2">
                          <Chip tone={signal.origin === "USER" ? "user" : "ai"}>
                            {signal.origin === "USER" ? "You said" : "Scaleezy inferred"}
                          </Chip>
                          {signal.origin === "AI" &&
                          signal.user_confirmation === "PENDING" ? (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={busy === signal.id}
                                onClick={() => act(signal.id, "confirm")}
                              >
                                <ThumbsUp className="mr-1 size-3.5" /> Like
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                disabled={busy === signal.id}
                                onClick={() => act(signal.id, "reject")}
                              >
                                <ThumbsDown className="mr-1 size-3.5" /> Not us
                              </Button>
                            </>
                          ) : (
                            <Badge variant="secondary">
                              {signal.user_confirmation.toLowerCase()}
                            </Badge>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- learning */

function LearningTab({ brandId }: { brandId: string }) {
  const slice = useSlice<BrandPreferenceRow[]>(() => fetchPreferences(brandId), true);

  if (slice.loading) return <Loading />;
  if (slice.error) return <Failed message={slice.error} onRetry={slice.reload} />;
  if (!slice.data?.length) {
    return (
      <Empty
        title="Nothing learned yet"
        hint="Approve and reject a few generations. Scaleezy needs more than one decision before it calls something a preference."
      />
    );
  }

  const groups: Array<[string, BrandPreferenceRow[]]> = [
    ["Established", slice.data.filter((p) => p.state === "ESTABLISHED")],
    ["Emerging", slice.data.filter((p) => p.state === "EMERGING")],
  ];

  return (
    <div className="space-y-8">
      {groups.map(([label, rows]) =>
        rows.length === 0 ? null : (
          <div key={label}>
            <SectionTitle
              title={label}
              description={
                label === "Established"
                  ? "Seen enough times that Scaleezy will act on it."
                  : "Noticed once. Not yet acted on."
              }
            />
            <ul className="mt-3 space-y-2">
              {rows.map((preference) => (
                <li
                  key={preference.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"
                >
                  <div className="min-w-0">
                    <p className="font-medium">
                      {preference.value || preference.attribute}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {preference.category.replaceAll("_", " ").toLowerCase()} ·{" "}
                      {preference.attribute}
                    </p>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    Learned from {preference.evidence_count} distinct decision
                    {preference.evidence_count === 1 ? "" : "s"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ),
      )}
    </div>
  );
}

/* ------------------------------------------------------------------- rules */

function RulesTab({ brandId }: { brandId: string }) {
  const slice = useSlice<BrandRuleRow[]>(() => fetchRules(brandId), true);

  if (slice.loading) return <Loading />;
  if (slice.error) return <Failed message={slice.error} onRetry={slice.reload} />;

  const active = (slice.data ?? []).filter((rule) => rule.is_active);
  const explicit = active.filter((rule) => rule.origin === "EXPLICIT");
  const learned = active.filter((rule) => rule.origin === "LEARNED");

  if (active.length === 0) {
    return (
      <Empty
        title="No rules yet"
        hint="Brand rules are the instructions Scaleezy must never break. Learned rules appear here once enough evidence supports them."
      />
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <SectionTitle
          title="Your brand rules"
          description="Stated by a person. Scaleezy treats these as instructions."
        />
        {explicit.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">None stated yet.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {explicit.map((rule) => (
              <li
                key={rule.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border-2 border-foreground/15 bg-foreground/[0.03] p-4"
              >
                <span className="min-w-0 font-medium">{rule.text}</span>
                <Chip tone={rule.hardness === "HARD" ? "hard" : "soft"}>
                  {rule.hardness === "HARD" ? "Must never break" : "Preference"}
                </Chip>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <SectionTitle
          title="Learned guidance"
          description="Inferred from your decisions. Guidance, not instruction — Scaleezy will not treat these as absolute."
        />
        {learned.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">Nothing inferred yet.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {learned.map((rule) => (
              <li
                key={rule.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed p-4"
              >
                <span className="min-w-0 text-muted-foreground">{rule.text}</span>
                <span className="flex items-center gap-2">
                  <Chip tone="soft">Learned</Chip>
                  <span className="text-xs text-muted-foreground">
                    {rule.evidence_event_ids.length} supporting decision
                    {rule.evidence_event_ids.length === 1 ? "" : "s"}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- brain */

function ClaimList({ claims }: { claims: BrainClaimLike[] }) {
  if (!claims.length) {
    return <p className="text-sm text-muted-foreground">Nothing yet.</p>;
  }
  return (
    <ul className="space-y-2">
      {claims.map((claim) => (
        <li
          key={`${claim.source_id}-${claim.attribute}`}
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm"
        >
          <span className="min-w-0">
            <span className="text-muted-foreground">
              {claim.attribute.replaceAll("_", " ")}:{" "}
            </span>
            {claim.value}
          </span>
          <Chip tone={claim.authority.includes("hard") ? "hard" : "soft"}>
            {claim.authority.replaceAll("_", " ")}
          </Chip>
        </li>
      ))}
    </ul>
  );
}

type BrainClaimLike = {
  attribute: string;
  value: string;
  authority: string;
  source_id: string;
};

function BrainSection({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <SectionTitle title={title} />
      <ul className="mt-3 space-y-2">
        {items.map((item) => (
          <li key={item} className="rounded-xl border p-3 text-sm">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function BrainTab({ brandId }: { brandId: string }) {
  const slice = useSlice<BrandBrain>(() => fetchBrain(brandId), true);

  if (slice.loading) return <Loading rows={5} />;
  if (slice.error) return <Failed message={slice.error} onRetry={slice.reload} />;
  const brain = slice.data;
  if (!brain) return null;

  const nothingYet =
    !brain.verified_product_truth.length &&
    !brain.hard_rules.length &&
    !brain.soft_rules.length &&
    !brain.preferences.length;

  if (nothingYet) {
    return (
      <Empty
        title="The brain is empty"
        hint="It compiles from knowledge, inspirations and what Scaleezy has learned. Add any of those and it fills in."
      />
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap gap-3 rounded-xl border bg-muted/40 p-4 text-sm">
        <span className="text-muted-foreground">Version</span>
        <span className="font-mono text-xs">{brain.brain_version.slice(0, 16)}</span>
        <span className="text-muted-foreground">· Compiled</span>
        <span>{new Date(brain.compiled_at).toLocaleString()}</span>
      </div>

      <BrainSection title="Verified product truth" items={brain.verified_product_truth} />
      <BrainSection title="Positioning" items={brain.positioning.statements ?? []} />
      <BrainSection title="Audience pains" items={brain.audiences.pains ?? []} />

      {brain.voice.tone || brain.voice.claims?.length ? (
        <div>
          <SectionTitle title="Voice" />
          {brain.voice.tone ? <p className="mt-2 text-sm">{brain.voice.tone}</p> : null}
          <div className="mt-3">
            <ClaimList claims={brain.voice.claims ?? []} />
          </div>
        </div>
      ) : null}

      <div>
        <SectionTitle title="Visual language" />
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(brain.visual_language.palette ?? {}).map(([name, value]) => (
            <span key={name} className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs">
              <span
                className="size-4 rounded border"
                style={{ backgroundColor: String(value) }}
              />
              {name}
            </span>
          ))}
        </div>
        <div className="mt-3">
          <ClaimList claims={brain.visual_language.claims ?? []} />
        </div>
      </div>

      <BrainSection title="Win patterns" items={brain.win_patterns} />
      <BrainSection title="Avoid patterns" items={brain.avoid_patterns} />
    </div>
  );
}

/* --------------------------------------------------------------- conflicts */

function ConflictsTab({ conflicts }: { conflicts: BrandConflict[] }) {
  if (!conflicts.length) {
    return (
      <Empty
        title="Nothing needs your decision"
        hint="When two equally trusted sources disagree, Scaleezy stops and asks rather than picking one."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-600" />
        <div>
          <p className="font-medium">Scaleezy needs your decision</p>
          <p className="text-sm text-muted-foreground">
            These sources are equally trusted and disagree, so nothing about them is being
            used. Update or revoke one of the sources to settle it.
          </p>
        </div>
      </div>

      {conflicts.map((conflict) => (
        <Card key={`${conflict.category}-${conflict.attribute}`}>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              {conflict.attribute.replaceAll("_", " ")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {conflict.claims.map((claim, index) => (
              <div
                key={claim.source_id ?? index}
                className="rounded-lg border p-3 text-sm"
              >
                <p>{claim.value}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {(claim.source_type ?? "source").replaceAll("_", " ")}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------- page */

function BrandMasterPage() {
  const [brandId, setBrandId] = useState<string | null>(null);
  const [overview, setOverview] = useState<BrandMasterOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);

  const loadOverview = useCallback(async (id: string) => {
    setOverview(await fetchOverview(id));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchCurrentBrand()
      .then((brand) => {
        if (cancelled) return null;
        setBrandId(brand.id);
        return loadOverview(brand.id);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load Brand Master.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loadOverview]);

  const onRebuild = useCallback(async () => {
    if (!brandId) return;
    setRebuilding(true);
    try {
      await rebuildBrain(brandId);
      await loadOverview(brandId);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not rebuild the Brand Brain.");
    } finally {
      setRebuilding(false);
    }
  }, [brandId, loadOverview]);

  const conflictCount = overview?.brain.unresolved_conflict_count ?? 0;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Brand Master"
        title="What Scaleezy knows"
        subtitle="Every fact, reference, preference and rule behind your brand's work — and where each one came from."
        actions={
          overview ? (
            overview.readiness.readiness_level === "READY" ||
            overview.readiness.readiness_level === "STRONG" ? (
              <Button asChild>
                <Link to="/">Create content</Link>
              </Button>
            ) : (
              <Button asChild variant="outline">
                <Link to="/onboarding">Continue setup</Link>
              </Button>
            )
          ) : null
        }
      />

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-40 w-full rounded-xl" />
          <Loading rows={4} />
        </div>
      ) : error ? (
        <Failed message={error} onRetry={() => window.location.reload()} />
      ) : !brandId || !overview ? (
        <Empty
          title="No brand yet"
          hint="Create a brand in Settings and Brand Master will start filling in."
        />
      ) : (
        <Tabs defaultValue="overview" className="space-y-6">
          <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1">
            <TabsTrigger value="overview" className="gap-1.5">
              <Sparkles className="size-3.5" /> Overview
            </TabsTrigger>
            <TabsTrigger value="knowledge" className="gap-1.5">
              <BookOpen className="size-3.5" /> Knowledge
            </TabsTrigger>
            <TabsTrigger value="inspirations" className="gap-1.5">
              <Lightbulb className="size-3.5" /> Inspirations
            </TabsTrigger>
            <TabsTrigger value="learning" className="gap-1.5">
              <TrendingUp className="size-3.5" /> Learning
            </TabsTrigger>
            <TabsTrigger value="rules" className="gap-1.5">
              <Scale className="size-3.5" /> Rules
            </TabsTrigger>
            <TabsTrigger value="brain" className="gap-1.5">
              <Brain className="size-3.5" /> Brand Brain
            </TabsTrigger>
            <TabsTrigger value="attention" className="gap-1.5">
              {conflictCount > 0 ? (
                <AlertTriangle className="size-3.5 text-amber-600" />
              ) : (
                <Check className="size-3.5" />
              )}
              Attention
              {conflictCount > 0 ? (
                <Badge variant="secondary" className="ml-1">
                  {conflictCount}
                </Badge>
              ) : null}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview">
            <OverviewTab
              overview={overview}
              onRebuild={onRebuild}
              rebuilding={rebuilding}
            />
          </TabsContent>
          <TabsContent value="knowledge">
            <KnowledgeTab brandId={brandId} />
          </TabsContent>
          <TabsContent value="inspirations">
            <InspirationsTab brandId={brandId} />
          </TabsContent>
          <TabsContent value="learning">
            <LearningTab brandId={brandId} />
          </TabsContent>
          <TabsContent value="rules">
            <RulesTab brandId={brandId} />
          </TabsContent>
          <TabsContent value="brain">
            <BrainTab brandId={brandId} />
          </TabsContent>
          <TabsContent value="attention">
            <ConflictsTab conflicts={overview.conflicts} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
