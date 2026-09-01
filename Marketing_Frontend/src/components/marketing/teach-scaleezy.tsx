/**
 * Teach Scaleezy — the PR6 guided setup, embedded in Brand Master.
 *
 * The backend derives the stage from what actually exists, so this is
 * resumable by construction: refresh, leave, come back — the summary endpoint
 * says where things stand. Nothing here advances a stage by itself; adding
 * knowledge advances the knowledge stage because the knowledge now exists.
 * Each stage hands the user to the Brand Master tab that owns the work.
 */
import { Link } from "@tanstack/react-router";
import {
  BookOpen,
  Lightbulb,
  Loader2,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Wand2,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Failed } from "@/components/marketing/brand-master-primitives";
import { StageRail } from "@/components/marketing/stage-rail";
import {
  READINESS_COPY,
  fetchOnboarding,
  reactToDirection,
  runCalibration,
  skipOnboardingStage,
  type BrandMasterTab,
  type CalibrationDirection,
  type OnboardingSummary,
} from "@/lib/brand-master";

const STAGES = [
  { key: "BASICS", label: "Brand basics" },
  { key: "KNOWLEDGE", label: "Knowledge" },
  { key: "INSPIRATIONS", label: "Inspirations" },
  { key: "CALIBRATION", label: "Your taste" },
  { key: "FIRST_GENERATION", label: "First content" },
] as const;

const DIMENSION_COPY: Record<string, string> = {
  minimal_restrained: "Minimal & restrained",
  expressive_editorial: "Expressive & editorial",
  conversion_focused: "Conversion-focused",
};

