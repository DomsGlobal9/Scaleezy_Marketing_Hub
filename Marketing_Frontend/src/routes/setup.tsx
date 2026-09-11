/**
 * First-run setup — three screens, nothing else on the page.
 *
 * A new client is sent here from the hub until the brand has produced its
 * first poster (or they choose to do that later). Every screen writes through
 * the same APIs the full product uses — the brand editor, OAuth connect, the
 * generation queue — so nothing done here has to be redone in Brand Master.
 *
 *   1. About your brand   name · industry · description · logo · colour
 *   2. Connect a channel  one OAuth card per platform, skippable
 *   3. First poster       one brief → one poster → straight into Content
 *
 * The OAuth return lands on /accounts, whose hub guard sends an unfinished
 * client straight back here; step 3 is the default once the brand has a
 * description, so the loop closes without any state in the browser.
 */
import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import { ArrowRight, Check, Clock, Loader2, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { LogoSection } from "@/components/marketing/brand-basics";
import { Field } from "@/components/marketing/brand-field-editors";
import { ScaleezyLogo } from "@/components/marketing/brand-logo";
import { PlatformIcon } from "@/components/marketing/primitives";
import { StageRail } from "@/components/marketing/stage-rail";
import { api, apiPost } from "@/lib/api";
import { skipOnboardingStage } from "@/lib/brand-master";
import { useBrandSettings } from "@/lib/brand-settings";
import { PLATFORMS } from "@/lib/marketing-data";
import {
  generateFirstPoster,
  loadSetupState,
  markSetupDone,
  SETUP_ROLES,
  type FirstPoster,
  type SetupState,
} from "@/lib/setup";
import { getSelectedWorkspace, loadWorkspaces, readSelectedWorkspaceId } from "@/lib/workspace";

type Step = 1 | 2 | 3;

export const Route = createFileRoute("/setup")({
  ssr: false,
  validateSearch: (search: Record<string, unknown>): { step?: Step } => {
    const step = Number(search["step"]);
    return step === 1 || step === 2 || step === 3 ? { step } : {};
  },
  beforeLoad: async ({ context, preload }) => {
    if (!context.auth.isAuthenticated()) {
      if (preload) return;
      throw redirect({ to: "/login", search: { redirect: "/setup" }, replace: true });
    }
    await loadWorkspaces();
    const role = getSelectedWorkspace()?.role ?? "";
    if (!SETUP_ROLES.has(role)) {
      if (preload) return;
      throw redirect({ to: "/overview", replace: true });
    }
    const state = await loadSetupState();
    if (state.done) {
      if (preload) return;
      throw redirect({ to: "/overview", replace: true });
    }
    return { setup: state };
  },
  head: () => ({
    meta: [{ title: "Set up — Scaleezy Marketing Hub" }, { name: "robots", content: "noindex" }],
  }),
  component: SetupPage,
});

const STEPS: Array<{ key: Step; label: string }> = [
  { key: 1, label: "About your brand" },
  { key: 2, label: "Connect a channel" },
  { key: 3, label: "Your first poster" },
];

function SetupPage() {
  const { setup } = Route.useRouteContext() as { setup: SetupState };
  const search = Route.useSearch();
  const navigate = useNavigate();
  const defaultStep: Step = setup.brand.description.trim() ? 3 : 1;
  const step = search.step ?? defaultStep;
  const go = (next: Step) => navigate({ to: "/setup", search: { step: next }, replace: true });

  return (
    <div className="min-h-screen bg-brand-dark px-4 py-8 sm:px-6">
      <div className="mx-auto w-full max-w-2xl">
        <div className="mb-8 flex items-center justify-between gap-4">
          <ScaleezyLogo className="w-[10rem]" priority />
          <span className="text-[0.625rem] tracking-[0.18em] text-white/45 uppercase">
            Setting up {setup.brand.name || "your brand"}
          </span>
        </div>

        <div className="mb-6">
          <StageRail
            steps={STEPS.map((s) => ({
              key: String(s.key),
              label: s.label,
              done: s.key < step,
              active: s.key === step,
            }))}
            onSelect={(key) => go(Number(key) as Step)}
          />
        </div>

        <div className="surface-card p-6 sm:p-8">
          {step === 1 ? <BrandStep brandId={setup.brand.id} onNext={() => go(2)} /> : null}
          {step === 2 ? <ChannelStep onNext={() => go(3)} /> : null}
          {step === 3 ? <PosterStep setup={setup} onConnect={() => go(2)} /> : null}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- step 1 */

const INDUSTRIES = [
  "Retail",
  "Fashion",
  "Food & beverage",
  "Beauty",
  "Real estate",
  "Education",
  "Healthcare",
  "Technology",
  "Services",
];

function BrandStep({ brandId, onNext }: { brandId: string; onNext: () => void }) {
  const editor = useBrandSettings({ brandId });
  const { settings, update, flush, loading, error } = editor;
  const [leaving, setLeaving] = useState(false);
  const ready = settings.name.trim().length > 0 && settings.description.trim().length > 0;

  const next = async () => {
    setLeaving(true);
    try {
      await flush({ keepalive: false });
      markSetupDone();
      onNext();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save. Try again.");
      setLeaving(false);
    }
  };

  return (
    <>
      <StepHeading
        title="Tell Scaleezy about your brand"
        blurb="Two minutes. Everything here can be refined later in Brand Master."
      />
      {error ? <p className="mt-4 text-sm text-destructive">{error}</p> : null}
      <div className="mt-6 space-y-5">
        <Field label="Brand name">
          <Input
            value={settings.name}
            disabled={loading}
            onChange={(e) => update({ name: e.target.value })}
          />
        </Field>
        <Field label="Industry" hint="Pick the closest — it shapes the first suggestions.">
          <div className="flex flex-wrap gap-2">
            {INDUSTRIES.map((industry) => {
              const on = settings.industry === industry;
              return (
                <button
                  key={industry}
                  type="button"
                  aria-pressed={on}
                  disabled={loading}
                  onClick={() => update({ industry }, { immediate: true })}
                  className={
                    on
                      ? "rounded-full border border-foreground bg-foreground px-3 py-1 text-xs font-medium text-background"
                      : "rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground hover:border-foreground/40"
                  }
                >
                  {industry}
                </button>
              );
            })}
          </div>
          <Input
            className="mt-2"
            placeholder="Or type your own"
            value={INDUSTRIES.includes(settings.industry) ? "" : settings.industry}
            disabled={loading}
            onChange={(e) => update({ industry: e.target.value })}
          />
        </Field>
        <Field
          label="What do you sell, and to whom?"
          hint="Plain words. Every poster Scaleezy makes reads this first."
        >
          <Textarea
            rows={4}
            placeholder="e.g. Handloom sarees for working women in Hyderabad who want festive wear they can also wear to the office."
            value={settings.description}
            disabled={loading}
            onChange={(e) => update({ description: e.target.value })}
          />
        </Field>
        <Field label="Website" hint="Optional.">
          <Input
            type="url"
            placeholder="https://"
            value={settings.website}
            disabled={loading}
            onChange={(e) => update({ website: e.target.value })}
          />
        </Field>
        <Field label="Main brand colour" hint="Optional. Posters are composed around it.">
          <input
            type="color"
            aria-label="Main brand colour"
            className="h-10 w-16 cursor-pointer rounded-lg border border-border bg-transparent"
            value={settings.palette["primary"] || "#221F3C"}
            disabled={loading}
            onChange={(e) => update({ palette: { ...settings.palette, primary: e.target.value } })}
          />
        </Field>
        <LogoSection editor={editor} />
      </div>
      <StepActions>
        <Button onClick={next} disabled={!ready || loading || leaving}>
          {leaving ? <Loader2 className="size-4 animate-spin" /> : null}
          Continue <ArrowRight className="size-4" />
        </Button>
      </StepActions>
    </>
  );
}

/* ------------------------------------------------------------- step 2 */

interface ConnectionRow {
  platform: string;
  account_name?: string;
  status: string;
}

function useConnections() {
  const [rows, setRows] = useState<ConnectionRow[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    api<unknown>("/api/marketing/social-accounts/")
      .then((payload) => {
        const list = Array.isArray(payload)
          ? payload
          : ((payload as { results?: unknown[] })?.results ?? []);
        if (!cancelled) setRows(list as ConnectionRow[]);
      })
      .catch(() => {
        if (!cancelled) setRows([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return rows;
}

function ChannelStep({ onNext }: { onNext: () => void }) {
  const rows = useConnections();
  const role = getSelectedWorkspace()?.role ?? "";
  const canConnect = role === "OWNER" || role === "ADMIN";
  const [busy, setBusy] = useState<string | null>(null);

  const connect = async (platform: string) => {
    setBusy(platform);
    try {
      const data = await apiPost<{ authorization_url?: string }>(
        "/api/marketing/social-accounts/connect/",
        { workspace_id: readSelectedWorkspaceId(), platform: platform.toUpperCase() },
      );
      if (!data?.authorization_url) throw new Error("That platform is not available right now.");
      window.location.href = data.authorization_url;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not start the connection.");
      setBusy(null);
    }
  };

  return (
    <>
      <StepHeading
        title="Connect one channel"
        blurb="Approved posts publish here. You authorise on the platform's own page — Scaleezy never sees your password."
      />
      {!canConnect ? (
        <p className="mt-4 text-sm text-muted-foreground">
          Connecting accounts needs a workspace admin. You can skip this for now.
        </p>
      ) : null}
      <ul className="mt-6 grid gap-3 sm:grid-cols-2">
        {PLATFORMS.filter((p) => p.supported).map((p) => {
          const connected = rows?.find(
            (r) => r.platform.toLowerCase() === p.id && r.status === "CONNECTED",
          );
          return (
            <li key={p.id} className="flex items-center gap-3 rounded-xl border border-border p-3">
              <PlatformIcon platform={p.id} />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-foreground">{p.name}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {connected ? connected.account_name || "Connected" : p.accountType}
                </span>
              </span>
              {connected ? (
                <Check className="size-4 text-success" aria-label="Connected" />
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!canConnect || busy !== null}
                  onClick={() => connect(p.id)}
                >
                  {busy === p.id ? <Loader2 className="size-4 animate-spin" /> : "Connect"}
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      <StepActions>
        <Button variant="ghost" onClick={onNext}>
          Skip for now
        </Button>
        <Button onClick={onNext}>
          Continue <ArrowRight className="size-4" />
        </Button>
      </StepActions>
    </>
  );
}

/* ------------------------------------------------------------- step 3 */

function PosterStep({ setup, onConnect }: { setup: SetupState; onConnect: () => void }) {
  const navigate = useNavigate();
  const brand = setup.brand;
  const awaitingApproval = brand.status === "PENDING";
  const [brief, setBrief] = useState(
    `An introduction post for ${brand.name}${brand.industry ? ` (${brand.industry})` : ""}: what we do and why it matters to our customers.`,
  );
  const [working, setWorking] = useState(false);
  const [result, setResult] = useState<FirstPoster | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  const create = async () => {
    setWorking(true);
    setError(null);
    abort.current = new AbortController();
    try {
      setResult(
        await generateFirstPoster(brief.trim(), `${brand.name} introduction`, abort.current.signal),
      );
      markSetupDone();
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError"))
        setError(e instanceof Error ? e.message : "Generation failed.");
    } finally {
      setWorking(false);
    }
  };

  const finish = async (destination: "/overview" | "/review") => {
    setLeaving(true);
    try {
      if (!result) await skipOnboardingStage(brand.id, "FIRST_GENERATION");
      markSetupDone();
      if (destination === "/review") {
        // ?item= opens the tab that holds the new draft and scrolls to it.
        await navigate({
          to: "/review",
          search: result?.contentItemId ? { item: result.contentItemId } : {},
          replace: true,
        });
      } else {
        await navigate({ to: "/overview", replace: true });
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not finish setup.");
      setLeaving(false);
    }
  };

  if (result) {
    return (
      <>
        <StepHeading
          title="Your first poster is ready"
          blurb="It is saved as a draft under Content, where you can edit it, approve it and publish it."
        />
        <div className="mt-6 overflow-hidden rounded-xl border border-border">
          {result.imageUrl ? (
            <img src={result.imageUrl} alt={result.headline} className="w-full" />
          ) : (
            <p className="p-4 text-sm text-muted-foreground">
              {result.imageFailed
                ? "The picture did not come through this time — the copy is saved and you can retry the image from Content."
                : "No preview yet."}
            </p>
          )}
          <div className="border-t border-border p-4">
            <p className="font-semibold text-foreground">{result.headline}</p>
            <p className="mt-1 text-sm whitespace-pre-wrap text-muted-foreground">
              {result.caption}
            </p>
          </div>
        </div>
        <StepActions>
          <Button variant="ghost" onClick={() => finish("/overview")} disabled={leaving}>
            Go to dashboard
          </Button>
          <Button onClick={() => finish("/review")} disabled={leaving}>
            Open in Content <ArrowRight className="size-4" />
          </Button>
        </StepActions>
      </>
    );
  }

  if (working) {
    return (
      <div className="grid min-h-[16rem] place-items-center text-center">
        <div>
          <Loader2 className="mx-auto size-8 animate-spin text-primary" />
          <p className="mt-4 font-semibold text-foreground">Making your first poster…</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Usually under a minute. Copy first, then the picture.
          </p>
          <Button variant="ghost" className="mt-4" onClick={() => abort.current?.abort()}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <>
      <StepHeading
        title="Make your first poster"
        blurb="Say what the post is about. Scaleezy writes the headline and caption and composes the picture with your brand."
      />
      {awaitingApproval ? (
        <p className="mt-4 flex items-start gap-2 rounded-xl border border-gold/30 bg-gold/10 px-3 py-2.5 text-sm text-foreground">
          <Clock className="mt-0.5 size-4 shrink-0" />
          <span>
            Your account is awaiting Scaleezy approval. Poster generation unlocks the moment it is
            approved — everything you set up here is kept.
          </span>
        </p>
      ) : null}
      {error ? <p className="mt-4 text-sm text-destructive">{error}</p> : null}
      <div className="mt-6">
        <Textarea
          rows={4}
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          disabled={awaitingApproval}
        />
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        Connected channels are not needed for this step —{" "}
        <button type="button" className="underline underline-offset-4" onClick={onConnect}>
          connect one
        </button>{" "}
        whenever you are ready to publish.
      </p>
      <StepActions>
        <Button variant="ghost" onClick={() => finish("/overview")} disabled={leaving}>
          Do this later
        </Button>
        <Button onClick={create} disabled={awaitingApproval || !brief.trim() || leaving}>
          <Sparkles className="size-4" /> Create my first poster
        </Button>
      </StepActions>
    </>
  );
}

/* ---------------------------------------------------------- primitives */

function StepHeading({ title, blurb }: { title: string; blurb: string }) {
  return (
    <>
      <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground">
        {title}
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">{blurb}</p>
    </>
  );
}

function StepActions({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-8 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-5">
      {children}
    </div>
  );
}
