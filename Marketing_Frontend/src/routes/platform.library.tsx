/**
 * Scaleezy library — references the team curates and shares across clients.
 *
 * An entry is a link, an uploaded image / video / file, or a piece of text,
 * plus the team's annotation. Draft → Published → Retired; only published
 * items reach a client's gallery, and only if that client has not opted out
 * of the universal layer.
 */
import { createFileRoute } from "@tanstack/react-router";
import { Archive, Pencil, Plus, RefreshCw, Send, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  KIND_LABEL,
  KindBadge,
  LibraryEntryPreview,
  asKind,
} from "@/components/marketing/library-entry-preview";
import {
  ConfirmDialog,
  ErrorNote,
  PlatformPageHeader,
  StatusPill,
  type ConfirmRequest,
} from "@/components/platform/shared";
import {
  LIBRARY_KINDS,
  LIBRARY_UPLOAD_ACCEPT,
  LIBRARY_UPLOAD_MAX_MB,
  createPlatformInspiration,
  errorText,
  fetchPlatformInspirations,
  formatDate,
  publishPlatformInspiration,
  retirePlatformInspiration,
  updatePlatformInspiration,
  uploadPlatformInspiration,
  type LibraryKind,
  type PlatformInspiration,
  type PlatformInspirationInput,
} from "@/lib/platform";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/platform/library")({
  head: () => ({ meta: [{ title: "Library — Scaleezy Platform Console" }] }),
  component: LibraryPage,
});

/** What the editor is authoring. UPLOAD covers image, video and file — the server picks which. */
type Mode = "LINK" | "UPLOAD" | "TEXT";

const MODE_LABEL: Record<Mode, string> = {
  LINK: "Link",
  UPLOAD: "Image / video / file",
  TEXT: "Text",
};

const modeFor = (kind: string): Mode => {
  const k = asKind(kind);
  return k === "LINK" || k === "TEXT" ? k : "UPLOAD";
};

const EMPTY_FORM: PlatformInspirationInput = {
  title: "",
  reference_url: "",
  body: "",
  annotation: "",
  tags: [],
  industry: "",
  channel: "",
};

type StatusFilter = "ALL" | "DRAFT" | "PUBLISHED" | "RETIRED";
type KindFilter = "ALL" | LibraryKind;

const isHttp = (value: string) => /^https?:\/\//i.test(value.trim());

