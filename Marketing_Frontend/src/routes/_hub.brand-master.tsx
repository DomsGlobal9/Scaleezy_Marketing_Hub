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
  LayoutTemplate,
  Lightbulb,
  Loader2,
  Scale,
  Sparkles,
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
import {
  Chip,
  Empty,
  Failed,
  InlineError,
  Loading,
  errorMessage,
  useSlice,
} from "@/components/marketing/brand-master-primitives";
import { CreativeResearchPanel } from "@/components/marketing/creative-research-panel";
import { HardRulesPanel } from "@/components/marketing/hard-rules-panel";
import { InspirationsPanel } from "@/components/marketing/inspirations-panel";
import { KnowledgePanel } from "@/components/marketing/knowledge-panel";
import { LearningUsagePanel } from "@/components/marketing/learning-usage-panel";
import { LibraryGallery } from "@/components/marketing/library-gallery";
import { EnrichFromWebsite, NlNoteBox } from "@/components/marketing/nl-note-box";
import { PageHeader, SectionTitle } from "@/components/marketing/primitives";
import { BrandProfilePanel } from "@/components/marketing/products-audience-panel";
import { TeachScaleezy } from "@/components/marketing/teach-scaleezy";
import { TemplatesPanel } from "@/components/marketing/templates-panel";
import {
  BRAND_MASTER_TABS,
  LEGACY_TAB_ALIASES,
  READINESS_COPY,
  createRule,
  deactivateRule,
  fetchBrain,
  fetchBrandMasterBootstrap,
  fetchKnowledge,
  fetchInspirations,
  fetchSignals,
  fetchMemories,
  fetchLearningEvents,
  fetchOverview,
  fetchPreferences,
  fetchRules,
  humanize,
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
import { useBrandSettings, type BrandDto } from "@/lib/brand-settings";

export const Route = createFileRoute("/_hub/brand-master")({
  validateSearch: (search: Record<string, unknown>): { tab?: BrandMasterTab } => {
    const raw = search["tab"];
    if (typeof raw !== "string") return {};
    // Old deep links to merged-away tabs land on the tab that absorbed them.
    const tab = LEGACY_TAB_ALIASES[raw] ?? raw;
    return (BRAND_MASTER_TABS as string[]).includes(tab) ? { tab: tab as BrandMasterTab } : {};
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
              aria-label={`${dimension.label}: ${Math.round(dimension.score * 100)}%. ${dimension.hint}`}
              onClick={() => {
                const t = tabForReadinessKey(dimension.key);
                if (t !== "create") onGoToTab(t);
              }}
              className="flex min-h-11 w-full items-center gap-3 rounded-md px-1 text-left hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
      className="rounded-xl border p-4 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <p className="font-display text-2xl leading-none font-semibold">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{label}</p>
    </button>
  );
}

function OverviewTab({
  overview,
  onGoToTab,
}: {
  overview: BrandMasterOverview;
  onGoToTab: (tab: BrandMasterTab) => void;
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
              <button
                type="button"
                onClick={() => onGoToTab("basics")}
                className="grid size-16 shrink-0 place-items-center rounded-xl border border-dashed text-muted-foreground"
                title="Add a logo"
                aria-label="Add a logo in Brand profile"
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
                Edit brand profile
              </Button>
            </div>
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
              onClick={() => onGoToTab("rules")}
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
      </div>

      <div className="space-y-6">
        <ReadinessCard overview={overview} onGoToTab={onGoToTab} />
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">What Scaleezy uses</CardTitle>
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
                Not compiled yet. It compiles automatically as you teach.
              </p>
            )}
            <div className="flex">
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                onClick={() => onGoToTab("brain")}
              >
                <Brain className="size-4" /> Open
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

/* --------------------------------------------------------- rules & learning */

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

/**
 * Stated rules and learned preferences are two halves of one governance
 * ledger, so they live on one tab: what a person instructed, what Scaleezy
 * inferred, whether any of it reaches generation, and the decisions it
 * learned from.
 */
function RulesTab({ brandId, onChanged }: { brandId: string; onChanged: () => void }) {
  const slice = useSlice<BrandRuleRow[]>(() => fetchRules(brandId), true);
  const prefs = useSlice<BrandPreferenceRow[]>(() => fetchPreferences(brandId), true);
  const events = useSlice<LearningEventRow[]>(() => fetchLearningEvents(brandId), true);
  const [text, setText] = useState("");
  const [hardness, setHardness] = useState<"HARD" | "SOFT">("HARD");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  if ((slice.loading && !slice.data) || (prefs.loading && !prefs.data)) return <Loading />;
  if (slice.error) return <Failed message={slice.error} onRetry={slice.reload} />;
  if (prefs.error) return <Failed message={prefs.error} onRetry={prefs.reload} />;

  const active = (slice.data ?? []).filter((rule) => rule.is_active);
  const explicit = active.filter((rule) => rule.origin === "EXPLICIT");
  const learned = active.filter((rule) => rule.origin === "LEARNED");
  const activePrefs = (prefs.data ?? []).filter((p) => p.state !== "RETIRED");
  const groups: Array<[string, BrandPreferenceRow[]]> = [
    ["Established", activePrefs.filter((p) => p.state === "ESTABLISHED")],
    ["Emerging", activePrefs.filter((p) => p.state === "EMERGING")],
  ];
  const recent = (events.data ?? []).slice(0, 8);

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
              aria-pressed={hardness === "HARD"}
              variant={hardness === "HARD" ? "default" : "outline"}
              onClick={() => setHardness("HARD")}
            >
              Must never break
            </Button>
            <Button
              size="sm"
              aria-pressed={hardness === "SOFT"}
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

      {/* The audit trail founders cite: every rule and preference, with
          whether it actually reaches generation. It stays this high on the
          tab deliberately. */}
      <LearningUsagePanel brandId={brandId} />

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

      {activePrefs.length === 0 ? (
        <Empty
          title="No learned preferences yet"
          hint="Calibration builds preferences over time. Corrective review guidance appears under Learned guidance immediately after the first tagged issue."
        />
      ) : (
        groups.map(([label, rows]) =>
          rows.length === 0 ? null : (
            <div key={label}>
              <SectionTitle
                title={`${label} preferences`}
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
          <Failed message={events.error} onRetry={events.reload} />
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

function BrainCorrection({
  label,
  tab,
  onGoToTab,
}: {
  label: string;
  tab: BrandMasterTab;
  onGoToTab: (tab: BrandMasterTab) => void;
}) {
  return (
    <Button variant="ghost" size="sm" onClick={() => onGoToTab(tab)}>
      Correct in {label}
    </Button>
  );
}

function BrainSection({
  title,
  items,
  correction,
  onGoToTab,
}: {
  title: string;
  items: string[];
  correction?: { label: string; tab: BrandMasterTab };
  onGoToTab: (tab: BrandMasterTab) => void;
}) {
  if (!items.length) return null;
  return (
    <div>
      <SectionTitle
        title={title}
        action={correction ? <BrainCorrection {...correction} onGoToTab={onGoToTab} /> : undefined}
      />
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
  if (!brain) return <Failed message="Brand Brain returned no data." onRetry={slice.reload} />;

  const nothingYet =
    !brain.verified_product_truth.length &&
    !brain.hard_rules.length &&
    !brain.soft_rules.length &&
    !brain.preferences.length &&
    !(brain.positioning.statements?.length ?? 0) &&
    !brain.identity.tagline &&
    !brain.identity.description &&
    !brain.audiences.stated &&
    !Object.keys(brain.visual_language.palette ?? {}).length &&
    !Object.keys(brain.visual_language.fonts ?? {}).length;

  return (
    <div className="space-y-8">
      <p className="rounded-xl border bg-muted/40 p-4 text-sm text-muted-foreground">
        Read-only preview of what Scaleezy gives generation. Use the correction links below to
        change the owning source; the next compile updates this view automatically.
      </p>

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
        <SectionTitle
          title="Identity"
          action={<BrainCorrection label="Brand profile" tab="basics" onGoToTab={onGoToTab} />}
        />
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          <IdentityRow label="Name" value={brain.identity.name} />
          <IdentityRow label="Industry" value={brain.identity.industry} />
          <IdentityRow label="Tagline" value={brain.identity.tagline} />
          <IdentityRow label="CTA keyword" value={brain.identity.cta_keyword ?? ""} />
          <IdentityRow label="Logo" value={brain.identity.has_logo ? "Uploaded" : "None"} />
        </dl>
        {brain.identity.description ? (
          <p className="mt-3 rounded-xl border p-3 text-sm">{brain.identity.description}</p>
        ) : null}
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

      <BrainSection
        title="Verified product truth"
        items={brain.verified_product_truth}
        correction={{ label: "Knowledge & facts", tab: "knowledge" }}
        onGoToTab={onGoToTab}
      />
      <BrainSection
        title="Positioning"
        items={brain.positioning.statements ?? []}
        correction={{ label: "Knowledge & facts", tab: "knowledge" }}
        onGoToTab={onGoToTab}
      />
      {brain.positioning.competitors?.length ? (
        <BrainSection
          title="Competitors"
          items={brain.positioning.competitors}
          correction={{ label: "Brand profile", tab: "basics" }}
          onGoToTab={onGoToTab}
        />
      ) : null}
      {brain.audiences.stated ? (
        <div>
          <SectionTitle
            title="Stated audience"
            action={<BrainCorrection label="Brand profile" tab="basics" onGoToTab={onGoToTab} />}
          />
          <p className="rounded-xl border p-3 text-sm">{brain.audiences.stated}</p>
        </div>
      ) : null}
      <BrainSection
        title="Audience pains"
        items={brain.audiences.pains ?? []}
        correction={{ label: "Knowledge & facts", tab: "knowledge" }}
        onGoToTab={onGoToTab}
      />
      <BrainSection
        title="Audience objections"
        items={brain.audiences.objections ?? []}
        correction={{ label: "Knowledge & facts", tab: "knowledge" }}
        onGoToTab={onGoToTab}
      />

      <div>
        <SectionTitle
          title="Voice"
          action={<BrainCorrection label="Brand profile" tab="basics" onGoToTab={onGoToTab} />}
        />
        {brain.voice.tone ? <p className="mt-2 text-sm">{brain.voice.tone}</p> : null}
        <div className="mt-3">
          <ClaimList claims={brain.voice.claims ?? []} />
        </div>
      </div>

      <div>
        <SectionTitle
          title="Visual language"
          action={<BrainCorrection label="Brand profile" tab="basics" onGoToTab={onGoToTab} />}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(brain.visual_language.palette ?? {}).map(([name, value]) => (
            <span
              key={name}
              className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs"
            >
              <span className="size-4 rounded border" style={{ backgroundColor: String(value) }} />
              {name}: {String(value)}
            </span>
          ))}
        </div>
        {Object.keys(brain.visual_language.fonts ?? {}).length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(brain.visual_language.fonts ?? {}).map(([role, family]) => (
              <span key={role} className="rounded-lg border px-3 py-2 text-xs">
                {role}: {String(family)}
              </span>
            ))}
          </div>
        ) : null}
        <div className="mt-3">
          <ClaimList claims={brain.visual_language.claims ?? []} />
        </div>
      </div>

      {brain.hard_rules.length || brain.soft_rules.length ? (
        <div>
          <SectionTitle
            title="Rules in force"
            action={
              <BrainCorrection label="Rules & preferences" tab="rules" onGoToTab={onGoToTab} />
            }
          />
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

      <BrainSection
        title="Preferred patterns"
        items={brain.win_patterns}
        correction={{ label: "Brand inspirations", tab: "inspirations" }}
        onGoToTab={onGoToTab}
      />
      <BrainSection
        title="Patterns to avoid"
        items={brain.avoid_patterns}
        correction={{ label: "Brand inspirations", tab: "inspirations" }}
        onGoToTab={onGoToTab}
      />
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
  const references = useSlice(() => fetchInspirations(brandId), true);
  const signals = useSlice(() => fetchSignals(brandId), true);
  const memories = useSlice(() => fetchMemories(brandId), true);
  const [busy, setBusy] = useState<string | null>(null);
  const conflicts = overview.conflicts;
  const needsAttention = (sources.data ?? []).filter(
    (s) => s.status === "FAILED" || s.status === "NEEDS_REVIEW",
  );
  const referenceAttention = (references.data ?? []).filter(
    (item) =>
      item.lifecycle_status !== "ARCHIVED" &&
      ["FAILED", "NEEDS_REVIEW"].includes(item.analysis_status),
  );
  const candidateFacts = (memories.data ?? []).filter(
    (item) =>
      item.status === "CANDIDATE" &&
      (!item.source ||
        sources.data?.some((source) => source.id === item.source && source.status !== "ARCHIVED")),
  ).length;
  const pendingSignals = (signals.data ?? []).filter(
    (item) =>
      item.user_confirmation === "PENDING" &&
      !item.superseded_at &&
      references.data?.some(
        (reference) =>
          reference.id === item.inspiration && reference.lifecycle_status !== "ARCHIVED",
      ),
  ).length;
  const attentionSlices = [sources, references, signals, memories];
  const incomplete = attentionSlices.some((slice) => slice.loading || slice.error || !slice.data);

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

  if (
    !incomplete &&
    !conflicts.length &&
    !needsAttention.length &&
    !referenceAttention.length &&
    !candidateFacts &&
    !pendingSignals &&
    overview.brain.compiled &&
    !overview.brain.needs_refresh
  ) {
    return (
      <Empty
        title="Nothing needs your decision"
        hint="No pending facts, inspiration decisions or source failures were found. Conflicts and missing compiled context also appear here."
      />
    );
  }

  return (
    <div className="space-y-8">
      {attentionSlices.some((slice) => slice.loading) ? <Loading rows={2} /> : null}
      {attentionSlices.map((slice, index) =>
        slice.error ? <Failed key={index} message={slice.error} onRetry={slice.reload} /> : null,
      )}
      {!overview.brain.compiled || overview.brain.needs_refresh ? (
        <div role="status" className="rounded-xl border border-amber-500/30 p-4">
          <p className="font-medium">
            {overview.brain.compiled
              ? "Brand context needs a refresh"
              : "Compiled brand context is not available yet"}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Review what Scaleezy uses and its source status before generating.
          </p>
          <Button className="mt-3" variant="outline" onClick={() => onGoToTab("brain")}>
            Check brand context
          </Button>
        </div>
      ) : null}
      {candidateFacts || pendingSignals ? (
        <div className="flex flex-wrap gap-3">
          {candidateFacts ? (
            <Button variant="outline" onClick={() => onGoToTab("knowledge")}>
              Review {candidateFacts} candidate facts
            </Button>
          ) : null}
          {pendingSignals ? (
            <Button variant="outline" onClick={() => onGoToTab("inspirations")}>
              Review {pendingSignals} inspiration observations
            </Button>
          ) : null}
        </div>
      ) : null}
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
                    ) : (
                      <span className="max-w-xs text-xs text-muted-foreground">
                        Correct this in the source section that created it.
                      </span>
                    )}
                  </div>
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}

      {needsAttention.length ? (
        <div>
          <SectionTitle
            title="Knowledge that needs attention"
            description="Failed sources need a retry; reviewed sources may contain facts waiting for your confirmation."
          />
          <ul className="mt-3 space-y-2">
            {needsAttention.map((source) => (
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
      {referenceAttention.length ? (
        <section>
          <SectionTitle
            title="Inspirations that need attention"
            description="Retry failed analysis or review the observations before they influence your brand."
          />
          <ul className="mt-3 space-y-2">
            {referenceAttention.map((item) => (
              <li
                key={item.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 text-sm"
              >
                <span>{item.title || "Untitled reference"}</span>
                <span className="flex items-center gap-2">
                  <Chip tone="warn">{humanize(item.analysis_status)}</Chip>
                  <Button size="sm" variant="outline" onClick={() => onGoToTab("inspirations")}>
                    Open inspiration
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        </section>
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
  const [initialBrand, setInitialBrand] = useState<BrandDto | null>(null);
  const [overview, setOverview] = useState<BrandMasterOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadOverview = useCallback(async (id: string) => {
    setOverview(await fetchOverview(id));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchBrandMasterBootstrap()
      .then((bootstrap) => {
        if (cancelled) return;
        setBrandId(bootstrap.brand.id);
        setInitialBrand(bootstrap.brand);
        setOverview(bootstrap.overview);
        setError(null);
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
  }, []);

  /** Something that changes intelligence happened; the backend recompiled the
   *  brain, this refreshes readiness and the counts that show it. */
  const refresh = useCallback(() => {
    if (brandId) void loadOverview(brandId).catch(() => undefined);
  }, [brandId, loadOverview]);
  const [adoptedNonce, setAdoptedNonce] = useState(0);
  const brandEditor = useBrandSettings({ brandId, initialBrand, onSaved: refresh });

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
          {/* Wrapping, not horizontally scrolling: a hidden-scrollbar strip is
              unreachable with a mouse, so overflowing tabs simply vanished. */}
          <TabsList
            aria-label="Brand Master sections"
            className="flex h-auto w-full flex-wrap justify-start gap-1"
          >
            <TabsTrigger value="overview" className="min-h-11 shrink-0 gap-1.5">
              <Sparkles className="size-3.5" /> Summary
            </TabsTrigger>
            <TabsTrigger value="basics" className="min-h-11 shrink-0 gap-1.5">
              <IdCard className="size-3.5" /> Brand profile
            </TabsTrigger>
            <TabsTrigger value="knowledge" className="min-h-11 shrink-0 gap-1.5">
              <BookOpen className="size-3.5" /> Knowledge &amp; facts
            </TabsTrigger>
            <TabsTrigger value="inspirations" className="min-h-11 shrink-0 gap-1.5">
              <Lightbulb className="size-3.5" /> Brand inspirations
            </TabsTrigger>
            <TabsTrigger value="templates" className="min-h-11 shrink-0 gap-1.5">
              <LayoutTemplate className="size-3.5" /> Templates
            </TabsTrigger>
            <TabsTrigger value="rules" className="min-h-11 shrink-0 gap-1.5">
              <Scale className="size-3.5" /> Rules &amp; preferences
            </TabsTrigger>
            <TabsTrigger value="brain" className="min-h-11 shrink-0 gap-1.5">
              <Brain className="size-3.5" /> What Scaleezy uses
            </TabsTrigger>
            <TabsTrigger value="attention" className="min-h-11 shrink-0 gap-1.5">
              {conflictCount > 0 ? (
                <AlertTriangle className="size-3.5 text-amber-600" />
              ) : (
                <Check className="size-3.5" />
              )}
              Needs review
              {conflictCount > 0 ? (
                <Badge variant="secondary" className="ml-1">
                  {conflictCount}
                </Badge>
              ) : null}
            </TabsTrigger>
            <TabsTrigger value="teach" className="min-h-11 shrink-0 gap-1.5">
              <GraduationCap className="size-3.5" /> Teach Scaleezy
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview">
            <OverviewTab overview={overview} onGoToTab={setTab} />
          </TabsContent>
          <TabsContent value="basics" forceMount className="data-[state=inactive]:hidden">
            <BrandProfilePanel editor={brandEditor} />
          </TabsContent>
          <TabsContent value="knowledge" className="space-y-6">
            <EnrichFromWebsite brandId={brandId} onChanged={refresh} />
            <KnowledgePanel brandId={brandId} onChanged={refresh} />
          </TabsContent>
          <TabsContent value="inspirations" className="space-y-10">
            {/* Adopting from research or the library writes into this brand's
                own inspirations, so the panel remounts (and re-reads) on adopt. */}
            <InspirationsPanel key={adoptedNonce} brandId={brandId} onChanged={refresh} />
            {initialBrand ? (
              <CreativeResearchPanel
                brand={initialBrand}
                onAdopted={() => {
                  setAdoptedNonce((n) => n + 1);
                  refresh();
                }}
              />
            ) : null}
            <LibraryGallery
              brandId={brandId}
              onChanged={() => {
                setAdoptedNonce((n) => n + 1);
                refresh();
              }}
            />
          </TabsContent>
          <TabsContent value="templates">
            <TemplatesPanel brandId={brandId} onChanged={refresh} />
          </TabsContent>
          <TabsContent value="rules" className="space-y-6">
            <HardRulesPanel brandId={brandId} />
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