export function TeachScaleezy({
  brandId,
  onGoToTab,
  onChanged,
}: {
  brandId: string;
  onGoToTab: (tab: BrandMasterTab) => void;
  onChanged: () => void;
}) {
  const [summary, setSummary] = useState<OnboardingSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [learnedFlash, setLearnedFlash] = useState(false);
  const [scoreBefore, setScoreBefore] = useState<number | null>(null);

  const load = useCallback(async () => {
    setSummary(await fetchOnboarding(brandId));
  }, [brandId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    load()
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const calibrate = useCallback(async () => {
    setBusy("calibrate");
    setError(null);
    try {
      await runCalibration(brandId);
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Calibration is unavailable right now.");
    } finally {
      setBusy(null);
    }
  }, [brandId, load]);

  const react = useCallback(
    async (direction: CalibrationDirection, reaction: "like" | "not_us" | "adjust", note = "") => {
      setBusy(direction.id);
      setScoreBefore(summary?.readiness.readiness_score ?? null);
      try {
        const result = await reactToDirection(direction.id, reaction, note);
        setSummary(result.summary);
        // Only claim learning when the backend says it actually persisted.
        if (result.learned) {
          setLearnedFlash(true);
          setTimeout(() => setLearnedFlash(false), 5000);
          onChanged();
        }
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Could not record that.");
      } finally {
        setBusy(null);
      }
    },
    [onChanged, summary],
  );

  const skip = useCallback(
    async (stage: string) => {
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

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (error && !summary) {
    return <Failed message={error} onRetry={() => void load()} />;
  }
  if (!summary) return null;

  const stage = summary.onboarding.current_stage;
  const readiness = summary.readiness;
  const copy = READINESS_COPY[readiness.readiness_level];
  const stageIndex = STAGES.findIndex((s) => s.key === stage);
  const scoreDelta = scoreBefore !== null ? readiness.readiness_score - scoreBefore : 0;

  return (
    <div className="space-y-6">
      <p className="max-w-2xl text-sm text-muted-foreground">
        A few minutes of teaching now makes every generation after it sharper. Each step happens in
        the tab that owns it — progress made anywhere in Brand Master counts here.
      </p>

      <StageRail
        steps={STAGES.map((step, index) => ({
          key: step.key,
          label: step.label,
          // stageIndex === -1 is the DONE stage: nothing is still ahead.
          done: stageIndex === -1 || index < stageIndex,
          active: step.key === stage,
          skipped: summary.onboarding.skipped_steps.includes(step.key),
        }))}
      />

      {/* Readiness strip */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-6 pt-6">
          <div className="min-w-40">
            <p className="label-eyebrow">Brand readiness</p>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="font-display text-3xl font-semibold">
                {readiness.readiness_score}
              </span>
              <span className="text-sm text-muted-foreground">/ 100 · {copy.label}</span>
              {learnedFlash && scoreDelta > 0 ? (
                <Badge className="bg-emerald-600 text-white">+{scoreDelta}</Badge>
              ) : null}
            </div>
          </div>
          <Progress value={readiness.readiness_score} className="min-w-40 flex-1" />
          <p className="w-full text-sm text-muted-foreground sm:w-auto">
            {readiness.recommended_next_action.label}
          </p>
        </CardContent>
      </Card>

      {learnedFlash ? (
        <div className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm font-medium text-emerald-800">
          <Sparkles className="size-4" /> Scaleezy learned from your choice.
        </div>
      ) : null}

      {error ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {stage === "BASICS" ? (
        <StagePanel
          icon={<Sparkles className="size-5" />}
          title="Start with the basics"
          body="Give the brand its name, industry and tagline. Scaleezy builds on whatever you tell it."
          action={<Button onClick={() => onGoToTab("basics")}>Open brand basics</Button>}
        />
      ) : null}

      {stage === "KNOWLEDGE" ? (
        <StagePanel
          icon={<BookOpen className="size-5" />}
          title="Give Scaleezy something to read"
          body="Brand decks, product docs, meeting transcripts, founder notes — anything true about the business becomes persistent brand knowledge."
          action={
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => onGoToTab("knowledge")}>Add knowledge</Button>
              <Button
                variant="ghost"
                disabled={busy === "skip:KNOWLEDGE"}
                onClick={() => skip("KNOWLEDGE")}
              >
                Skip for now
              </Button>
            </div>
          }
        />
      ) : null}

      {stage === "INSPIRATIONS" ? (
        <StagePanel
          icon={<Lightbulb className="size-5" />}
          title="Show Scaleezy what good looks like"
          body="Add a few references — screenshots, competitor posts, work you admire — and say what you like about each."
          action={
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => onGoToTab("inspirations")}>Add inspirations</Button>
              <Button
                variant="ghost"
                disabled={busy === "skip:INSPIRATIONS"}
                onClick={() => skip("INSPIRATIONS")}
              >
                Skip for now
              </Button>
            </div>
          }
        />
      ) : null}

      {stage === "CALIBRATION" || summary.calibration.length > 0 ? (
        <CalibrationPanel
          directions={summary.calibration}
          busy={busy}
          onCalibrate={calibrate}
          onReact={react}
          onSkip={() => skip("CALIBRATION")}
          showGenerate={stage === "CALIBRATION" && summary.calibration.length === 0}
          canSkip={stage === "CALIBRATION"}
        />
      ) : null}

      {stage === "FIRST_GENERATION" || stage === "DONE" ? (
        <StagePanel
          icon={<Wand2 className="size-5" />}
          title={
            stage === "DONE"
              ? "Your brand is ready to create"
              : "Create your first brand-aligned content"
          }
          body="Everything Scaleezy has learned goes into every generation from here on."
          action={
            <Button asChild>
              <Link to="/publishing">Create content</Link>
            </Button>
          }
        />
      ) : null}
    </div>
  );
}

/** The shared stage card: used by the stage blocks above and by
 *  CalibrationPanel below. The onboarding wizard it was originally exported
 *  for is retired — /onboarding now redirects into this tab. */
export function StagePanel({
  icon,
  title,
  body,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  action: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-5 pt-6">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl border bg-muted/40">
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-medium">{title}</p>
          <p className="mt-0.5 max-w-xl text-sm text-muted-foreground">{body}</p>
        </div>
        {action}
      </CardContent>
    </Card>
  );
}

export function CalibrationPanel({
  directions,
  busy,
  onCalibrate,
  onReact,
  onSkip,
  showGenerate,
  canSkip,
}: {
  directions: CalibrationDirection[];
  busy: string | null;
  onCalibrate: () => void;
  onReact: (d: CalibrationDirection, r: "like" | "not_us" | "adjust", note?: string) => void;
  onSkip: () => void;
  showGenerate: boolean;
  canSkip: boolean;
}) {
  const [adjusting, setAdjusting] = useState<string | null>(null);
  const [note, setNote] = useState("");

  if (showGenerate) {
    return (
      <StagePanel
        icon={<Wand2 className="size-5" />}
        title="Teach Scaleezy your taste"
        body="Scaleezy creates three deliberately different directions through your configured AI provider. Your reactions become persistent brand preferences."
        action={
          <div className="flex flex-wrap gap-2">
            <Button onClick={onCalibrate} disabled={busy === "calibrate"}>
              {busy === "calibrate" ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" /> Creating directions…
                </>
              ) : (
                "Generate 3 directions"
              )}
            </Button>
            <Button variant="ghost" disabled={busy === "skip:CALIBRATION"} onClick={onSkip}>
              Skip for now
            </Button>
          </div>
        }
      />
    );
  }

  const pending = directions.filter((d) => d.verdict === "PENDING").length;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium">Which of these feels most like you?</p>
        {canSkip && pending > 0 ? (
          <Button size="sm" variant="ghost" disabled={busy === "skip:CALIBRATION"} onClick={onSkip}>
            Skip the rest
          </Button>
        ) : null}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {directions.map((direction) => (
          <Card key={direction.id}>
            <CardContent className="space-y-3 pt-6">
              <Badge variant="secondary">
                {DIMENSION_COPY[direction.tests_dimension] ?? direction.tests_dimension}
              </Badge>
              {direction.preview_url ? (
                <img
                  src={direction.preview_url}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  className="aspect-square w-full rounded-lg border object-cover"
                />
              ) : (
                <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                  Copy only — no visual was produced for this direction, so nothing visual is
                  learned from your verdict on it.
                </p>
              )}
              <p className="font-medium">{direction.headline || "—"}</p>
              <p className="line-clamp-4 text-sm text-muted-foreground">{direction.caption}</p>

              {direction.verdict === "PENDING" ? (
                adjusting === direction.id ? (
                  <div className="space-y-2">
                    <Textarea
                      placeholder='e.g. "Less text. Warmer photography."'
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      rows={2}
                    />
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        disabled={!note.trim() || busy === direction.id}
                        onClick={() => {
                          onReact(direction, "adjust", note);
                          setAdjusting(null);
                          setNote("");
                        }}
                      >
                        Send
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setAdjusting(null)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      disabled={busy === direction.id}
                      onClick={() => onReact(direction, "like")}
                    >
                      <ThumbsUp className="mr-1 size-3.5" /> Like
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy === direction.id}
                      onClick={() => onReact(direction, "not_us")}
                    >
                      <ThumbsDown className="mr-1 size-3.5" /> Not us
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy === direction.id}
                      onClick={() => setAdjusting(direction.id)}
                    >
                      Adjust
                    </Button>
                  </div>
                )
              ) : (
                <div className="space-y-1">
                  <Badge variant={direction.verdict === "LIKED" ? "default" : "outline"}>
                    {direction.verdict === "LIKED"
                      ? "Liked"
                      : direction.verdict === "NOT_US"
                        ? "Not us"
                        : "Adjusted"}
                  </Badge>
                  {direction.adjustment_note ? (
                    <p className="text-xs text-muted-foreground">“{direction.adjustment_note}”</p>
                  ) : null}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
