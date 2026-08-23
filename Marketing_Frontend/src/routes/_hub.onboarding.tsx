/**
 * Guided onboarding — seven steps from a bare client to a brand that can work.
 *
 * Resumable by construction, because it stores nothing. Every step's tick is
 * derived from records that already exist: the Brand columns for the first
 * three, the onboarding summary (whose stage the backend itself derives from
 * knowledge, inspirations, calibration verdicts and content) for the rest.
 * There is no wizard table, no step counter, no "progress" to fall out of sync
 * with the product — close the tab at step five and it reopens at step five
 * because the work is what remembers.
 *
 * Nothing here is a second implementation either: knowledge, inspirations and
 * calibration are the same panels Brand Master renders, and the brand fields
 * are the same sections, split differently.
 */
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight, Rocket, Sparkles, Wand2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  BrandError,
  ClientBasicsSection,
  LogoSection,
  MarketSection,
  VisualIdentitySection,
  VoiceSection,
} from "@/components/marketing/brand-basics";
import { Empty, Failed } from "@/components/marketing/brand-master-primitives";
import { InspirationsPanel } from "@/components/marketing/inspirations-panel";
import { KnowledgePanel } from "@/components/marketing/knowledge-panel";
import { PageHeader, SectionTitle } from "@/components/marketing/primitives";
import { ProductsAudienceSection } from "@/components/marketing/products-audience-panel";
import { StageRail } from "@/components/marketing/stage-rail";
import { CalibrationPanel, StagePanel } from "@/components/marketing/teach-scaleezy";
import {
  fetchCurrentBrand,
  fetchOnboarding,
  reactToDirection,
  runCalibration,
  skipOnboardingStage,
  type CalibrationDirection,
  type OnboardingStage,
  type OnboardingSummary,
} from "@/lib/brand-master";
import { useBrandSettings } from "@/lib/brand-settings";

