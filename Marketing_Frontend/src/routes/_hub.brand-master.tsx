/**
 * Brand Master — everything Scaleezy understands about a brand, in three tabs.
 *
 *   About the brand   the first-party record, and what the brain compiled from it
 *   Show & tell       anything you give Scaleezy to learn from: notes, documents,
 *                     references, templates — and the suggestions awaiting a decision
 *   Rules             what must never happen, and what Scaleezy has learned to prefer
 *
 * Every number comes from a backend that owns it; nothing is filled in
 * optimistically. Deep links address sections (`?tab=knowledge`), and the
 * page opens the owning tab and scrolls there.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { AlertTriangle, Brain, IdCard, Lightbulb, Loader2, Scale, Sparkles } from "lucide-react";
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
import { TemplatesPanel } from "@/components/marketing/templates-panel";
import {
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
  resolveBrandMasterTarget,
  retirePreference,
  tabForReadinessKey,
  type BrandBrain,
  type BrandConflict,
  type BrandMasterOverview,
  type BrandMasterSection,
  type BrandMasterTab,
  type BrandPreferenceRow,
  type BrandRuleRow,
  type KnowledgeSource,
  type LearningEventRow,
} from "@/lib/brand-master";
import { useBrandSettings, type BrandDto } from "@/lib/brand-settings";

export const Route = createFileRoute("/_hub/brand-master")({
  validateSearch: (
    search: Record<string, unknown>,
  ): { tab?: BrandMasterTab | BrandMasterSection } => {
    const raw = search["tab"];
    if (typeof raw !== "string") return {};
    const target = resolveBrandMasterTarget(raw);
    return target ? { tab: target.section ?? target.tab } : {};
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

/* --------------------------------------------------------------- readiness */

