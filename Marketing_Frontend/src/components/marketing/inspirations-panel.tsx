/**
 * Inspirations — the PR2 inspiration system, used from Brand Master.
 *
 * A reference (link, post, reel, screenshot, upload) plus what the user says
 * about it. Stated preferences are recorded as USER-origin signals, which
 * outrank anything inferred and compile into the Brand Brain the moment they
 * are saved. Automatic analysis of a reference is not available yet, and the
 * panel says so rather than showing an "Analyse" button that returns 501.
 */
import {
  Archive,
  ExternalLink,
  FileText,
  Image as ImageIcon,
  Link2,
  Loader2,
  Plus,
  Upload,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import {
  Chip,
  Empty,
  Failed,
  InlineError,
  Loading,
  errorMessage,
  useSlice,
} from "@/components/marketing/brand-master-primitives";
import {
  INSPIRATION_LINK_TYPES,
  INSPIRATION_UPLOAD_TYPES,
  SIGNAL_CATEGORIES,
  archiveInspiration,
  confirmSignal,
  createInspiration,
  createSignal,
  fetchInspirations,
  fetchSignals,
  humanize,
  rejectSignal,
  uploadInspiration,
  type Inspiration,
  type InspirationInput,
  type InspirationSignalRow,
  type SignalSentiment,
} from "@/lib/brand-master";
import { cn } from "@/lib/utils";

const PLATFORMS = [
  "instagram",
  "pinterest",
  "linkedin",
  "tiktok",
  "youtube",
  "facebook",
  "website",
  "other",
];

const SENTIMENT_COPY: Record<SignalSentiment, { label: string; tone: "user" | "warn" | "soft" }> = {
  LIKED: { label: "Like", tone: "user" },
  DISLIKED: { label: "Avoid", tone: "warn" },
  NEUTRAL: { label: "Noted", tone: "soft" },
};

export function InspirationsPanel({
  brandId,
  onChanged,
}: {
  brandId: string;
  onChanged: () => void;
}) {
  const inspirations = useSlice<Inspiration[]>(() => fetchInspirations(brandId), true);
  const signals = useSlice<InspirationSignalRow[]>(() => fetchSignals(brandId), true);
  const [adding, setAdding] = useState(false);

  const byInspiration = useMemo(() => {
    const map = new Map<string, InspirationSignalRow[]>();
    for (const signal of signals.data ?? []) {
      const list = map.get(signal.inspiration) ?? [];
      list.push(signal);
      map.set(signal.inspiration, list);
    }
    return map;
  }, [signals.data]);

  const refreshAll = () => {
    inspirations.reload();
    signals.reload();
    onChanged();
  };

  if (inspirations.loading && !inspirations.data) return <Loading />;
  if (inspirations.error)
    return <Failed message={inspirations.error} onRetry={inspirations.reload} />;

  const rows = inspirations.data ?? [];
  const active = rows.filter((i) => i.lifecycle_status !== "ARCHIVED");
  const archived = rows.filter((i) => i.lifecycle_status === "ARCHIVED");

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <p className="text-sm text-muted-foreground">
            Show Scaleezy what good looks like — posts, reels, ads, screenshots, competitor work —
            and say what you like about each. What you state here is treated as your preference and
            outranks anything Scaleezy infers.
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Automatic analysis of references is not available yet. Nothing is marked as analysed
            unless it actually was.
          </p>
        </div>
        <Button onClick={() => setAdding((v) => !v)}>
          <Plus className="size-4" /> Add inspiration
        </Button>
      </div>

      {adding ? (
        <AddInspirationCard
          brandId={brandId}
          onCancel={() => setAdding(false)}
          onAdded={() => {
            setAdding(false);
            refreshAll();
          }}
        />
      ) : null}

      {active.length === 0 && !adding ? (
        <Empty
          title="No inspirations yet"
          hint="Add references — a screenshot, a competitor post, a reel — and say what you like about them."
          action={
            <Button variant="outline" onClick={() => setAdding(true)}>
              <Plus className="size-4" /> Add your first reference
            </Button>
          }
        />
      ) : null}

      <div className="space-y-4">
        {active.map((inspiration) => (
          <InspirationCard
            key={inspiration.id}
            inspiration={inspiration}
            signals={byInspiration.get(inspiration.id) ?? []}
            signalsLoading={signals.loading && !signals.data}
            onChanged={refreshAll}
          />
        ))}
      </div>

      {archived.length > 0 ? (
        <div>
          <p className="label-eyebrow mb-2">Archived</p>
          <ul className="space-y-2">
            {archived.map((inspiration) => (
              <li
                key={inspiration.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 opacity-70"
              >
                <span className="min-w-0 truncate text-sm">{inspiration.title}</span>
                <Badge variant="outline">archived</Badge>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------- add card */

function AddInspirationCard({
  brandId,
  onCancel,
  onAdded,
}: {
  brandId: string;
  onCancel: () => void;
  onAdded: () => void;
}) {
  const [mode, setMode] = useState<"link" | "upload">("link");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [type, setType] = useState("POST");
  const [platform, setPlatform] = useState("instagram");
  const [title, setTitle] = useState("");
  const [annotation, setAnnotation] = useState("");
  const [scope, setScope] = useState<"FULL_REFERENCE" | "SPECIFIC_ELEMENTS">("FULL_REFERENCE");
  const [focus, setFocus] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const switchMode = (next: "link" | "upload") => {
    setMode(next);
    setType(next === "link" ? "POST" : "SCREENSHOT");
    setError(null);
  };

  const toggleFocus = (key: string) =>
    setFocus((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));

  const canSubmit =
    !busy &&
    (mode === "link" ? url.trim().length > 0 : file !== null) &&
    (scope === "FULL_REFERENCE" || focus.length > 0);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const input: InspirationInput = {
      title: title.trim() || (mode === "link" ? url.trim() : (file?.name ?? "")),
      inspiration_type: type,
      annotation: annotation.trim(),
      external_platform: platform === "other" ? "" : platform,
      usage_scope: scope,
      focus_areas: scope === "SPECIFIC_ELEMENTS" ? focus : [],
    };
    try {
      if (mode === "link") {
        await createInspiration(brandId, { ...input, reference_url: url.trim() });
      } else if (file) {
        await uploadInspiration(brandId, file, input);
      }
      toast.success("Inspiration saved.");
      onAdded();
    } catch (e) {
      setError(errorMessage(e, "Could not save the inspiration."));
    } finally {
      setBusy(false);
    }
  };

  const types = mode === "link" ? INSPIRATION_LINK_TYPES : INSPIRATION_UPLOAD_TYPES;

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant={mode === "link" ? "default" : "outline"}
            onClick={() => switchMode("link")}
          >
            <Link2 className="size-3.5" /> Link or post
          </Button>
          <Button
            size="sm"
            variant={mode === "upload" ? "default" : "outline"}
            onClick={() => switchMode("upload")}
          >
            <Upload className="size-3.5" /> Upload image
          </Button>
        </div>

        {mode === "link" ? (
          <div>
            <Label className="text-xs tracking-wide uppercase">Link</Label>
            <Input
              className="mt-1.5"
              type="url"
              placeholder="https://www.instagram.com/reel/…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
        ) : (
          <div>
            <Label className="text-xs tracking-wide uppercase">Image</Label>
            <div className="mt-1.5 flex flex-wrap items-center gap-3">
              <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                <ImageIcon className="size-4" /> {file ? "Choose another" : "Choose image"}
              </Button>
              <span className="text-sm text-muted-foreground">
                {file ? file.name : "Screenshot, photo, moodboard…"}
              </span>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <Label className="text-xs tracking-wide uppercase">Type</Label>
            <Select value={type} onValueChange={setType}>
              <SelectTrigger className="mt-1.5 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {types.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs tracking-wide uppercase">Platform</Label>
            <Select value={platform} onValueChange={setPlatform}>
              <SelectTrigger className="mt-1.5 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PLATFORMS.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs tracking-wide uppercase">Title (optional)</Label>
            <Input className="mt-1.5" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
        </div>

        <div>
          <Label className="text-xs tracking-wide uppercase">What do you like about it?</Label>
          <Textarea
            className="mt-1.5"
            rows={2}
            placeholder="e.g. The restraint — one image, four words, lots of air."
            value={annotation}
            onChange={(e) => setAnnotation(e.target.value)}
          />
        </div>

        <div>
          <Label className="text-xs tracking-wide uppercase">Use</Label>
          <div className="mt-1.5 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant={scope === "FULL_REFERENCE" ? "default" : "outline"}
              onClick={() => setScope("FULL_REFERENCE")}
            >
              The whole reference
            </Button>
            <Button
              size="sm"
              variant={scope === "SPECIFIC_ELEMENTS" ? "default" : "outline"}
              onClick={() => setScope("SPECIFIC_ELEMENTS")}
            >
              Only specific elements
            </Button>
          </div>
          {scope === "SPECIFIC_ELEMENTS" ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {SIGNAL_CATEGORIES.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  onClick={() => toggleFocus(c.value)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-xs transition-colors",
                    focus.includes(c.value)
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border text-muted-foreground hover:text-foreground",
                  )}
                >
                  {c.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <InlineError message={error} />

        <div className="flex flex-wrap gap-2">
          <Button disabled={!canSubmit} onClick={submit}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
            {busy ? "Saving…" : "Save inspiration"}
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------- inspiration card */

function InspirationCard({
  inspiration,
  signals,
  signalsLoading,
  onChanged,
}: {
  inspiration: Inspiration;
  signals: InspirationSignalRow[];
  signalsLoading: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);

  const live = signals.filter((s) => !s.superseded_at && s.user_confirmation !== "REJECTED");
  const stated = live.filter((s) => s.origin === "USER");
  const inferred = live.filter((s) => s.origin === "AI");

  const act = async (signal: InspirationSignalRow, action: "confirm" | "reject") => {
    setBusy(signal.id);
    try {
      await (action === "confirm" ? confirmSignal(signal.id) : rejectSignal(signal.id));
      toast.success(action === "confirm" ? "Noted as your preference." : "Withdrawn.");
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e, "Could not update that."));
    } finally {
      setBusy(null);
    }
  };

  const archive = async () => {
    setBusy("archive");
    try {
      await archiveInspiration(inspiration.id);
      toast("Inspiration archived. It no longer influences the Brand Brain.");
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e, "Could not archive."));
    } finally {
      setBusy(null);
      setConfirmArchive(false);
    }
  };

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap items-start gap-4">
          {inspiration.file_url && inspiration.mime_type?.startsWith("video/") ? (
            <video
              src={inspiration.file_url}
              controls
              preload="metadata"
              playsInline
              className="size-24 shrink-0 rounded-lg border bg-black object-contain"
            />
          ) : inspiration.file_url && inspiration.mime_type && !inspiration.mime_type.startsWith("image/") ? (
            <a
              href={inspiration.file_url}
              target="_blank"
              rel="noreferrer"
              className="grid size-24 shrink-0 place-items-center rounded-lg border text-muted-foreground hover:text-foreground"
              title={inspiration.file_url}
            >
              <FileText className="size-5" />
            </a>
          ) : inspiration.file_url ? (
            <a href={inspiration.file_url} target="_blank" rel="noreferrer" className="shrink-0">
              <img
                src={inspiration.file_url}
                alt=""
                className="size-24 rounded-lg border object-cover"
              />
            </a>
          ) : (
            <span className="grid size-24 shrink-0 place-items-center rounded-lg border border-dashed text-muted-foreground">
              <Link2 className="size-5" />
            </span>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-medium">{inspiration.title}</p>
                <p className="text-xs text-muted-foreground">
                  {humanize(inspiration.inspiration_type)}
                  {inspiration.external_platform ? ` · ${inspiration.external_platform}` : ""}
                  {" · added "}
                  {new Date(inspiration.created_at).toLocaleDateString()}
                </p>
                {inspiration.reference_url ? (
                  <a
                    href={inspiration.reference_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-flex items-center gap-1 text-xs text-primary underline-offset-2 hover:underline"
                  >
                    <ExternalLink className="size-3" /> Open reference
                  </a>
                ) : null}
              </div>
              {confirmArchive ? (
                <span className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={busy === "archive"}
                    onClick={archive}
                  >
                    Confirm archive
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmArchive(false)}>
                    Keep
                  </Button>
                </span>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => setConfirmArchive(true)}>
                  <Archive className="size-3.5" /> Archive
                </Button>
              )}
            </div>
            {inspiration.annotation ? (
              <p className="mt-2 text-sm">“{inspiration.annotation}”</p>
            ) : null}
            {inspiration.usage_scope === "SPECIFIC_ELEMENTS" && inspiration.focus_areas.length ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Use only: {inspiration.focus_areas.map(humanize).join(", ")}
              </p>
            ) : null}
          </div>
        </div>

        <div>
          <p className="label-eyebrow mb-2">What you told Scaleezy</p>
          {signalsLoading ? (
            <Loading rows={1} />
          ) : stated.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing specific yet. Name one thing about this reference — the typography, the
              pacing, the hook — and whether it is you or not.
            </p>
          ) : (
            <ul className="space-y-2">
              {stated.map((signal) => (
                <SignalRow
                  key={signal.id}
                  signal={signal}
                  busy={busy === signal.id}
                  onWithdraw={() => act(signal, "reject")}
                />
              ))}
            </ul>
          )}
          <div className="mt-3">
            <AddSignalForm inspirationId={inspiration.id} onAdded={onChanged} />
          </div>
        </div>

        <div>
          <p className="label-eyebrow mb-2">What Scaleezy noticed</p>
          {inferred.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {inspiration.analysis_status === "NOT_ANALYSED"
                ? "Not analysed automatically — that capability is not available yet. What you note above is used directly."
                : `Analysis state: ${humanize(inspiration.analysis_status)}.`}
            </p>
          ) : (
            <ul className="space-y-2">
              {inferred.map((signal) => (
                <li
                  key={signal.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
                >
                  <span className="min-w-0 text-sm">
                    <span className="font-medium">{humanize(signal.category)}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      — {signal.value || signal.attribute}
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    <Chip tone="ai">Scaleezy inferred</Chip>
                    {signal.user_confirmation === "PENDING" ? (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy === signal.id}
                          onClick={() => act(signal, "confirm")}
                        >
                          That's us
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy === signal.id}
                          onClick={() => act(signal, "reject")}
                        >
                          Not us
                        </Button>
                      </>
                    ) : (
                      <Badge variant="secondary">{signal.user_confirmation.toLowerCase()}</Badge>
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
}

function SignalRow({
  signal,
  busy,
  onWithdraw,
}: {
  signal: InspirationSignalRow;
  busy: boolean;
  onWithdraw: () => void;
}) {
  const sentiment = SENTIMENT_COPY[signal.sentiment] ?? SENTIMENT_COPY.NEUTRAL;
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
      <span className="min-w-0 text-sm">
        <span className="font-medium">{humanize(signal.category)}</span>
        {signal.attribute ? (
          <span className="text-muted-foreground"> · {signal.attribute}</span>
        ) : null}
        <span className="text-muted-foreground"> — {signal.value}</span>
      </span>
      <span className="flex items-center gap-2">
        <Chip tone={sentiment.tone}>{sentiment.label}</Chip>
        <Chip tone="user">You said</Chip>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onWithdraw}>
          Withdraw
        </Button>
      </span>
    </li>
  );
}

function AddSignalForm({ inspirationId, onAdded }: { inspirationId: string; onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState("TONE");
  const [attribute, setAttribute] = useState("");
  const [value, setValue] = useState("");
  const [sentiment, setSentiment] = useState<SignalSentiment>("LIKED");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await createSignal({
        inspiration: inspirationId,
        category,
        attribute: attribute.trim() || humanize(category),
        value: value.trim(),
        sentiment,
      });
      toast.success("Noted. This is now part of your brand's preferences.");
      setAttribute("");
      setValue("");
      setOpen(false);
      onAdded();
    } catch (e) {
      setError(errorMessage(e, "Could not save that."));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <Plus className="size-3.5" /> Tell Scaleezy what you like
      </Button>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border border-dashed p-3">
      <div className="grid gap-3 sm:grid-cols-4">
        <div>
          <Label className="text-xs tracking-wide uppercase">About</Label>
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="mt-1.5 w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SIGNAL_CATEGORIES.map((c) => (
                <SelectItem key={c.value} value={c.value}>
                  {c.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs tracking-wide uppercase">Which part (optional)</Label>
          <Input
            className="mt-1.5"
            placeholder="headline length"
            value={attribute}
            onChange={(e) => setAttribute(e.target.value)}
          />
        </div>
        <div>
          <Label className="text-xs tracking-wide uppercase">What it is</Label>
          <Input
            className="mt-1.5"
            placeholder="short, four words"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>
        <div>
          <Label className="text-xs tracking-wide uppercase">Verdict</Label>
          <Select value={sentiment} onValueChange={(v) => setSentiment(v as SignalSentiment)}>
            <SelectTrigger className="mt-1.5 w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="LIKED">Like — more of this</SelectItem>
              <SelectItem value="DISLIKED">Avoid — not us</SelectItem>
              <SelectItem value="NEUTRAL">Just noting it</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      <InlineError message={error} />
      <div className="flex gap-2">
        <Button size="sm" disabled={busy || !value.trim()} onClick={submit}>
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : null} Save
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
