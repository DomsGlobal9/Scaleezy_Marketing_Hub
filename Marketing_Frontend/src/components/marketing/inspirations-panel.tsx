/**
 * Inspirations — the PR2 inspiration system, used from Brand Master.
 *
 * A reference (link, post, reel, screenshot, upload) plus what the user says
 * about it. Stated preferences are recorded as USER-origin signals, which
 * outrank anything inferred and compile into the Brand Brain the moment they
 * are saved. AI analysis produces pending signals that a person must confirm
 * before they influence the brand.
 */
import {
  Archive,
  ExternalLink,
  FileText,
  Link2,
  Loader2,
  Plus,
  Quote,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
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
  SIGNAL_CATEGORIES,
  analyzeInspiration,
  archiveInspiration,
  confirmSignal,
  createInspiration,
  createSignal,
  fetchInspirations,
  fetchSignals,
  humanize,
  isBrandAmbassador,
  isBrandTemplate,
  rejectSignal,
  uploadInspiration,
  type Inspiration,
  type InspirationInput,
  type InspirationSignalRow,
  type SignalSentiment,
} from "@/lib/brand-master";
import { cn } from "@/lib/utils";

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

  useEffect(() => {
    if (
      !(inspirations.data ?? []).some((item) =>
        ["QUEUED", "PROCESSING"].includes(item.analysis_status),
      )
    )
      return;
    const timer = window.setInterval(() => {
      inspirations.reload();
      signals.reload();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [inspirations.data, inspirations.reload, signals.reload]);

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
  if (signals.loading && !signals.data) return <Loading />;
  if (signals.error) return <Failed message={signals.error} onRetry={signals.reload} />;

  // Brand templates and ambassador photos ride the same API but live on
  // their own surfaces; showing them here would list every upload twice.
  const rows = (inspirations.data ?? []).filter(
    (i) => !isBrandTemplate(i) && !isBrandAmbassador(i),
  );
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
            Analysis runs when you request it. Every AI suggestion waits for your confirmation
            before it can influence the Brand Brain.
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

const isHttp = (value: string) => /^https?:\/\//i.test(value.trim());

/** Platform guessed from the pasted URL — nobody should have to say where an Instagram link came from. */
const platformFromUrl = (url: string): string => {
  try {
    const host = new URL(url.trim()).hostname.toLowerCase();
    if (host.includes("instagram")) return "instagram";
    if (host.includes("pinterest") || host.includes("pin.it")) return "pinterest";
    if (host.includes("linkedin")) return "linkedin";
    if (host.includes("tiktok")) return "tiktok";
    if (host.includes("youtube") || host.includes("youtu.be")) return "youtube";
    if (host.includes("facebook") || host.includes("fb.watch")) return "facebook";
    return "website";
  } catch {
    return "website";
  }
};

const typeFromUrl = (url: string): string => {
  const lower = url.toLowerCase();
  if (lower.includes("/reel")) return "REEL";
  if (lower.includes("pinterest") || lower.includes("pin.it")) return "PIN";
  if (lower.includes("youtube") || lower.includes("youtu.be")) return "VIDEO";
  return "POST";
};

/** The title comes from the note — nobody should have to invent one. */
const titleFromNote = (note: string) => {
  const firstLine = note.trim().split(/[\n.!?]/, 1)[0]?.trim() ?? "";
  if (firstLine.length <= 64) return firstLine || "Inspiration";
  const cut = firstLine.slice(0, 64);
  return cut.slice(0, Math.max(cut.lastIndexOf(" "), 40)) + "…";
};

function InspirationThumb({ file, onRemove }: { file: File; onRemove: () => void }) {
  const url = useMemo(() => URL.createObjectURL(file), [file]);
  useEffect(() => () => URL.revokeObjectURL(url), [url]);
  return (
    <div className="relative">
      <img
        src={url}
        alt={file.name}
        className="aspect-square w-full rounded-lg border border-border object-cover"
      />
      <button
        type="button"
        aria-label={`Remove ${file.name}`}
        onClick={onRemove}
        className="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full border border-border bg-background text-muted-foreground shadow-sm hover:text-foreground"
      >
        <X className="size-3" />
      </button>
    </div>
  );
}

/**
 * Same model as the platform library's quick add: drop images (as many as
 * you like) or paste a link, say what you like in plain language, done.
 * Type, platform and title are derived — from the URL and the note — and
 * the focus chips stay behind an optional reveal, defaulting to "use the
 * whole reference". The note is the training signal: it is stored as a
 * USER-origin statement, which outranks anything inferred.
 */
function AddInspirationCard({
  brandId,
  onCancel,
  onAdded,
}: {
  brandId: string;
  onCancel: () => void;
  onAdded: () => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [focus, setFocus] = useState<string[]>([]);
  const [showFocus, setShowFocus] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const fieldId = useId();
  const urlId = `${fieldId}-url`;
  const noteId = `${fieldId}-note`;

  const addFiles = (incoming: FileList | File[]) => {
    const images = Array.from(incoming).filter((f) => f.type.startsWith("image/"));
    if (images.length) setFiles((prev) => [...prev, ...images]);
  };

  const toggleFocus = (key: string) =>
    setFocus((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));

  const canSubmit = !busy && (files.length > 0 || isHttp(url)) && !!note.trim();

  const submit = async () => {
    setBusy("Saving…");
    setError(null);
    const shared: Omit<InspirationInput, "title" | "inspiration_type"> = {
      annotation: note.trim(),
      external_platform: "",
      usage_scope: focus.length ? "SPECIFIC_ELEMENTS" : "FULL_REFERENCE",
      focus_areas: focus,
    };
    const title = titleFromNote(note);
    const total = files.length + (isHttp(url) ? 1 : 0);
    let added = 0;
    try {
      for (const [i, file] of [...files].entries()) {
        setBusy(`Saving ${added + 1} of ${total}…`);
        await uploadInspiration(brandId, file, {
          ...shared,
          title: files.length > 1 ? `${title} (${i + 1})` : title,
          inspiration_type: "SCREENSHOT",
        });
        added += 1;
        // Saved ones leave the tray, so a failure partway keeps only what
        // still needs sending.
        setFiles((prev) => prev.filter((f) => f !== file));
      }
      if (isHttp(url)) {
        setBusy(`Saving ${added + 1} of ${total}…`);
        await createInspiration(brandId, {
          ...shared,
          title,
          inspiration_type: typeFromUrl(url),
          external_platform: platformFromUrl(url),
          reference_url: url.trim(),
        });
        added += 1;
        setUrl("");
      }
      toast.success(`${added} inspiration${added === 1 ? "" : "s"} saved.`);
      onAdded();
    } catch (e) {
      setError(
        `${errorMessage(e, "Could not save the inspiration.")}${added ? ` ${added} of ${total} saved; the rest are still here — try again.` : ""}`,
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div
          role="button"
          tabIndex={0}
          aria-label="Add images"
          onClick={() => fileRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" ? fileRef.current?.click() : null)}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            addFiles(e.dataTransfer.files);
          }}
          className="cursor-pointer rounded-xl border-2 border-dashed border-border bg-secondary/30 px-4 py-6 text-center transition-colors hover:border-primary/50"
        >
          <Upload className="mx-auto size-5 text-muted-foreground" />
          <p className="mt-2 text-sm font-medium text-foreground">
            Drop images here, or click to choose
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Screenshots, photos, moodboards — as many as you like
          </p>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept="image/*"
            className="hidden"
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
        {files.length ? (
          <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
            {files.map((file, i) => (
              <InspirationThumb
                key={`${file.name}-${file.size}-${i}`}
                file={file}
                onRemove={() => setFiles((prev) => prev.filter((f) => f !== file))}
              />
            ))}
          </div>
        ) : null}

        <div>
          <Label htmlFor={urlId} className="text-xs tracking-wide uppercase">
            …or paste a link
          </Label>
          <Input
            id={urlId}
            className="mt-1.5"
            type="url"
            placeholder="https://www.instagram.com/reel/…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>

        <div>
          <Label htmlFor={noteId} className="text-xs tracking-wide uppercase">
            What do you like about it?
          </Label>
          <Textarea
            id={noteId}
            className="mt-1.5"
            rows={2}
            placeholder="e.g. The restraint — one image, four words, lots of air."
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>

        <div>
          <button
            type="button"
            onClick={() => {
              setShowFocus((v) => !v);
              if (showFocus) setFocus([]);
            }}
            aria-expanded={showFocus}
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            {showFocus
              ? "Never mind — use the whole reference"
              : "Only like part of it? Point at the elements (optional)"}
          </button>
          {showFocus ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {SIGNAL_CATEGORIES.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  onClick={() => toggleFocus(c.value)}
                  aria-pressed={focus.includes(c.value)}
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
          <Button disabled={!canSubmit} onClick={() => void submit()}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
            {busy ?? "Save inspiration"}
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={!!busy}>
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

  const analyze = async () => {
    setBusy("analyze");
    try {
      await analyzeInspiration(inspiration.id);
      toast.success("Analysis queued. Review the suggestions when they appear.");
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e, "Could not analyze this inspiration."));
    } finally {
      setBusy(null);
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
          ) : inspiration.file_url &&
            inspiration.mime_type &&
            !inspiration.mime_type.startsWith("image/") ? (
            <a
              href={inspiration.file_url}
              target="_blank"
              rel="noreferrer"
              className="grid size-24 shrink-0 place-items-center rounded-lg border text-muted-foreground hover:text-foreground"
              title={inspiration.file_name ?? inspiration.file_url}
            >
              <FileText className="size-5" />
            </a>
          ) : inspiration.file_url ? (
            <a href={inspiration.file_url} target="_blank" rel="noreferrer" className="shrink-0">
              <img
                src={inspiration.file_url}
                alt=""
                loading="lazy"
                decoding="async"
                className="size-24 rounded-lg border object-cover"
              />
            </a>
          ) : (
            <span className="grid size-24 shrink-0 place-items-center rounded-lg border border-dashed text-muted-foreground">
              {inspiration.inspiration_type === "TEXT" ? (
                <Quote className="size-5" />
              ) : (
                <Link2 className="size-5" />
              )}
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
                <span className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={
                      busy === "analyze" ||
                      ["QUEUED", "PROCESSING"].includes(inspiration.analysis_status)
                    }
                    onClick={analyze}
                  >
                    {busy === "analyze" ||
                    ["QUEUED", "PROCESSING"].includes(inspiration.analysis_status) ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : null}
                    {inspiration.analysis_status === "FAILED"
                      ? "Retry analysis"
                      : "Analyze with AI"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmArchive(true)}>
                    <Archive className="size-3.5" /> Archive
                  </Button>
                </span>
              )}
            </div>
            {inspiration.annotation ? (
              <p className="mt-2 text-sm whitespace-pre-wrap">“{inspiration.annotation}”</p>
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
                ? "Not analysed yet. Choose Analyze with AI, then approve only the suggestions that fit."
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
  const fieldId = useId();
  const categoryId = `${fieldId}-category`;
  const attributeId = `${fieldId}-attribute`;
  const valueId = `${fieldId}-value`;
  const sentimentId = `${fieldId}-sentiment`;

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
          <Label htmlFor={categoryId} className="text-xs tracking-wide uppercase">
            About
          </Label>
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger id={categoryId} className="mt-1.5 w-full">
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
          <Label htmlFor={attributeId} className="text-xs tracking-wide uppercase">
            Which part (optional)
          </Label>
          <Input
            id={attributeId}
            className="mt-1.5"
            placeholder="headline length"
            value={attribute}
            onChange={(e) => setAttribute(e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor={valueId} className="text-xs tracking-wide uppercase">
            What it is
          </Label>
          <Input
            id={valueId}
            className="mt-1.5"
            placeholder="short, four words"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor={sentimentId} className="text-xs tracking-wide uppercase">
            Verdict
          </Label>
          <Select value={sentiment} onValueChange={(v) => setSentiment(v as SignalSentiment)}>
            <SelectTrigger id={sentimentId} className="mt-1.5 w-full">
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