function ReadinessStrip({
  overview,
  onGoTo,
}: {
  overview: BrandMasterOverview;
  onGoTo: (section: BrandMasterSection) => void;
}) {
  const { readiness } = overview;
  const copy = READINESS_COPY[readiness.readiness_level];
  const target = tabForReadinessKey(readiness.recommended_next_action.key);
  return (
    <div className="surface-card flex flex-wrap items-center gap-x-6 gap-y-3 p-4">
      <div className="flex items-center gap-3">
        <span className="font-display text-3xl leading-none font-semibold">
          {readiness.readiness_score}
        </span>
        <span className="text-sm text-muted-foreground">
          / 100
          <Badge variant="secondary" className="ml-2">
            {copy.label}
          </Badge>
        </span>
      </div>
      <Progress value={readiness.readiness_score} className="h-1.5 w-full sm:w-40" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">
          Next: {readiness.recommended_next_action.label}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {readiness.recommended_next_action.detail}
        </p>
      </div>
      {target === "create" ? (
        <Button asChild size="sm">
          <Link to="/publishing">Create content</Link>
        </Button>
      ) : (
        <Button size="sm" variant="outline" onClick={() => onGoTo(target)}>
          Go there
        </Button>
      )}
    </div>
  );
}

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
          <Label className="text-xs tracking-wide uppercase">Add a rule in your own words</Label>
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
              Always
            </Button>
            <Button
              size="sm"
              aria-pressed={hardness === "SOFT"}
              variant={hardness === "SOFT" ? "default" : "outline"}
              onClick={() => setHardness("SOFT")}
            >
              Prefer
            </Button>
            <span className="text-xs text-muted-foreground">
              Your rules always win over anything Scaleezy picks up by itself.
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
        <SectionTitle title="Your rules" description="Written by you. Scaleezy follows them." />
        {explicit.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">None yet.</p>
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
          title="What Scaleezy has picked up"
          description="Patterns from your approvals and edits. Treated as preferences, never as rules — you can retire any of them."
        />
        {learned.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">Nothing yet.</p>
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
          title="Nothing picked up yet"
          hint="Approve, edit and reject a few posts and Scaleezy starts learning what you like."
        />
      ) : (
        groups.map(([label, rows]) =>
          rows.length === 0 ? null : (
            <div key={label}>
              <SectionTitle
                title={label === "Established" ? "Sure about these" : "Starting to notice"}
                description={
                  label === "Established"
                    ? "Seen often enough that Scaleezy acts on it."
                    : "Seen once or twice. Not acted on strongly yet."
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
          description="What Scaleezy learned from, newest first."
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
  tab: BrandMasterSection;
  onGoToTab: (section: BrandMasterSection) => void;
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
  correction?: { label: string; tab: BrandMasterSection };
  onGoToTab: (section: BrandMasterSection) => void;
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
  onGoToTab: (section: BrandMasterSection) => void;
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
            <Button variant="outline" onClick={() => onGoToTab("knowledge")}>
              Show Scaleezy something
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
  onGoToTab: (section: BrandMasterSection) => void;
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

/**
 * The attention panel is only mounted when there is something to decide —
 * its own loading and empty states would otherwise be the first thing on the
 * Show & tell tab for a brand that has nothing waiting.
 */
function attentionCount(overview: BrandMasterOverview): number {
  const { readiness, brain } = overview;
  return readiness.counts.unresolved_conflicts + (brain.compiled && !brain.needs_refresh ? 0 : 1);
}

function BrandMasterPage() {
  const navigate = useNavigate();
  const search = Route.useSearch();
  const target = search.tab ? resolveBrandMasterTarget(search.tab) : null;
  const tab: BrandMasterTab = target?.tab ?? "about";
  const setTab = useCallback(
    (next: BrandMasterTab) => {
      void navigate({
        to: "/brand-master",
        search: next === "about" ? {} : { tab: next },
        replace: true,
      });
    },
    [navigate],
  );
  // Switch to the owning tab, then scroll once its content has rendered.
  const goTo = useCallback(
    (section: BrandMasterSection) => {
      void navigate({ to: "/brand-master", search: { tab: section }, replace: true });
    },
    [navigate],
  );
  const section = target?.section;
  useEffect(() => {
    // The first section of a tab is already in view once the tab opens.
    if (!section || section === "basics" || section === "rules") return;
    const timer = window.setTimeout(() => {
      document.getElementById(section)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
    return () => window.clearTimeout(timer);
  }, [section]);

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
  const pending = overview ? attentionCount(overview) : 0;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Brand Master"
        title="What Scaleezy knows"
        subtitle="Your brand, what you have shown Scaleezy, and the rules it works to."
        actions={
          <Button asChild>
            <Link to="/publishing">
              <Sparkles className="size-4" /> Create content
            </Link>
          </Button>
        }
      />

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-20 w-full rounded-xl" />
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
              <Link to="/setup" search={{}}>
                Start setup
              </Link>
            </Button>
          }
        />
      ) : (
        <>
          <ReadinessStrip overview={overview} onGoTo={goTo} />
          <Tabs
            value={tab}
            onValueChange={(value) => setTab(value as BrandMasterTab)}
            className="space-y-6"
          >
            <TabsList
              aria-label="Brand Master sections"
              className="flex h-auto w-full flex-wrap justify-start gap-1"
            >
              <TabsTrigger value="about" className="min-h-11 shrink-0 gap-1.5">
                <IdCard className="size-3.5" /> About the brand
              </TabsTrigger>
              <TabsTrigger value="show" className="min-h-11 shrink-0 gap-1.5">
                <Lightbulb className="size-3.5" /> Show &amp; tell
                {pending > 0 ? (
                  <Badge variant="secondary" className="ml-1">
                    {pending}
                  </Badge>
                ) : null}
              </TabsTrigger>
              <TabsTrigger value="rules" className="min-h-11 shrink-0 gap-1.5">
                <Scale className="size-3.5" /> Rules
              </TabsTrigger>
            </TabsList>

            <TabsContent
              value="about"
              forceMount
              className="space-y-10 data-[state=inactive]:hidden"
            >
              <div id="basics">
                <BrandProfilePanel editor={brandEditor} />
              </div>
              <details id="brain" className="group rounded-xl border border-border p-4">
                <summary className="cursor-pointer list-none text-sm font-semibold text-foreground">
                  <Brain className="mr-1.5 inline size-4" /> What Scaleezy is working from
                  <span className="ml-2 font-normal text-muted-foreground">
                    — the compiled view every generation reads
                  </span>
                </summary>
                <div className="mt-4">
                  {tab === "about" ? <BrainTab brandId={brandId} onGoToTab={goTo} /> : null}
                </div>
              </details>
            </TabsContent>

            <TabsContent value="show" className="space-y-10">
              {pending > 0 ? (
                <section id="attention">
                  <SectionTitle
                    title="Needs your decision"
                    description="Suggestions and conflicts Scaleezy will not act on until you say so."
                  />
                  <div className="mt-4">
                    <AttentionTab
                      brandId={brandId}
                      overview={overview}
                      onGoToTab={goTo}
                      onChanged={refresh}
                    />
                  </div>
                </section>
              ) : null}
              <NlNoteBox brandId={brandId} onChanged={refresh} />
              <section id="knowledge" className="space-y-6">
                <SectionTitle title="Documents, links and facts" />
                <EnrichFromWebsite brandId={brandId} onChanged={refresh} />
                <KnowledgePanel brandId={brandId} onChanged={refresh} />
              </section>
              <section id="inspirations" className="space-y-6">
                <SectionTitle title="Work you like" />
                <InspirationsPanel key={adoptedNonce} brandId={brandId} onChanged={refresh} />
                <details className="rounded-xl border border-border p-4">
                  <summary className="cursor-pointer list-none text-sm font-semibold text-foreground">
                    Find more references
                    <span className="ml-2 font-normal text-muted-foreground">
                      — web research and the Scaleezy library
                    </span>
                  </summary>
                  <div className="mt-6 space-y-10">
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
                  </div>
                </details>
              </section>
              <section id="templates">
                <SectionTitle title="Your poster templates" />
                <div className="mt-4">
                  <TemplatesPanel brandId={brandId} onChanged={refresh} />
                </div>
              </section>
            </TabsContent>

            <TabsContent value="rules" className="space-y-6">
              <div id="rules" className="space-y-6">
                <HardRulesPanel brandId={brandId} />
                <RulesTab brandId={brandId} onChanged={refresh} />
              </div>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}