const STEPS = [
  { key: "basics", label: "Client basics" },
  { key: "identity", label: "Brand identity" },
  { key: "context", label: "Business context" },
  { key: "knowledge", label: "Knowledge" },
  { key: "inspirations", label: "Inspirations" },
  { key: "calibration", label: "Calibration" },
  { key: "ready", label: "Ready" },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

const STEP_KEYS = STEPS.map((s) => s.key) as readonly StepKey[];

/** Which backend stage a step corresponds to, where one exists. */
const STEP_STAGE: Partial<Record<StepKey, OnboardingStage>> = {
  knowledge: "KNOWLEDGE",
  inspirations: "INSPIRATIONS",
  calibration: "CALIBRATION",
};

/** The backend's own ordering, used to read "is this stage behind us?". */
const STAGE_ORDER: OnboardingStage[] = [
  "BASICS",
  "KNOWLEDGE",
  "INSPIRATIONS",
  "CALIBRATION",
  "FIRST_GENERATION",
  "DONE",
];

export const Route = createFileRoute("/_hub/onboarding")({
  validateSearch: (search: Record<string, unknown>): { step?: StepKey } => {
    const step = search["step"];
    return typeof step === "string" && (STEP_KEYS as readonly string[]).includes(step)
      ? { step: step as StepKey }
      : {};
  },
  head: () => ({
    meta: [
      { title: "Set up your client — Scaleezy Marketing Hub" },
      {
        name: "description",
        content: "Seven steps from a new client to a brand Scaleezy can create for.",
      },
    ],
  }),
  component: OnboardingPage,
});

function OnboardingPage() {
  const navigate = useNavigate();
  const search = Route.useSearch();

  const [brandId, setBrandId] = useState<string | null>(null);
  const [summary, setSummary] = useState<OnboardingSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  // One hook instance for the whole wizard. Two would each hold their own
  // debounce timer over the same brand, and the later flush would overwrite
  // the earlier section's edit with a record that predates it.
  const editor = useBrandSettings({ brandId });

  const loadSummary = useCallback(async (id: string) => {
    setSummary(await fetchOnboarding(id));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchCurrentBrand()
      .then((brand) => {
        if (cancelled) return null;
        setBrandId(brand.id);
        return loadSummary(brand.id);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load onboarding.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loadSummary]);

  /** Something persisted changed, so every derived tick may have moved. */
  const refresh = useCallback(() => {
    if (brandId) void loadSummary(brandId).catch(() => undefined);
  }, [brandId, loadSummary]);

  const calibrate = useCallback(async () => {
    if (!brandId) return;
    setBusy("calibrate");
    setError(null);
    try {
      await runCalibration(brandId);
      await loadSummary(brandId);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Calibration is unavailable right now.");
    } finally {
      setBusy(null);
    }
  }, [brandId, loadSummary]);

  const react = useCallback(
    async (direction: CalibrationDirection, reaction: "like" | "not_us" | "adjust", note = "") => {
      setBusy(direction.id);
      try {
        const result = await reactToDirection(direction.id, reaction, note);
        setSummary(result.summary);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Could not record that.");
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const skip = useCallback(
    async (stage: OnboardingStage) => {
      if (!brandId) return;
      setBusy(`skip:${stage}`);
      try {
        setSummary(await skipOnboardingStage(brandId, stage));
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Could not skip that stage.");
      } finally {
        setBusy(null);
      }
    },
    [brandId],
  );

  const { settings } = editor;
  const counts = summary?.readiness.counts;
  const stageIndex = summary ? STAGE_ORDER.indexOf(summary.onboarding.current_stage) : 0;
  const isBehind = (stage: OnboardingStage) => stageIndex > STAGE_ORDER.indexOf(stage);

  /**
   * Completion, derived — never stored. Each rule names a record: the first
   * three read Brand columns (which is exactly what the backend's BASICS check
   * reads), the rest read the summary the backend derived from the knowledge,
   * inspiration, calibration and content tables.
   */
  const done: Record<StepKey, boolean> = {
    basics: !!settings.name && !!(settings.industry || settings.tagline),
    identity: !!settings.brandTone,
    context: !!(
      settings.description ||
      settings.audience ||
      settings.productsServices.length
    ),
    knowledge: (counts?.sources ?? 0) > 0,
    inspirations: (counts?.inspirations ?? 0) > 0,
    calibration: isBehind("CALIBRATION"),
    ready: summary?.onboarding.status === "COMPLETED",
  };

  const skipped = new Set(summary?.onboarding.skipped_steps ?? []);
  const firstOpen = STEP_KEYS.find((key) => {
    const stage = STEP_STAGE[key];
    return !done[key] && !(stage && skipped.has(stage));
  });
  const step: StepKey = search.step ?? firstOpen ?? "ready";
  const index = STEP_KEYS.indexOf(step);

  const goTo = useCallback(
    (next: StepKey) => {
      void navigate({ to: "/onboarding", search: { step: next }, replace: true });
    },
    [navigate],
  );

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  if (error && !summary) {
    return <Failed message={error} onRetry={() => window.location.reload()} />;
  }

  if (!brandId || !summary) {
    return (
      <Empty
        title="No brand to set up yet"
        hint="Every client gets a brand when it is created. Add a client from the switcher in the sidebar and setup starts here."
      />
    );
  }

  // The brand columns decide three of the seven ticks, so the rail would show
  // step one as the place to be for a beat before jumping. Waiting costs a
  // skeleton; not waiting moves the page under the reader.
  if (editor.loading) {
    return <Skeleton className="h-96 w-full rounded-xl" />;
  }

  const completedCount = STEP_KEYS.filter((key) => done[key]).length;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Client setup"
        title={settings.name ? `Set up ${settings.name}` : "Set up your client"}
        subtitle="Seven steps. Each one is ticked by work that actually exists, so you can leave at any point and come back to exactly here."
        actions={
          <Button variant="outline" asChild>
            <Link to="/brand-master">Skip to Brand Master</Link>
          </Button>
        }
      />

      {summary.awaiting_approval ? (
        <div
          role="status"
          className="flex items-start gap-3 rounded-xl border border-gold/40 bg-gold/10 px-4 py-3 text-sm"
        >
          <Sparkles className="mt-0.5 size-4 shrink-0 text-gold" />
          <p>
            <span className="font-medium text-foreground">Awaiting Scaleezy approval</span>
            <span className="text-muted-foreground">
              {" "}
              — calibration and generation unlock once approved. Keep teaching in the meantime;
              everything you add now is kept.
            </span>
          </p>
        </div>
      ) : null}

      <div className="space-y-3">
        <StageRail
          steps={STEPS.map((entry) => {
            const stage = STEP_STAGE[entry.key];
            return {
              key: entry.key,
              label: entry.label,
              done: done[entry.key],
              active: entry.key === step,
              skipped: !!stage && skipped.has(stage),
            };
          })}
          onSelect={(key) => goTo(key as StepKey)}
        />
        <div className="flex items-center gap-3">
          <Progress value={(completedCount / STEPS.length) * 100} className="h-1.5 flex-1" />
          <span className="text-xs text-muted-foreground">
            {completedCount} of {STEPS.length} done · readiness{" "}
            {summary.readiness.readiness_score}/100
          </span>
        </div>
      </div>

      <BrandError error={editor.error} />
      {error ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <Card>
        <CardContent className="space-y-8 pt-6">
          {step === "basics" ? <ClientBasicsSection editor={editor} /> : null}

          {step === "identity" ? (
            <>
              <VoiceSection editor={editor} />
              <LogoSection editor={editor} />
              <VisualIdentitySection editor={editor} />
            </>
          ) : null}

          {step === "context" ? (
            <>
              <ProductsAudienceSection editor={editor} />
              <MarketSection editor={editor} />
            </>
          ) : null}

          {step === "knowledge" ? (
            <>
              <SectionTitle
                title="Give Scaleezy something to read"
                description="Brand decks, product docs, meeting transcripts, founder notes — anything true about the business becomes persistent brand knowledge."
              />
              <KnowledgePanel brandId={brandId} onChanged={refresh} />
            </>
          ) : null}

          {step === "inspirations" ? (
            <>
              <SectionTitle
                title="Show Scaleezy what good looks like"
                description="Add a few references and say what you like about each. Screenshots, competitor posts, work you admire."
              />
              <InspirationsPanel brandId={brandId} onChanged={refresh} />
            </>
          ) : null}

          {step === "calibration" ? (
            <CalibrationPanel
              directions={summary.calibration}
              busy={busy}
              onCalibrate={calibrate}
              onReact={react}
              onSkip={() => void skip("CALIBRATION")}
              showGenerate={summary.calibration.length === 0}
              canSkip
            />
          ) : null}

          {step === "ready" ? (
            <div className="space-y-6">
              <StagePanel
                icon={<Rocket className="size-5" />}
                title={
                  done.ready
                    ? "This client is up and running"
                    : "Everything you have taught is in place"
                }
                body="Scaleezy reads all of it — basics, knowledge, references and your taste — on every generation from here on."
                action={
                  <Button asChild>
                    <Link to="/publishing">
                      <Sparkles className="size-4" /> Create your first content
                    </Link>
                  </Button>
                }
              />
              <StagePanel
                icon={<Wand2 className="size-5" />}
                title="Brand Master is where this lives from now on"
                body="Every fact, reference, preference and rule behind this brand — and where to teach it more."
                action={
                  <Button variant="outline" asChild>
                    <Link to="/brand-master">Open Brand Master</Link>
                  </Button>
                }
              />
            </div>
          ) : null}
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button
          variant="ghost"
          disabled={index <= 0}
          onClick={() => goTo(STEP_KEYS[index - 1] as StepKey)}
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <div className="flex flex-wrap gap-2">
          {STEP_STAGE[step] && !done[step] ? (
            <Button
              variant="ghost"
              disabled={busy === `skip:${STEP_STAGE[step]}`}
              onClick={() => void skip(STEP_STAGE[step] as OnboardingStage)}
            >
              Skip for now
            </Button>
          ) : null}
          {index < STEP_KEYS.length - 1 ? (
            <Button onClick={() => goTo(STEP_KEYS[index + 1] as StepKey)}>
              Next <ArrowRight className="size-4" />
            </Button>
          ) : (
            <Button asChild>
              <Link to="/brand-master">Finish in Brand Master</Link>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
