/**
 * Scaleezy library — references the team curates and shares across clients.
 *
 * A pointer and an annotation, never re-hosted media. Draft → Published →
 * Retired; only published items reach a client's gallery, and only if that
 * client has not opted out of the universal layer.
 */
import { createFileRoute } from "@tanstack/react-router";
import { ExternalLink, Pencil, Plus, RefreshCw, Send, Archive } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
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
  ConfirmDialog,
  ErrorNote,
  PlatformPageHeader,
  StatusPill,
  type ConfirmRequest,
} from "@/components/platform/shared";
import {
  createPlatformInspiration,
  errorText,
  fetchPlatformInspirations,
  formatDate,
  publishPlatformInspiration,
  retirePlatformInspiration,
  updatePlatformInspiration,
  type PlatformInspiration,
  type PlatformInspirationInput,
} from "@/lib/platform";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/platform/library")({
  head: () => ({ meta: [{ title: "Library — Scaleezy Platform Console" }] }),
  component: LibraryPage,
});

const EMPTY_FORM: PlatformInspirationInput = {
  title: "",
  reference_url: "",
  annotation: "",
  tags: [],
  industry: "",
  channel: "",
};

type StatusFilter = "ALL" | "DRAFT" | "PUBLISHED" | "RETIRED";

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
  const [form, setForm] = useState<PlatformInspirationInput>(EMPTY_FORM);
  const [tagsText, setTagsText] = useState("");
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm(
      item
        ? {
            title: item.title,
            reference_url: item.reference_url,
            annotation: item.annotation,
            tags: item.tags ?? [],
            industry: item.industry,
            channel: item.channel,
          }
        : EMPTY_FORM,
    );
    setTagsText((item?.tags ?? []).join(", "));
  }, [item, open]);

  const set = <K extends keyof PlatformInspirationInput>(key: K, value: PlatformInspirationInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const valid = form.title.trim() && /^https?:\/\//i.test(form.reference_url.trim());

  const save = () => {
    const payload: PlatformInspirationInput = {
      ...form,
      title: form.title.trim(),
      reference_url: form.reference_url.trim(),
      annotation: form.annotation.trim(),
      industry: form.industry.trim(),
      channel: form.channel.trim(),
      tags: tagsText
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    };
    setConfirm({
      title: item ? `Save changes to "${payload.title}"?` : `Add "${payload.title}" to the library?`,
      description: item
        ? "Clients who already adopted it keep their copy; the library entry is what changes."
        : "It starts as a draft. Nobody sees it until you publish it.",
      confirmLabel: item ? "Save" : "Create draft",
      run: async () => {
        if (item) await updatePlatformInspiration(item.id, payload);
        else await createPlatformInspiration(payload);
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
              A link and why the team kept it. The annotation, not the artwork, is what a client
              receives.
            </SheetDescription>
          </SheetHeader>
          <div className="mt-6 space-y-4">
            <Field label="Title" id="lib-title">
              <Input id="lib-title" value={form.title} onChange={(e) => set("title", e.target.value)} />
            </Field>
            <Field label="Reference URL" id="lib-url" hint="Must start with http:// or https://">
              <Input
                id="lib-url"
                value={form.reference_url}
                onChange={(e) => set("reference_url", e.target.value)}
                placeholder="https://"
              />
            </Field>
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
  hint?: string;
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

function LibraryPage() {
  const [items, setItems] = useState<PlatformInspiration[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("ALL");
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

  const visible = (items ?? []).filter((i) => filter === "ALL" || i.status === filter);
  const counts = {
    ALL: items?.length ?? 0,
    DRAFT: items?.filter((i) => i.status === "DRAFT").length ?? 0,
    PUBLISHED: items?.filter((i) => i.status === "PUBLISHED").length ?? 0,
    RETIRED: items?.filter((i) => i.status === "RETIRED").length ?? 0,
  };

  return (
    <div>
      <PlatformPageHeader
        eyebrow="Platform"
        title="Library"
        subtitle="Curated references every client can adopt. Links and annotations only — nothing is re-hosted, and nothing here ever comes from a client's own material."
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

      <div className="mb-4 flex flex-wrap gap-2">
        {(["ALL", "DRAFT", "PUBLISHED", "RETIRED"] as StatusFilter[]).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setFilter(value)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              filter === value
                ? "border-slate-900 bg-slate-900 text-white"
                : "border-border bg-background text-muted-foreground hover:text-foreground",
            )}
          >
            {value === "ALL" ? "All" : value.charAt(0) + value.slice(1).toLowerCase()} · {counts[value]}
          </button>
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
            {filter === "ALL"
              ? "Add the first reference the team wants every client to see."
              : "No entries with this status."}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((item) => (
            <article key={item.id} className="surface-card flex flex-col p-4">
              <div className="flex items-start justify-between gap-2">
                <h3 className="min-w-0 font-medium text-foreground">{item.title}</h3>
                <StatusPill value={item.status} />
              </div>
              <a
                href={item.reference_url}
                target="_blank"
                rel="noreferrer noopener"
                className="mt-1 inline-flex items-center gap-1 truncate text-xs text-muted-foreground hover:text-foreground"
              >
                <ExternalLink className="size-3 shrink-0" />
                <span className="truncate">{item.reference_url}</span>
              </a>
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
