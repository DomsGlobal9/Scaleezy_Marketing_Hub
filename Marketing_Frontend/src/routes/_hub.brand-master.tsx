/**
 * Brand Master — the single home for everything Scaleezy understands about a
 * brand, and the place it is taught.
 *
 * Teach → Understand → Create → Review → Learn → Improve. Every number on
 * this page comes from a backend that owns it; every card opens the tab that
 * owns the work; nothing is filled in optimistically. If a layer is empty the
 * tab says so plainly.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import {
  AlertTriangle,
  BookOpen,
  Brain,
  Check,
  GraduationCap,
  IdCard,
  Image as ImageIcon,
  Lightbulb,
  Loader2,
  Package,
  RefreshCw,
  Scale,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BrandBasicsPanel } from "@/components/marketing/brand-basics";
import {
  Chip,
  Empty,
  Failed,
  InlineError,
  Loading,
  errorMessage,
  useSlice,
} from "@/components/marketing/brand-master-primitives";
import { InspirationsPanel } from "@/components/marketing/inspirations-panel";
import { KnowledgePanel } from "@/components/marketing/knowledge-panel";
import { LibraryGallery } from "@/components/marketing/library-gallery";
import { EnrichFromWebsite, NlNoteBox } from "@/components/marketing/nl-note-box";
import { PageHeader, SectionTitle } from "@/components/marketing/primitives";
import { ProductsAudiencePanel } from "@/components/marketing/products-audience-panel";
import { TeachScaleezy } from "@/components/marketing/teach-scaleezy";
import {
  BRAND_MASTER_TABS,
  READINESS_COPY,
  createRule,
  deactivateRule,
  fetchBrain,
  fetchCurrentBrand,
  fetchKnowledge,
  fetchLearningEvents,
  fetchOverview,
  fetchPreferences,
  fetchRules,
  humanize,
  rebuildBrain,
  rejectMemory,
  rejectSignal,
  retirePreference,
  tabForReadinessKey,
  type BrandBrain,
  type BrandConflict,
  type BrandMasterOverview,
  type BrandMasterTab,
  type BrandPreferenceRow,
  type BrandRuleRow,
  type KnowledgeSource,
  type LearningEventRow,
} from "@/lib/brand-master";
import { useBrandSettings } from "@/lib/brand-settings";

export const Route = createFileRoute("/_hub/brand-master")({
  validateSearch: (search: Record<string, unknown>): { tab?: BrandMasterTab } => {
    const tab = search["tab"];
    return typeof tab === "string" && (BRAND_MASTER_TABS as string[]).includes(tab)
      ? { tab: tab as BrandMasterTab }
      : {};
  },
  head: () => ({
    meta: [
      { title: "Brand Master — Scaleezy Marketing Hub" },
      {
        name: "description",
        content:
          "What Scaleezy knows about your brand, how it learned it, and where to teach it more.",
      },
    ],
  }),
  component: BrandMasterPage,
});

/* ---------------------------------------------------------------- overview */