function EditorSheet({
  item,
  open,
  onClose,
  onSaved,
}: {
  item: PlatformInspiration | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [mode, setMode] = useState<Mode>("LINK");
  const [form, setForm] = useState<PlatformInspirationInput>(EMPTY_FORM);
  const [tagsText, setTagsText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  useEffect(() => {
    if (!open) return;
    setMode(item ? modeFor(item.kind) : "LINK");
    setForm(
      item
        ? {
            title: item.title,
            reference_url: item.reference_url,
            body: item.body ?? "",
            annotation: item.annotation,
            tags: item.tags ?? [],
            industry: item.industry,
            channel: item.channel,
          }
        : EMPTY_FORM,
    );
    setTagsText((item?.tags ?? []).join(", "));
    setFile(null);
  }, [item, open]);

  // A local preview for a picked image, released when the pick changes.
  const filePreview = useMemo(
    () => (file && file.type.startsWith("image/") ? URL.createObjectURL(file) : null),
    [file],
  );
  useEffect(() => () => (filePreview ? URL.revokeObjectURL(filePreview) : undefined), [filePreview]);

  const set = <K extends keyof PlatformInspirationInput>(key: K, value: PlatformInspirationInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const fileTooBig = !!file && file.size > LIBRARY_UPLOAD_MAX_MB * 1024 * 1024;
  const contentOk =
    mode === "LINK"
      ? isHttp(form.reference_url)
      : mode === "TEXT"
        ? !!form.body?.trim()
        : item
          ? true
          : !!file && !fileTooBig;
  // On a non-link entry the URL is an optional credit — blank or http(s).
  const sourceOk = mode === "LINK" || !form.reference_url.trim() || isHttp(form.reference_url);
  const valid = !!form.title.trim() && contentOk && sourceOk;

  const save = () => {
    const tags = tagsText
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    const common = {
      title: form.title.trim(),
      reference_url: form.reference_url.trim(),
      annotation: form.annotation.trim(),
      industry: form.industry.trim(),
      channel: form.channel.trim(),
      tags,
    };
    const kindWord = item ? KIND_LABEL[asKind(item.kind)].toLowerCase() : MODE_LABEL[mode].toLowerCase();
    setConfirm({
      title: item ? `Save changes to "${common.title}"?` : `Add "${common.title}" to the library?`,
      description: item
        ? "Clients who already adopted it keep their copy; the library entry is what changes."
        : `It starts as a draft ${kindWord} entry. Nobody sees it until you publish it.`,
      confirmLabel: item ? "Save" : "Create draft",
      run: async () => {
        if (item) {
          const patch: Partial<PlatformInspirationInput> = { ...common };
          if (mode === "TEXT") patch.body = (form.body ?? "").trim();
          await updatePlatformInspiration(item.id, patch);
        } else if (mode === "UPLOAD") {
          if (!file) return;
          await uploadPlatformInspiration(file, common);
        } else if (mode === "TEXT") {
          await createPlatformInspiration({ ...common, kind: "TEXT", body: (form.body ?? "").trim() });
        } else {
          await createPlatformInspiration({ ...common, kind: "LINK" });
        }
        toast.success(item ? "Library entry updated." : "Draft created.");
        onSaved();
        onClose();
      },
    });
  };

  return (
    <>
      <Sheet open={open} onOpenChange={(next) => (!next ? onClose() : null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>{item ? "Edit library entry" : "New library entry"}</SheetTitle>
            <SheetDescription>
              A link, an image, a video, a file or a piece of text — and why the team kept it. The
              annotation is the part a client is really given.
            </SheetDescription>
          </SheetHeader>
          <div className="mt-6 space-y-4">
            <Field label="Kind" id="lib-kind" hint={item ? "Fixed once created. Retire and add a new entry to change it." : undefined}>
              {item ? (
                <KindBadge kind={item.kind} className="text-xs" />
              ) : (
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Kind">
                  {(Object.keys(MODE_LABEL) as Mode[]).map((value) => (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={mode === value}
                      onClick={() => setMode(value)}
                      className={cn(
                        "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                        mode === value
                          ? "border-slate-900 bg-slate-900 text-white"
                          : "border-border bg-background text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {MODE_LABEL[value]}
                    </button>
                  ))}
                </div>
              )}
            </Field>

            <Field label="Title" id="lib-title">
              <Input id="lib-title" value={form.title} onChange={(e) => set("title", e.target.value)} />
            </Field>

            {mode === "LINK" ? (
              <Field label="Reference URL" id="lib-url" hint="Must start with http:// or https://">
                <Input
                  id="lib-url"
                  value={form.reference_url}
                  onChange={(e) => set("reference_url", e.target.value)}
                  placeholder="https://"
                />
              </Field>
            ) : null}

            {mode === "TEXT" ? (
              <Field
                label="Text"
                id="lib-body"
                hint="The words themselves — a hook, a headline, a caption, a brief."
              >
                <Textarea
                  id="lib-body"
                  rows={6}
                  value={form.body ?? ""}
                  onChange={(e) => set("body", e.target.value)}
                />
              </Field>
            ) : null}

            {mode === "UPLOAD" ? (
              item ? (
                <Field label="File" id="lib-file-current">
                  <LibraryEntryPreview entry={item} className="mt-0" />
                </Field>
              ) : (
                <Field
                  label="File"
                  id="lib-file"
                  hint={`Image (PNG, JPG, GIF, WebP, AVIF), video (MP4, WebM, MOV), PDF, text, Word or PowerPoint — up to ${LIBRARY_UPLOAD_MAX_MB} MB.`}
                >
                  <Input
                    id="lib-file"
                    type="file"
                    accept={LIBRARY_UPLOAD_ACCEPT}
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  />
                  {filePreview ? (
                    <img
                      src={filePreview}
                      alt=""
                      className="mt-2 h-40 w-full rounded-lg border border-border object-cover"
                    />
                  ) : file ? (
                    <p className="mt-2 truncate text-xs text-muted-foreground">
                      <Upload className="mr-1 inline size-3" /> {file.name}
                    </p>
                  ) : null}
                  {fileTooBig ? (
                    <p className="mt-1 text-xs text-destructive">
                      That file is larger than {LIBRARY_UPLOAD_MAX_MB} MB.
                    </p>
                  ) : null}
                </Field>
              )
            ) : null}

            {mode !== "LINK" ? (
              <Field label="Source URL" id="lib-source" hint="Optional — where it came from, as a credit.">
                <Input
                  id="lib-source"
                  value={form.reference_url}
                  onChange={(e) => set("reference_url", e.target.value)}
                  placeholder="https://"
                />
              </Field>
            ) : null}

            <Field label="Annotation" id="lib-annotation" hint="What is good about it, in the team's words.">
              <Textarea
                id="lib-annotation"
                rows={4}
                value={form.annotation}
                onChange={(e) => set("annotation", e.target.value)}
              />
            </Field>
            <Field label="Tags" id="lib-tags" hint="Comma separated, e.g. minimal, product-led">
              <Input id="lib-tags" value={tagsText} onChange={(e) => setTagsText(e.target.value)} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Industry" id="lib-industry" hint="Blank = every industry">
                <Input
                  id="lib-industry"
                  value={form.industry}
                  onChange={(e) => set("industry", e.target.value)}
                />
              </Field>
              <Field label="Channel" id="lib-channel" hint="Blank = every channel">
                <Input id="lib-channel" value={form.channel} onChange={(e) => set("channel", e.target.value)} />
              </Field>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={save} disabled={!valid}>
                {item ? "Save…" : "Create draft…"}
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </>
  );
}

function Field({
  label,
  id,
  hint,
  children,
}: {
  label: string;
  id: string;
  hint?: string | undefined;
  children: React.ReactNode;
}) {
  return (
    <div>
      <Label htmlFor={id} className="text-xs tracking-wide uppercase">
        {label}
      </Label>
      <div className="mt-1.5">{children}</div>
      {hint ? <p className="mt-1 text-[0.6875rem] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        active
          ? "border-slate-900 bg-slate-900 text-white"
          : "border-border bg-background text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function LibraryPage() {
  const [items, setItems] = useState<PlatformInspiration[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("ALL");
  const [kindFilter, setKindFilter] = useState<KindFilter>("ALL");
  const [editing, setEditing] = useState<PlatformInspiration | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await fetchPlatformInspirations());
    } catch (e: unknown) {
      setError(errorText(e, "Could not load the library."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const publish = (item: PlatformInspiration) =>
    setConfirm({
      title: `Publish "${item.title}"?`,
      description:
        "It appears in every client's Scaleezy library (unless that client opted out) and can be adopted into their own inspirations.",
      confirmLabel: "Publish",
      run: async () => {
        await publishPlatformInspiration(item.id);
        toast.success("Published.");
        await load();
      },
    });

  const retire = (item: PlatformInspiration) =>
    setConfirm({
      title: `Retire "${item.title}"?`,
      description: "It leaves the library. Copies clients already adopted are theirs and stay.",
      confirmLabel: "Retire",
      destructive: true,
      reason: { label: "Reason", placeholder: "Optional — why it is being retired" },
      run: async (reason) => {
        await retirePlatformInspiration(item.id, reason);
        toast.success("Retired.");
        await load();
      },
    });

  const byStatus = (items ?? []).filter((i) => filter === "ALL" || i.status === filter);
  const visible = byStatus.filter((i) => kindFilter === "ALL" || asKind(i.kind) === kindFilter);
  const counts = {
    ALL: items?.length ?? 0,
    DRAFT: items?.filter((i) => i.status === "DRAFT").length ?? 0,
    PUBLISHED: items?.filter((i) => i.status === "PUBLISHED").length ?? 0,
    RETIRED: items?.filter((i) => i.status === "RETIRED").length ?? 0,
  };
  const kindCounts = Object.fromEntries(
    LIBRARY_KINDS.map((k) => [k, byStatus.filter((i) => asKind(i.kind) === k).length]),
  ) as Record<LibraryKind, number>;

  return (
    <div>
      <PlatformPageHeader
        eyebrow="Platform"
        title="Library"
        subtitle="Curated references every client can adopt — links, images, videos, files and text, each with the team's annotation. Nothing here ever comes from a client's own material."
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={cn("size-4", loading && "animate-spin")} /> Refresh
            </Button>
            <Button
              size="sm"
              onClick={() => {
                setEditing(null);
                setEditorOpen(true);
              }}
            >
              <Plus className="size-4" /> New entry
            </Button>
          </>
        }
      />

      <div className="mb-2 flex flex-wrap gap-2">
        {(["ALL", "DRAFT", "PUBLISHED", "RETIRED"] as StatusFilter[]).map((value) => (
          <FilterChip key={value} active={filter === value} onClick={() => setFilter(value)}>
            {value === "ALL" ? "All" : value.charAt(0) + value.slice(1).toLowerCase()} · {counts[value]}
          </FilterChip>
        ))}
      </div>
      <div className="mb-4 flex flex-wrap gap-2">
        <FilterChip active={kindFilter === "ALL"} onClick={() => setKindFilter("ALL")}>
          Every kind · {byStatus.length}
        </FilterChip>
        {LIBRARY_KINDS.map((k) => (
          <FilterChip key={k} active={kindFilter === k} onClick={() => setKindFilter(k)}>
            {KIND_LABEL[k]}s · {kindCounts[k]}
          </FilterChip>
        ))}
      </div>

      <ErrorNote message={error} />

      {loading && !items ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="surface-card p-10 text-center">
          <p className="font-medium text-foreground">Nothing here yet.</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {filter === "ALL" && kindFilter === "ALL"
              ? "Add the first reference the team wants every client to see — a link, an image, a video, a file or a piece of text."
              : "No entries match these filters."}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((item) => (
            <article key={item.id} className="surface-card flex flex-col p-4">
              <div className="flex items-start justify-between gap-2">
                <h3 className="min-w-0 font-medium text-foreground">{item.title}</h3>
                <div className="flex shrink-0 items-center gap-1">
                  <KindBadge kind={item.kind} />
                  <StatusPill value={item.status} />
                </div>
              </div>
              <LibraryEntryPreview entry={item} />
              {item.annotation ? (
                <p className="mt-3 line-clamp-4 text-sm text-foreground">{item.annotation}</p>
              ) : (
                <p className="mt-3 text-sm text-muted-foreground italic">No annotation.</p>
              )}
              <div className="mt-3 flex flex-wrap gap-1">
                {(item.tags ?? []).map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full border border-border bg-secondary px-2 py-0.5 text-[0.625rem] text-muted-foreground"
                  >
                    {tag}
                  </span>
                ))}
                {item.industry ? (
                  <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[0.625rem] text-sky-700">
                    {item.industry}
                  </span>
                ) : null}
                {item.channel ? (
                  <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[0.625rem] text-sky-700">
                    {item.channel}
                  </span>
                ) : null}
              </div>
              <p className="mt-3 text-[0.6875rem] text-muted-foreground">
                {item.status === "PUBLISHED" && item.published_at
                  ? `Published ${formatDate(item.published_at)}`
                  : `Created ${formatDate(item.created_at)}`}
                {typeof item.adoption_count === "number"
                  ? ` · adopted by ${item.adoption_count} brand${item.adoption_count === 1 ? "" : "s"}`
                  : ""}
              </p>
              <div className="mt-auto flex flex-wrap gap-2 pt-4">
                {item.status !== "RETIRED" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditing(item);
                      setEditorOpen(true);
                    }}
                  >
                    <Pencil className="size-3.5" /> Edit
                  </Button>
                ) : null}
                {item.status === "DRAFT" ? (
                  <Button size="sm" onClick={() => publish(item)}>
                    <Send className="size-3.5" /> Publish
                  </Button>
                ) : null}
                {item.status === "PUBLISHED" ? (
                  <Button size="sm" variant="outline" onClick={() => retire(item)}>
                    <Archive className="size-3.5" /> Retire
                  </Button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      )}

      <EditorSheet
        item={editing}
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        onSaved={() => void load()}
      />
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </div>
  );
}
