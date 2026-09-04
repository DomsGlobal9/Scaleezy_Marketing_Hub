/**
 * Knowledge — the PR1 knowledge system, used from Brand Master.
 *
 * Sources are stored with full provenance (file, pasted text or link) and
 * facts are captured against them and confirmed. Confirmed facts compile
 * into the Brand Brain on the server the moment they are confirmed, so the
 * readiness counts and the next generation reflect them without a manual
 * rebuild.
 *
 * Processing runs on the durable worker and returns reviewable candidates;
 * nothing becomes Brand Brain truth until a person confirms it.
 */
import { Archive, FileText, Link2, Loader2, Plus, Upload } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

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
import { SectionTitle } from "@/components/marketing/primitives";
import {
  MEMORY_TYPES,
  SOURCE_TYPES,
  confirmMemory,
  createMemory,
  createTextSource,
  fetchKnowledge,
  fetchMemories,
  humanize,
  processSource,
  rejectMemory,
  revokeSource,
  uploadSource,
  type BrandMemoryRow,
  type KnowledgeSource,
} from "@/lib/brand-master";

type AddMode = "text" | "file" | "url";

const SOURCE_STATUS_COPY: Record<
  string,
  { label: string; tone: "soft" | "warn" | "user" | "hard" }
> = {
  UPLOADED: { label: "Stored · not read automatically", tone: "soft" },
  QUEUED: { label: "Queued", tone: "warn" },
  PROCESSING: { label: "Processing", tone: "warn" },
  READY: { label: "Read", tone: "user" },
  NEEDS_REVIEW: { label: "Needs review", tone: "warn" },
  FAILED: { label: "Reading failed", tone: "warn" },
  ARCHIVED: { label: "Archived", tone: "hard" },
};

const MEMORY_STATUS_COPY: Record<
  string,
  { label: string; tone: "soft" | "warn" | "user" | "hard" }
> = {
  CANDIDATE: { label: "Awaiting confirmation", tone: "warn" },
  CONFIRMED: { label: "Confirmed", tone: "user" },
  REJECTED: { label: "Rejected", tone: "hard" },
  SUPERSEDED: { label: "Superseded", tone: "soft" },
  EXPIRED: { label: "Expired", tone: "soft" },
};