function ReadinessCard({
  overview,
  onGoToTab,
}: {
  overview: BrandMasterOverview;
  onGoToTab: (tab: BrandMasterTab) => void;
}) {
  const { readiness } = overview;
  const copy = READINESS_COPY[readiness.readiness_level];
  const target = tabForReadinessKey(readiness.recommended_next_action.key);

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
            <button
              type="button"
              key={dimension.key}
              onClick={() => {
                const t = tabForReadinessKey(dimension.key);
                if (t !== "create") onGoToTab(t);
              }}
              className="flex w-full items-center gap-3 rounded-md text-left hover:bg-muted/50"
              title={dimension.hint}
            >
              <span className="w-44 shrink-0 truncate text-sm text-muted-foreground">
                {dimension.label}
              </span>
              <Progress value={dimension.score * 100} className="h-1.5 flex-1" />
              <span className="w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                {Math.round(dimension.score * 100)}%
              </span>
            </button>
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
          {target === "create" ? (
            <Button asChild size="sm" className="mt-3">
              <Link to="/publishing">Create content</Link>
            </Button>
          ) : (
            <Button size="sm" variant="outline" className="mt-3" onClick={() => onGoToTab(target)}>
              Go there
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function CountTile({
  label,
  value,
  onClick,
}: {
  label: string;
  value: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-xl border p-4 text-left transition-colors hover:bg-muted/40"
    >
      <p className="font-display text-2xl leading-none font-semibold">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{label}</p>
    </button>
  );
}

function OverviewTab({
  overview,
  onRebuild,
  rebuilding,
  onGoToTab,
}: {
  overview: BrandMasterOverview;
  onRebuild: () => void;
  rebuilding: boolean;
  onGoToTab: (tab: BrandMasterTab) => void;
}) {
  const { brand, brain, readiness } = overview;
  const low = readiness.readiness_level === "STARTING" || readiness.readiness_level === "LEARNING";
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
              <button
                type="button"
                onClick={() => onGoToTab("basics")}
                className="grid size-16 shrink-0 place-items-center rounded-xl border border-dashed text-muted-foreground"
                title="Add a logo"
              >
                <ImageIcon className="size-5" />
              </button>
            )}
            <div className="min-w-0 flex-1">
              <h2 className="font-display text-2xl font-semibold tracking-tight">{brand.name}</h2>
              <p className="text-sm text-muted-foreground">{brand.industry || "No industry set"}</p>
              {brand.tagline ? (
                <p className="mt-2 text-sm text-foreground">{brand.tagline}</p>
              ) : null}
              {brand.brand_tone ? (
                <p className="mt-1 text-sm text-muted-foreground">Tone: {brand.brand_tone}</p>
              ) : null}
              <Button
                variant="link"
                size="sm"
                className="mt-1 h-auto px-0"
                onClick={() => onGoToTab("basics")}
              >
                Edit brand basics
              </Button>
            </div>
            {low ? (
              <Button onClick={() => onGoToTab("teach")}>
                <GraduationCap className="size-4" /> Continue teaching Scaleezy
              </Button>
            ) : (
              <Button asChild>
                <Link to="/publishing">
                  <Sparkles className="size-4" /> Create content
                </Link>
              </Button>
            )}
          </CardContent>
        </Card>

        <div>
          <SectionTitle
            title="What Scaleezy is working from"
            description="Each count opens the layer it comes from."
          />
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <CountTile
              label="Knowledge sources"
              value={readiness.counts.sources}
              onClick={() => onGoToTab("knowledge")}
            />
            <CountTile
              label="Confirmed facts"
              value={readiness.counts.memories}
              onClick={() => onGoToTab("knowledge")}
            />
            <CountTile
              label="Inspirations"
              value={readiness.counts.inspirations}
              onClick={() => onGoToTab("inspirations")}
            />
            <CountTile
              label="Learned preferences"
              value={readiness.counts.preferences}
              onClick={() => onGoToTab("learning")}
            />
            <CountTile
              label="Active rules"
              value={readiness.counts.rules}
              onClick={() => onGoToTab("rules")}
            />
            <CountTile
              label="Needs your decision"
              value={readiness.counts.unresolved_conflicts}
              onClick={() => onGoToTab("attention")}
            />
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
        <ReadinessCard overview={overview} onGoToTab={onGoToTab} />
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Brand Brain</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {brain.compiled ? (
              <>
                <Row
                  label="State"
                  value={
                    brain.unresolved_conflict_count
                      ? `${brain.unresolved_conflict_count} unresolved`
                      : "Consistent"
                  }
                />
                <Row label="Version" value={brain.brain_version.slice(0, 12)} mono />
                <Row
                  label="Last compiled"
                  value={brain.compiled_at ? new Date(brain.compiled_at).toLocaleString() : "—"}
                />
              </>
            ) : (
              <p className="text-muted-foreground">
                Not compiled yet. It compiles automatically as you teach; rebuild to snapshot it
                now.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                onClick={() => onGoToTab("brain")}
              >
                <Brain className="size-4" /> Open
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                onClick={onRebuild}
                disabled={rebuilding}
              >
                {rebuilding ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <RefreshCw className="size-4" />
                )}
                Rebuild
              </Button>
            </div>
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

/* ---------------------------------------------------------------- learning */

const EVENT_COPY: Record<string, string> = {
  APPROVED: "Approved a generation",
  EDITED: "Sent a generation back for edits",
  REJECTED: "Rejected a generation",
  REDO: "Asked for a redo",
  EXPLICIT_RULE: "Stated a brand rule",
  PREFERENCE_SIGNAL: "Reacted to a calibration direction",
  INSPIRATION_SIGNAL: "Stated a preference on a reference",
  PUBLISHED: "Published",
  PERFORMANCE_OBSERVED: "Performance observed",
  MEMORY_CONFIRMED: "Confirmed a fact",
  MEMORY_REJECTED: "Rejected a fact",
};

function LearningTab({ brandId, onChanged }: { brandId: string; onChanged: () => void }) {
  const prefs = useSlice<BrandPreferenceRow[]>(() => fetchPreferences(brandId), true);
  const events = useSlice<LearningEventRow[]>(() => fetchLearningEvents(brandId), true);
  const [busy, setBusy] = useState<string | null>(null);

  const retire = async (preference: BrandPreferenceRow) => {
    setBusy(preference.id);
    try {
      await retirePreference(preference.id);
      toast("Preference retired. It no longer influences generation.");
      prefs.reload();
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e, "Could not retire the preference."));
    } finally {
      setBusy(null);
    }
  };

  if (prefs.loading && !prefs.data) return <Loading />;
  if (prefs.error) return <Failed message={prefs.error} onRetry={prefs.reload} />;

  const active = (prefs.data ?? []).filter((p) => p.state !== "RETIRED");
  const groups: Array<[string, BrandPreferenceRow[]]> = [
    ["Established", active.filter((p) => p.state === "ESTABLISHED")],
    ["Emerging", active.filter((p) => p.state === "EMERGING")],
  ];
  const recent = (events.data ?? []).slice(0, 8);

  return (
    <div className="space-y-8">
      {active.length === 0 ? (
        <Empty
          title="Nothing learned yet"
          hint="React to calibration directions and review a few generations. Scaleezy needs more than one decision before it calls something a preference."
        />
      ) : (
        groups.map(([label, rows]) =>
          rows.length === 0 ? null : (
            <div key={label}>
              <SectionTitle
                title={label}
                description={
                  label === "Established"
                    ? "Seen enough times that Scaleezy will act on it."
                    : "Noticed once. Not yet acted on strongly."
                }
              />
              <ul className="mt-3 space-y-2">
                {rows.map((preference) => (
                  <li
                    key={preference.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"
                  >
                    <div className="min-w-0">
                      <p className="font-medium">{preference.value || preference.attribute}</p>
                      <p className="text-xs text-muted-foreground">
                        {humanize(preference.category)} · {preference.attribute}
                      </p>
                    </div>
                    <span className="flex items-center gap-3">
                      <span className="text-xs text-muted-foreground">
                        {label} · {preference.evidence_count} supporting decision
                        {preference.evidence_count === 1 ? "" : "s"}
                      </span>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy === preference.id}
                        onClick={() => retire(preference)}
                      >
                        Retire
                      </Button>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ),
        )
      )}

      <div>
        <SectionTitle
          title="Recent decisions"
          description="The evidence Scaleezy learns from, newest first."
        />
        {events.loading && !events.data ? (
          <Loading rows={2} />
        ) : events.error ? (
          <p className="mt-3 text-sm text-muted-foreground">{events.error}</p>
        ) : recent.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">No decisions recorded yet.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {recent.map((event) => (
              <li
                key={event.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-sm"
              >
                <span>{EVENT_COPY[event.event_type] ?? humanize(event.event_type)}</span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Chip
                    tone={
                      event.outcome === "POSITIVE"
                        ? "user"
                        : event.outcome === "NEGATIVE"
                          ? "warn"
                          : "soft"
                    }
                  >
                    {humanize(event.outcome)}
                  </Chip>
                  {new Date(event.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- rules */

function RulesTab({ brandId, onChanged }: { brandId: string; onChanged: () => void }) {
  const slice = useSlice<BrandRuleRow[]>(() => fetchRules(brandId), true);
  const [text, setText] = useState("");
  const [hardness, setHardness] = useState<"HARD" | "SOFT">("HARD");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const add = async () => {
    setBusy("add");
    setError(null);
    try {
      await createRule(brandId, { text: text.trim(), hardness });
      toast.success(
        hardness === "HARD" ? "Rule saved. Scaleezy will never break it." : "Preference saved.",
      );
      setText("");
      slice.reload();
      onChanged();
    } catch (e) {
      setError(errorMessage(e, "Could not save the rule."));
    } finally {
      setBusy(null);
    }
  };

  const deactivate = async (rule: BrandRuleRow) => {
    setBusy(rule.id);
    try {
      await deactivateRule(rule.id);
      toast("Rule deactivated.");
      slice.reload();
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e, "Could not deactivate the rule."));
    } finally {
      setBusy(null);
    }
  };

  if (slice.loading && !slice.data) return <Loading />;
  if (slice.error) return <Failed message={slice.error} onRetry={slice.reload} />;

  const active = (slice.data ?? []).filter((rule) => rule.is_active);
  const explicit = active.filter((rule) => rule.origin === "EXPLICIT");
  const learned = active.filter((rule) => rule.origin === "LEARNED");

  return (
    <div className="space-y-8">
      <Card>
        <CardContent className="space-y-3 pt-6">
          <Label className="text-xs tracking-wide uppercase">State a brand rule</Label>
          <Input
            placeholder='e.g. "Never mention discounts in the headline."'
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant={hardness === "HARD" ? "default" : "outline"}
              onClick={() => setHardness("HARD")}
            >
              Must never break
            </Button>
            <Button
              size="sm"
              variant={hardness === "SOFT" ? "default" : "outline"}
              onClick={() => setHardness("SOFT")}
            >
              Strong preference
            </Button>
            <span className="text-xs text-muted-foreground">
              Stated rules outrank everything Scaleezy learns on its own.
            </span>
          </div>
          <InlineError message={error} />
          <Button disabled={busy === "add" || !text.trim()} onClick={add}>
            {busy === "add" ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Scale className="size-4" />
            )}
            Save rule
          </Button>
        </CardContent>
      </Card>

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
                <span className="flex items-center gap-2">
                  <Chip tone={rule.hardness === "HARD" ? "hard" : "soft"}>
                    {rule.hardness === "HARD" ? "Must never break" : "Preference"}
                  </Chip>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === rule.id}
                    onClick={() => deactivate(rule)}
                  >
                    Deactivate
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <SectionTitle
          title="Learned guidance"
          description="Inferred from your decisions. Guidance, not instruction — Scaleezy will not treat these as absolute, and they can never become hard rules on their own."
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
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === rule.id}
                    onClick={() => deactivate(rule)}
                  >
                    Deactivate
                  </Button>
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

type BrainClaimLike = { attribute: string; value: string; authority: string; source_id: string };

function ClaimList({ claims }: { claims: BrainClaimLike[] }) {
  if (!claims.length) return <p className="text-sm text-muted-foreground">Nothing yet.</p>;
  return (
    <ul className="space-y-2">
      {claims.map((claim) => (
        <li
          key={`${claim.source_id}-${claim.attribute}`}
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm"
        >
          <span className="min-w-0">
            <span className="text-muted-foreground">{claim.attribute.replaceAll("_", " ")}: </span>
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

function BrainTab({
  brandId,
  onGoToTab,
}: {
  brandId: string;
  onGoToTab: (tab: BrandMasterTab) => void;
}) {
  const slice = useSlice<BrandBrain>(() => fetchBrain(brandId), true);

  if (slice.loading && !slice.data) return <Loading rows={5} />;
  if (slice.error) return <Failed message={slice.error} onRetry={slice.reload} />;
  const brain = slice.data;
  if (!brain) return null;

  const nothingYet =
    !brain.verified_product_truth.length &&
    !brain.hard_rules.length &&
    !brain.soft_rules.length &&
    !brain.preferences.length &&
    !(brain.positioning.statements?.length ?? 0) &&
    !brain.identity.tagline;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap gap-3 rounded-xl border bg-muted/40 p-4 text-sm">
        <span className="text-muted-foreground">Version</span>
        <span className="font-mono text-xs">{brain.brain_version.slice(0, 16)}</span>
        <span className="text-muted-foreground">· Compiled</span>
        <span>{new Date(brain.compiled_at).toLocaleString()}</span>
        <span className="text-muted-foreground">
          · This is exactly what the Context Gateway hands to generation.
        </span>
      </div>

      {nothingYet ? (
        <Empty
          title="The brain is nearly empty"
          hint="It compiles from brand basics, knowledge, inspirations and what Scaleezy has learned. Add any of those and it fills in."
          action={
            <Button variant="outline" onClick={() => onGoToTab("teach")}>
              Teach Scaleezy
            </Button>
          }
        />
      ) : null}

      <div>
        <SectionTitle title="Identity" />
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          <IdentityRow label="Name" value={brain.identity.name} />
          <IdentityRow label="Industry" value={brain.identity.industry} />
          <IdentityRow label="Tagline" value={brain.identity.tagline} />
          <IdentityRow label="CTA keyword" value={brain.identity.cta_keyword ?? ""} />
          <IdentityRow label="Logo" value={brain.identity.has_logo ? "Uploaded" : "None"} />
        </dl>
        {brain.identity.canon?.length ? (
          <ul className="mt-3 space-y-2">
            {brain.identity.canon.map((item) => (
              <li key={item} className="rounded-xl border p-3 text-sm">
                {item}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <BrainSection title="Verified product truth" items={brain.verified_product_truth} />
      <BrainSection title="Positioning" items={brain.positioning.statements ?? []} />
      {brain.positioning.competitors?.length ? (
        <BrainSection title="Competitors" items={brain.positioning.competitors} />
      ) : null}
      <BrainSection title="Audience pains" items={brain.audiences.pains ?? []} />
      <BrainSection title="Audience objections" items={brain.audiences.objections ?? []} />

      <div>
        <SectionTitle title="Voice" />
        {brain.voice.tone ? <p className="mt-2 text-sm">{brain.voice.tone}</p> : null}
        <div className="mt-3">
          <ClaimList claims={brain.voice.claims ?? []} />
        </div>
      </div>

      <div>
        <SectionTitle title="Visual language" />
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(brain.visual_language.palette ?? {}).map(([name, value]) => (
            <span
              key={name}
              className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs"
            >
              <span className="size-4 rounded border" style={{ backgroundColor: String(value) }} />
              {name}
            </span>
          ))}
          {brain.visual_language.layout_preference ? (
            <span className="rounded-lg border px-3 py-2 text-xs">
              Layout: {humanize(brain.visual_language.layout_preference)}
            </span>
          ) : null}
        </div>
        <div className="mt-3">
          <ClaimList claims={brain.visual_language.claims ?? []} />
        </div>
      </div>

      {brain.hard_rules.length || brain.soft_rules.length ? (
        <div>
          <SectionTitle title="Rules in force" />
          <ul className="mt-3 space-y-2">
            {brain.hard_rules.map((rule) => (
              <li
                key={rule.id}
                className="flex items-center justify-between gap-2 rounded-xl border p-3 text-sm"
              >
                <span>{rule.text}</span>
                <Chip tone="hard">Must never break</Chip>
              </li>
            ))}
            {brain.soft_rules.map((rule) => (
              <li
                key={rule.id}
                className="flex items-center justify-between gap-2 rounded-xl border border-dashed p-3 text-sm"
              >
                <span>{rule.text}</span>
                <Chip tone="soft">{rule.origin === "LEARNED" ? "Learned" : "Preference"}</Chip>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <BrainSection title="Win patterns" items={brain.win_patterns} />
      <BrainSection title="Avoid patterns" items={brain.avoid_patterns} />
    </div>
  );
}

function IdentityRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 rounded-lg border px-3 py-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={value ? "" : "text-muted-foreground"}>{value || "—"}</dd>
    </div>
  );
}

/* --------------------------------------------------------------- attention */

function AttentionTab({
  brandId,
  overview,
  onGoToTab,
  onChanged,
}: {
  brandId: string;
  overview: BrandMasterOverview;
  onGoToTab: (tab: BrandMasterTab) => void;
  onChanged: () => void;
}) {
  const sources = useSlice<KnowledgeSource[]>(() => fetchKnowledge(brandId), true);
  const [busy, setBusy] = useState<string | null>(null);
  const conflicts = overview.conflicts;
  const missing = overview.readiness.dimensions.filter((d) => !d.complete && d.score < 0.5);
  const failed = (sources.data ?? []).filter(
    (s) => s.status === "FAILED" || s.status === "NEEDS_REVIEW",
  );

  const resolve = async (conflict: BrandConflict, claim: BrandConflict["claims"][number]) => {
    if (!claim.source_id) return;
    setBusy(claim.source_id);
    try {
      switch (claim.source_type) {
        case "brand_memory":
          await rejectMemory(claim.source_id);
          break;
        case "inspiration_signal":
          await rejectSignal(claim.source_id);
          break;
        case "brand_rule":
          await deactivateRule(claim.source_id);
          break;
        case "brand_preference":
          await retirePreference(claim.source_id);
          break;
        default:
          toast.error("This claim cannot be resolved from here.");
          return;
      }
      toast.success(`Resolved: ${humanize(conflict.attribute)}.`);
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e, "Could not resolve that."));
    } finally {
      setBusy(null);
    }
  };

  const RESOLVE_LABEL: Record<string, string> = {
    brand_memory: "Reject this fact",
    inspiration_signal: "Withdraw this preference",
    brand_rule: "Deactivate this rule",
    brand_preference: "Retire this preference",
  };

  if (!conflicts.length && !missing.length && !failed.length) {
    return (
      <Empty
        title="Nothing needs your decision"
        hint="When two equally trusted sources disagree, or a high-value input is missing, it shows up here with a way to fix it."
      />
    );
  }

  return (
    <div className="space-y-8">
      {conflicts.length ? (
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-600" />
            <div>
              <p className="font-medium">Scaleezy needs your decision</p>
              <p className="text-sm text-muted-foreground">
                These sources are equally trusted and disagree, so nothing about them is being used.
                Withdraw the one that is wrong and the other takes effect.
              </p>
            </div>
          </div>
          {conflicts.map((conflict) => (
            <Card key={`${conflict.category}-${conflict.attribute}`}>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">
                  {humanize(conflict.category)} · {humanize(conflict.attribute)}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {conflict.claims.map((claim, index) => (
                  <div
                    key={claim.source_id ?? index}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-sm"
                  >
                    <div className="min-w-0">
                      <p>{claim.value}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {humanize(claim.source_type ?? "source")} ·{" "}
                        {humanize(claim.authority ?? "")}
                      </p>
                    </div>
                    {claim.source_type && RESOLVE_LABEL[claim.source_type] ? (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy === claim.source_id}
                        onClick={() => resolve(conflict, claim)}
                      >
                        {RESOLVE_LABEL[claim.source_type]}
                      </Button>
                    ) : null}
                  </div>
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}

      {failed.length ? (
        <div>
          <SectionTitle
            title="Knowledge that needs attention"
            description="Sources whose processing did not complete."
          />
          <ul className="mt-3 space-y-2">
            {failed.map((source) => (
              <li
                key={source.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 text-sm"
              >
                <span>{source.title}</span>
                <span className="flex items-center gap-2">
                  <Chip tone="warn">{humanize(source.status)}</Chip>
                  <Button size="sm" variant="outline" onClick={() => onGoToTab("knowledge")}>
                    Open
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {missing.length ? (
        <div>
          <SectionTitle
            title="Missing high-value inputs"
            description="The gaps that hold readiness back most."
          />
          <ul className="mt-3 space-y-2">
            {missing.map((dimension) => {
              const target = tabForReadinessKey(dimension.key);
              return (
                <li
                  key={dimension.key}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 text-sm"
                >
                  <span>
                    <span className="font-medium">{dimension.label}</span>
                    <span className="text-muted-foreground"> — {dimension.hint}</span>
                  </span>
                  {target === "create" ? null : (
                    <Button size="sm" variant="outline" onClick={() => onGoToTab(target)}>
                      Fix
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------- page */

function BrandMasterPage() {
  const navigate = useNavigate();
  const search = Route.useSearch();
  const tab: BrandMasterTab = search.tab ?? "overview";
  const setTab = useCallback(
    (next: BrandMasterTab) => {
      void navigate({
        to: "/brand-master",
        search: next === "overview" ? {} : { tab: next },
        replace: true,
      });
    },
    [navigate],
  );

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
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load Brand Master.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loadOverview]);

  /** Something that changes intelligence happened; the backend recompiled the
   *  brain, this refreshes readiness and the counts that show it. */
  const refresh = useCallback(() => {
    if (brandId) void loadOverview(brandId).catch(() => undefined);
  }, [brandId, loadOverview]);
  const brandEditor = useBrandSettings({ brandId, onSaved: refresh });

  const onRebuild = useCallback(async () => {
    if (!brandId) return;
    setRebuilding(true);
    try {
      await rebuildBrain(brandId);
      await loadOverview(brandId);
      toast.success("Brand Brain recompiled.");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Could not rebuild the Brand Brain.");
    } finally {
      setRebuilding(false);
    }
  }, [brandId, loadOverview]);

  const conflictCount = overview?.brain.unresolved_conflict_count ?? 0;
  const low =
    overview?.readiness.readiness_level === "STARTING" ||
    overview?.readiness.readiness_level === "LEARNING";

  const headerActions = useMemo(() => {
    if (!overview) return null;
    return low ? (
      <>
        <Button variant="outline" asChild>
          <Link to="/publishing">Create content</Link>
        </Button>
        <Button onClick={() => setTab("teach")}>
          <GraduationCap className="size-4" /> Continue teaching Scaleezy
        </Button>
      </>
    ) : (
      <>
        <Button variant="outline" onClick={() => setTab("teach")}>
          <GraduationCap className="size-4" /> Teach Scaleezy more
        </Button>
        <Button asChild>
          <Link to="/publishing">
            <Sparkles className="size-4" /> Create content
          </Link>
        </Button>
      </>
    );
  }, [low, overview, setTab]);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Brand Master"
        title="What Scaleezy knows"
        subtitle="Every fact, reference, preference and rule behind your brand's work — where each one came from, and where to teach it more."
        actions={headerActions}
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
          hint="Every client gets a brand. Run the guided setup and this page fills in as you go."
          action={
            <Button asChild>
              <Link to="/onboarding">Start client setup</Link>
            </Button>
          }
        />
      ) : (
        <Tabs
          value={tab}
          onValueChange={(value) => setTab(value as BrandMasterTab)}
          className="space-y-6"
        >
          <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1">
            <TabsTrigger value="overview" className="gap-1.5">
              <Sparkles className="size-3.5" /> Overview
            </TabsTrigger>
            <TabsTrigger value="basics" className="gap-1.5">
              <IdCard className="size-3.5" /> Brand basics
            </TabsTrigger>
            <TabsTrigger value="products" className="gap-1.5">
              <Package className="size-3.5" /> Products &amp; Audience
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
            <TabsTrigger value="teach" className="gap-1.5">
              <GraduationCap className="size-3.5" /> Teach Scaleezy
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview">
            <OverviewTab
              overview={overview}
              onRebuild={onRebuild}
              rebuilding={rebuilding}
              onGoToTab={setTab}
            />
          </TabsContent>
          <TabsContent value="basics" forceMount>
            <BrandBasicsPanel editor={brandEditor} />
          </TabsContent>
          <TabsContent value="products" forceMount>
            <ProductsAudiencePanel editor={brandEditor} />
          </TabsContent>
          <TabsContent value="knowledge" className="space-y-6">
            <EnrichFromWebsite brandId={brandId} onChanged={refresh} />
            <KnowledgePanel brandId={brandId} onChanged={refresh} />
          </TabsContent>
          <TabsContent value="inspirations" className="space-y-10">
            <InspirationsPanel brandId={brandId} onChanged={refresh} />
            <LibraryGallery brandId={brandId} onChanged={refresh} />
          </TabsContent>
          <TabsContent value="learning">
            <LearningTab brandId={brandId} onChanged={refresh} />
          </TabsContent>
          <TabsContent value="rules">
            <RulesTab brandId={brandId} onChanged={refresh} />
          </TabsContent>
          <TabsContent value="brain">
            <BrainTab brandId={brandId} onGoToTab={setTab} />
          </TabsContent>
          <TabsContent value="attention">
            <AttentionTab
              brandId={brandId}
              overview={overview}
              onGoToTab={setTab}
              onChanged={refresh}
            />
          </TabsContent>
          <TabsContent value="teach" className="space-y-6">
            <NlNoteBox brandId={brandId} onChanged={refresh} />
            <TeachScaleezy brandId={brandId} onGoToTab={setTab} onChanged={refresh} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
