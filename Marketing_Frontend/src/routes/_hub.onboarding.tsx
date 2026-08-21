/**
 * Onboarding — Scaleezy learning a brand, stage by stage.
 *
 * The backend derives the stage from what actually exists, so this screen is
 * resumable by construction: refresh, leave, come back — the summary endpoint
 * says where things stand. Nothing here advances a stage by itself; uploading
 * knowledge advances the knowledge stage because the knowledge now exists.
 */
import { useCallback, useEffect, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ArrowRight,
  BookOpen,
  Check,
  Lightbulb,
  Loader2,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Wand2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/marketing/primitives";
import { api } from "@/lib/api";
import { READINESS_COPY, fetchCurrentBrand, type Readiness } from "@/lib/brand-master";

export const Route = createFileRoute("/_hub/onboarding")({
  head: () => ({
    meta: [
      { title: "Brand Setup — Scaleezy Marketing Hub" },
      { name: "description", content: "Teach Scaleezy your brand." },
    ],
  }),
  component: OnboardingPage,
});

interface Direction {
  id: string;
  label: string;
  tests_dimension: string;
  headline: string;
  caption: string;
  preview_url: string;
  verdict: "PENDING" | "LIKED" | "NOT_US" | "ADJUSTED";
  adjustment_note?: string;
}

interface Summary {
  onboarding: {
    current_stage: string;
    status: string;
    skipped_steps: string[];
  };
  readiness: Readiness;
  calibration: Direction[];
}

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

function OnboardingPage() {
  const [brandId, setBrandId] = useState<string | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [learnedFlash, setLearnedFlash] = useState(false);
  const [scoreBefore, setScoreBefore] = useState<number | null>(null);

  const load = useCallback(async (id: string) => {
    setSummary(await api<Summary>(`/api/marketing/onboarding/${id}/`));
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchCurrentBrand()
      .then((brand) => {
        if (cancelled) return null;
        setBrandId(brand.id);
        return load(brand.id);
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
  }, [load]);

  const calibrate = useCallback(async () => {
    if (!brandId) return;
    setBusy("calibrate");
    setError(null);
    try {
      await api(`/api/marketing/onboarding/${brandId}/calibrate/`, { method: "POST" });
      await load(brandId);
    } catch (e: unknown) {
      setError(
        e instanceof Error ? e.message : "Calibration is unavailable right now.",
      );
    } finally {
      setBusy(null);
    }
  }, [brandId, load]);

  const react = useCallback(
    async (direction: Direction, reaction: "like" | "not_us" | "adjust", note = "") => {
      if (!brandId) return;
      setBusy(direction.id);
      setScoreBefore(summary?.readiness.readiness_score ?? null);
      try {
        const result = await api<{ learned: boolean; summary: Summary }>(
          `/api/marketing/calibration-directions/${direction.id}/react/`,
          { method: "POST", body: { reaction, note } },
        );
        setSummary(result.summary);
        // Only claim learning when the backend says it actually persisted.
        if (result.learned) {
          setLearnedFlash(true);
          setTimeout(() => setLearnedFlash(false), 5000);
        }
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Could not record that.");
      } finally {
        setBusy(null);
      }
    },
    [brandId, load, summary],
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
    return (
      <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center">
        <p className="text-sm font-medium text-destructive">{error}</p>
        <Button
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={() => window.location.reload()}
        >
          Try again
        </Button>
      </div>
    );
  }

  if (!summary || !brandId) {
    return (
      <div className="rounded-xl border border-dashed p-10 text-center">
        <p className="font-medium">No brand yet</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Create a brand in Settings, then come back to teach Scaleezy about it.
        </p>
      </div>
    );
  }

  const stage = summary.onboarding.current_stage;
  const readiness = summary.readiness;
  const copy = READINESS_COPY[readiness.readiness_level];
  const stageIndex = STAGES.findIndex((s) => s.key === stage);
  const scoreDelta =
    scoreBefore !== null ? readiness.readiness_score - scoreBefore : 0;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Brand setup"
        title="Teach Scaleezy your brand"
        subtitle="A few minutes of teaching now makes every generation after it sharper."
      />

      {/* Stage rail */}
      <ol className="flex flex-wrap items-center gap-2">
        {STAGES.map((step, index) => {
          const done = stageIndex === -1 || index < stageIndex;
          const active = step.key === stage;
          const skipped = summary.onboarding.skipped_steps.includes(step.key);
          return (
            <li key={step.key} className="flex items-center gap-2">
              <span
                className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
                  active
                    ? "border-foreground bg-foreground text-background"
                    : done
                      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700"
                      : "border-border text-muted-foreground"
                }`}
              >
                {done ? <Check className="size-3" /> : null}
                {step.label}
                {skipped && !done ? <span className="opacity-70">(skipped)</span> : null}
              </span>
              {index < STAGES.length - 1 ? (
                <ArrowRight className="size-3 text-muted-foreground/50" />
              ) : null}
            </li>
          );
        })}
      </ol>

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

      {/* Stage content */}
      {stage === "BASICS" ? (
        <StagePanel
          icon={<Sparkles className="size-5" />}
          title="Start with the basics"
          body="Give the brand its name, industry and tagline in Settings. Scaleezy builds on whatever you tell it."
          action={
            <Button asChild>
              <Link to="/settings">Open brand settings</Link>
            </Button>
          }
        />
      ) : null}

      {stage === "KNOWLEDGE" ? (
        <StagePanel
          icon={<BookOpen className="size-5" />}
          title="Give Scaleezy something to read"
          body="Brand decks, product docs, meeting transcripts, founder notes — anything true about the business becomes persistent brand knowledge."
          action={
            <div className="flex flex-wrap gap-2">
              <Button asChild>
                <Link to="/brand-master">Upload in Brand Master</Link>
              </Button>
              <SkipButton brandId={brandId} stage="KNOWLEDGE" onDone={() => load(brandId)} />
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
              <Button asChild>
                <Link to="/brand-master">Add inspirations</Link>
              </Button>
              <SkipButton
                brandId={brandId}
                stage="INSPIRATIONS"
                onDone={() => load(brandId)}
              />
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
          showGenerate={stage === "CALIBRATION" && summary.calibration.length === 0}
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
              <Link to="/">Create content</Link>
            </Button>
          }
        />
      ) : null}
    </div>
  );
}

function StagePanel({
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

function SkipButton({
  brandId,
  stage,
  onDone,
}: {
  brandId: string;
  stage: string;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="ghost"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await api(`/api/marketing/onboarding/${brandId}/skip/`, {
            method: "POST",
            body: { stage },
          });
          onDone();
        } finally {
          setBusy(false);
        }
      }}
    >
      Skip for now
    </Button>
  );
}

function CalibrationPanel({
  directions,
  busy,
  onCalibrate,
  onReact,
  showGenerate,
}: {
  directions: Direction[];
  busy: string | null;
  onCalibrate: () => void;
  onReact: (d: Direction, r: "like" | "not_us" | "adjust", note?: string) => void;
  showGenerate: boolean;
}) {
  const [adjusting, setAdjusting] = useState<string | null>(null);
  const [note, setNote] = useState("");

  if (showGenerate) {
    return (
      <StagePanel
        icon={<Wand2 className="size-5" />}
        title="Teach Scaleezy your taste"
        body="Scaleezy will create three deliberately different directions. Your reactions become persistent brand preferences."
        action={
          <Button onClick={onCalibrate} disabled={busy === "calibrate"}>
            {busy === "calibrate" ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" /> Creating directions…
              </>
            ) : (
              "Generate 3 directions"
            )}
          </Button>
        }
      />
    );
  }

  return (
    <div>
      <p className="mb-3 font-medium">Which of these feels most like you?</p>
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
                  className="aspect-square w-full rounded-lg border object-cover"
                />
              ) : null}
              <p className="font-medium">{direction.headline || "—"}</p>
              <p className="line-clamp-4 text-sm text-muted-foreground">
                {direction.caption}
              </p>

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
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setAdjusting(null)}
                      >
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
                <Badge
                  variant={direction.verdict === "LIKED" ? "default" : "outline"}
                >
                  {direction.verdict === "LIKED"
                    ? "Liked"
                    : direction.verdict === "NOT_US"
                      ? "Not us"
                      : "Adjusted"}
                </Badge>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