export function KnowledgePanel({ brandId, onChanged }: { brandId: string; onChanged: () => void }) {
  const sources = useSlice<KnowledgeSource[]>(() => fetchKnowledge(brandId), true);
  const memories = useSlice<BrandMemoryRow[]>(() => fetchMemories(brandId), true);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    if (!(sources.data ?? []).some((source) => ["QUEUED", "PROCESSING"].includes(source.status)))
      return;
    const timer = window.setInterval(() => {
      sources.reload();
      memories.reload();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [sources.data, sources.reload, memories.reload]);

  const bySource = useMemo(() => {
    const map = new Map<string, BrandMemoryRow[]>();
    for (const memory of memories.data ?? []) {
      const key = memory.source ?? "__direct__";
      const list = map.get(key) ?? [];
      list.push(memory);
      map.set(key, list);
    }
    return map;
  }, [memories.data]);

  const refreshAll = () => {
    sources.reload();
    memories.reload();
    onChanged();
  };

  if (sources.loading && !sources.data) return <Loading />;
  if (sources.error) return <Failed message={sources.error} onRetry={sources.reload} />;
  if (memories.loading && !memories.data) return <Loading />;
  if (memories.error) return <Failed message={memories.error} onRetry={memories.reload} />;

  const active = (sources.data ?? []).filter((s) => s.status !== "ARCHIVED");
  const archived = (sources.data ?? []).filter((s) => s.status === "ARCHIVED");
  const direct = bySource.get("__direct__") ?? [];

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <p className="text-sm text-muted-foreground">
            Transcripts, minutes of meeting, client calls, founder notes, decks, product documents
            and web pages — anything true about the business. Sources are kept with their
            provenance; the facts you confirm from them become part of the Brand Brain immediately.
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Ask Scaleezy to read a source, then confirm or reject every suggested fact. Unconfirmed
            suggestions never enter the Brand Brain.
          </p>
        </div>
        <Button onClick={() => setAdding((v) => !v)}>
          <Plus className="size-4" /> Add source
        </Button>
      </div>

      {adding ? (
        <AddSourceCard
          brandId={brandId}
          onCancel={() => setAdding(false)}
          onAdded={() => {
            setAdding(false);
            refreshAll();
          }}
        />
      ) : null}

      {active.length === 0 && direct.length === 0 && !adding ? (
        <Empty
          title="No knowledge yet"
          hint="Upload a brand deck, paste a meeting transcript or add a product page and Scaleezy keeps it as permanent brand intelligence."
          action={
            <Button variant="outline" onClick={() => setAdding(true)}>
              <Plus className="size-4" /> Add your first source
            </Button>
          }
        />
      ) : null}

      {active.map((source) => (
        <SourceCard
          key={source.id}
          brandId={brandId}
          source={source}
          memories={bySource.get(source.id) ?? []}
          memoriesLoading={memories.loading}
          onChanged={refreshAll}
        />
      ))}

      <div>
        <SectionTitle
          title="Facts added directly"
          description="Things you know are true that do not come from a single document."
        />
        <div className="mt-3 space-y-3">
          <MemoryList
            memories={direct}
            loading={memories.loading && !memories.data}
            onChanged={refreshAll}
          />
          <AddFactForm brandId={brandId} sourceId={null} onAdded={refreshAll} />
        </div>
      </div>

      {archived.length > 0 ? (
        <div>
          <SectionTitle
            title="Archived sources"
            description="No longer used by the Brand Brain. Kept for provenance."
          />
          <ul className="mt-3 space-y-2">
            {archived.map((source) => (
              <li
                key={source.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 opacity-70"
              >
                <span className="min-w-0 truncate text-sm">{source.title}</span>
                <Chip tone="hard">Archived</Chip>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------- add source */

function AddSourceCard({
  brandId,
  onCancel,
  onAdded,
}: {
  brandId: string;
  onCancel: () => void;
  onAdded: () => void;
}) {
  const [mode, setMode] = useState<AddMode>("text");
  const [sourceType, setSourceType] = useState("TRANSCRIPT");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const fieldId = useId();
  const sourceTypeId = `${fieldId}-source-type`;
  const titleId = `${fieldId}-title`;
  const textId = `${fieldId}-text`;
  const urlId = `${fieldId}-url`;
  const fileId = `${fieldId}-file`;

  const types = SOURCE_TYPES.filter((t) => (mode === "file" ? t.kind !== "url" : t.kind === mode));

  const switchMode = (next: AddMode) => {
    setMode(next);
    setError(null);
    const first = SOURCE_TYPES.find((t) => (next === "file" ? t.kind === "file" : t.kind === next));
    if (first) setSourceType(first.value);
  };

  const canSubmit =
    !busy &&
    (mode === "text"
      ? text.trim().length > 0 && title.trim().length > 0
      : mode === "url"
        ? url.trim().length > 0
        : file !== null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (mode === "text") {
        await createTextSource(brandId, {
          source_type: sourceType,
          title: title.trim(),
          raw_text: text,
        });
      } else if (mode === "url") {
        await createTextSource(brandId, {
          source_type: sourceType,
          title: title.trim() || url.trim(),
          source_url: url.trim(),
        });
      } else if (file) {
        await uploadSource(brandId, file, { source_type: sourceType, title: title.trim() });
      }
      toast.success("Source saved.");
      onAdded();
    } catch (e) {
      setError(errorMessage(e, "Could not save the source."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap gap-2">
          {(
            [
              ["text", "Paste text", FileText],
              ["file", "Upload a file", Upload],
              ["url", "Add a link", Link2],
            ] as const
          ).map(([key, label, Icon]) => (
            <Button
              key={key}
              size="sm"
              variant={mode === key ? "default" : "outline"}
              onClick={() => switchMode(key)}
            >
              <Icon className="size-3.5" /> {label}
            </Button>
          ))}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor={sourceTypeId} className="text-xs tracking-wide uppercase">
              What is it?
            </Label>
            <Select value={sourceType} onValueChange={setSourceType}>
              <SelectTrigger id={sourceTypeId} className="mt-1.5 w-full">
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
            <Label htmlFor={titleId} className="text-xs tracking-wide uppercase">
              Title{mode === "text" ? "" : " (optional)"}
            </Label>
            <Input
              id={titleId}
              className="mt-1.5"
              placeholder={
                mode === "text" ? "Founder call, 12 Aug" : "Defaults to the file or link"
              }
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
        </div>

        {mode === "text" ? (
          <div>
            <Label htmlFor={textId} className="text-xs tracking-wide uppercase">
              Text
            </Label>
            <Textarea
              id={textId}
              className="mt-1.5"
              rows={8}
              placeholder="Paste the transcript, minutes or notes here…"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
        ) : null}

        {mode === "url" ? (
          <div>
            <Label htmlFor={urlId} className="text-xs tracking-wide uppercase">
              Link
            </Label>
            <Input
              id={urlId}
              className="mt-1.5"
              type="url"
              placeholder="https://…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <p className="mt-1.5 text-xs text-muted-foreground">
              Scaleezy fetches this public page only when you choose Read with AI, then shows facts
              for your review.
            </p>
          </div>
        ) : null}

        {mode === "file" ? (
          <div>
            <Label htmlFor={fileId} className="text-xs tracking-wide uppercase">
              File
            </Label>
            <div className="mt-1.5 flex flex-wrap items-center gap-3">
              <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                <Upload className="size-4" /> {file ? "Choose another" : "Choose file"}
              </Button>
              <span className="text-sm text-muted-foreground">
                {file
                  ? `${file.name} · ${Math.ceil(file.size / 1024)} KB`
                  : "PDF, document, deck, export…"}
              </span>
              <input
                id={fileId}
                ref={fileRef}
                type="file"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
          </div>
        ) : null}

        <InlineError message={error} />

        <div className="flex flex-wrap gap-2">
          <Button disabled={!canSubmit} onClick={submit}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
            {busy ? "Saving…" : "Save source"}
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------ source card */

function SourceCard({
  brandId,
  source,
  memories,
  memoriesLoading,
  onChanged,
}: {
  brandId: string;
  source: KnowledgeSource;
  memories: BrandMemoryRow[];
  memoriesLoading: boolean;
  onChanged: () => void;
}) {
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [busy, setBusy] = useState(false);
  const status = SOURCE_STATUS_COPY[source.status] ?? {
    label: humanize(source.status),
    tone: "soft" as const,
  };
  const typeLabel =
    SOURCE_TYPES.find((t) => t.value === source.source_type)?.label ?? humanize(source.source_type);

  const archive = async () => {
    setBusy(true);
    try {
      await revokeSource(source.id);
      toast("Source archived. It no longer influences the Brand Brain.");
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e, "Could not archive the source."));
    } finally {
      setBusy(false);
      setConfirmArchive(false);
    }
  };

  const process = async () => {
    setBusy(true);
    try {
      await processSource(source.id);
      toast.success("Source queued. Suggested facts will appear here for review.");
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e, "Could not process the source."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-medium">{source.title}</p>
            <p className="text-xs text-muted-foreground">
              {typeLabel}
              {source.file_name ? ` · ${source.file_name}` : ""}
              {" · added "}
              {new Date(source.created_at).toLocaleDateString()}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Chip tone={status.tone}>{status.label}</Chip>
              {source.file_url ? (
                <a
                  href={source.file_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-primary underline-offset-2 hover:underline"
                >
                  Open file
                </a>
              ) : null}
              {source.source_url ? (
                <a
                  href={source.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-primary underline-offset-2 hover:underline"
                >
                  Open link
                </a>
              ) : null}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {!confirmArchive ? (
              <Button
                size="sm"
                variant="outline"
                disabled={busy || ["QUEUED", "PROCESSING"].includes(source.status)}
                onClick={process}
              >
                {busy || ["QUEUED", "PROCESSING"].includes(source.status) ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : null}
                {source.status === "FAILED" ? "Retry AI reading" : "Read with AI"}
              </Button>
            ) : null}
            {confirmArchive ? (
              <>
                <Button size="sm" variant="destructive" disabled={busy} onClick={archive}>
                  {busy ? <Loader2 className="size-3.5 animate-spin" /> : null} Confirm archive
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmArchive(false)}>
                  Keep
                </Button>
              </>
            ) : (
              <Button size="sm" variant="ghost" onClick={() => setConfirmArchive(true)}>
                <Archive className="size-3.5" /> Archive
              </Button>
            )}
          </div>
        </div>

        {source.raw_text ? (
          <details className="rounded-lg border bg-muted/30 p-3 text-sm">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
              Show text
            </summary>
            <p className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-muted-foreground">
              {source.raw_text}
            </p>
          </details>
        ) : null}

        <div>
          <p className="label-eyebrow mb-2">Facts from this source</p>
          <MemoryList memories={memories} loading={memoriesLoading} onChanged={onChanged} />
          <div className="mt-3">
            <AddFactForm brandId={brandId} sourceId={source.id} onAdded={onChanged} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------- facts list */

function MemoryList({
  memories,
  loading,
  onChanged,
}: {
  memories: BrandMemoryRow[];
  loading: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  const act = async (memory: BrandMemoryRow, action: "confirm" | "reject") => {
    setBusy(memory.id);
    try {
      await (action === "confirm" ? confirmMemory(memory.id) : rejectMemory(memory.id));
      toast.success(
        action === "confirm" ? "Fact confirmed — it is now in the Brand Brain." : "Fact rejected.",
      );
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e, "Could not update the fact."));
    } finally {
      setBusy(null);
    }
  };

  if (loading) return <Loading rows={1} />;
  if (memories.length === 0) {
    return <p className="text-sm text-muted-foreground">No facts captured yet.</p>;
  }

  return (
    <ul className="space-y-2">
      {memories.map((memory) => {
        const status = MEMORY_STATUS_COPY[memory.status] ?? {
          label: humanize(memory.status),
          tone: "soft" as const,
        };
        return (
          <li
            key={memory.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
          >
            <span className="min-w-0 flex-1">
              <span className="block text-sm">{memory.content}</span>
              <span className="mt-1 block text-xs text-muted-foreground">
                {MEMORY_TYPES.find((t) => t.value === memory.memory_type)?.label ??
                  humanize(memory.memory_type)}
              </span>
            </span>
            <span className="flex items-center gap-2">
              <Chip tone={status.tone}>{status.label}</Chip>
              {memory.status === "CANDIDATE" ? (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy === memory.id}
                    onClick={() => act(memory, "confirm")}
                  >
                    Confirm
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === memory.id}
                    onClick={() => act(memory, "reject")}
                  >
                    Reject
                  </Button>
                </>
              ) : memory.status === "CONFIRMED" ? (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy === memory.id}
                  onClick={() => act(memory, "reject")}
                >
                  Withdraw
                </Button>
              ) : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/* --------------------------------------------------------------- add fact */

function AddFactForm({
  brandId,
  sourceId,
  onAdded,
}: {
  brandId: string;
  sourceId: string | null;
  onAdded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [type, setType] = useState("FACT");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fieldId = useId();
  const typeId = `${fieldId}-type`;
  const contentId = `${fieldId}-content`;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const memory = await createMemory(brandId, {
        source: sourceId,
        memory_type: type,
        content: content.trim(),
      });
      try {
        await confirmMemory(memory.id);
        toast.success("Fact confirmed — it is now in the Brand Brain.");
      } catch (e) {
        // The fact exists as a candidate; say so rather than claiming more.
        toast.error(errorMessage(e, "Fact saved, but it could not be confirmed yet."));
      }
      setContent("");
      setOpen(false);
      onAdded();
    } catch (e) {
      setError(errorMessage(e, "Could not save the fact."));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <Plus className="size-3.5" /> Add a fact
      </Button>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border border-dashed p-3">
      <div className="grid gap-3 sm:grid-cols-[14rem_minmax(0,1fr)]">
        <div>
          <Label htmlFor={typeId} className="text-xs tracking-wide uppercase">
            Kind
          </Label>
          <Select value={type} onValueChange={setType}>
            <SelectTrigger id={typeId} className="mt-1.5 w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MEMORY_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label htmlFor={contentId} className="text-xs tracking-wide uppercase">
            The fact, in one sentence
          </Label>
          <Textarea
            id={contentId}
            className="mt-1.5"
            rows={2}
            placeholder="e.g. Every bag is roasted within 48 hours of shipping."
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
        </div>
      </div>
      <InlineError message={error} />
      <div className="flex gap-2">
        <Button size="sm" disabled={busy || !content.trim()} onClick={submit}>
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : null} Add as confirmed fact
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
