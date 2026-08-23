/**
 * Universal standards — Scaleezy's own craft rules, authored here.
 *
 * Shaped as claims (category / attribute / value + the guidance sentence a
 * generation receives) so they drop into the same precedence machinery the
 * Brand Brain uses, at a rank weaker than anything a client stated. Preview
 * shows how many active brands a standard would reach — and says plainly that
 * scope matching is exact, because industry is free text.
 */
import { createFileRoute } from "@tanstack/react-router";
import { Archive, Eye, Loader2, Pencil, Plus, RefreshCw, Send } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  RecordTable,
  StatusPill,
  type ConfirmRequest,
} from "@/components/platform/shared";
import {
  createStandard,
  errorText,
  fetchStandards,
  formatDate,
  previewStandard,
  publishStandard,
  retireStandard,
  updateStandard,
  type StandardInput,
  type StandardPreview,
  type UniversalScope,
  type UniversalStandard,
} from "@/lib/platform";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/platform/standards")({
  head: () => ({ meta: [{ title: "Standards — Scaleezy Platform Console" }] }),
  component: StandardsPage,
});

const SCOPES: Array<{ value: UniversalScope; label: string; hint: string }> = [
  { value: "GLOBAL", label: "Every client", hint: "Applies to every generation on the platform." },
  { value: "INDUSTRY", label: "One industry", hint: "Matched exactly against Brand.industry." },
  { value: "CHANNEL", label: "One channel", hint: "Matched exactly against the generation's channel." },
  { value: "CONTENT_TYPE", label: "One content type", hint: "Matched exactly against the content type." },
];

const EMPTY_FORM: StandardInput = {
  title: "",
  rationale: "",
  category: "",
  attribute: "",
  value: "",
  guidance: "",
  scope: "GLOBAL",
  scope_value: "",
};

type StatusFilter = "ALL" | "DRAFT" | "PUBLISHED" | "RETIRED";

/* ------------------------------------------------------------------- editor */

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

function EditorSheet({
  standard,
  open,
  onClose,
  onSaved,
}: {
  standard: UniversalStandard | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<StandardInput>(EMPTY_FORM);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm(
      standard
        ? {
            title: standard.title,
            rationale: standard.rationale,
            category: standard.category,
            attribute: standard.attribute,
            value: standard.value,
            guidance: standard.guidance,
            scope: (standard.scope as UniversalScope) || "GLOBAL",
            scope_value: standard.scope_value,
          }
        : EMPTY_FORM,
    );
  }, [standard, open]);

  const set = <K extends keyof StandardInput>(key: K, value: StandardInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const scopeMeta = SCOPES.find((s) => s.value === form.scope);
  const valid =
    form.title.trim() &&
    form.category.trim() &&
    form.attribute.trim() &&
    form.value.trim() &&
    form.guidance.trim() &&
    (form.scope === "GLOBAL" || form.scope_value.trim());

  const save = () => {
    const payload: StandardInput = {
      title: form.title.trim(),
      rationale: form.rationale.trim(),
      category: form.category.trim().toUpperCase(),
      attribute: form.attribute.trim(),
      value: form.value.trim(),
      guidance: form.guidance.trim(),
      scope: form.scope,
      scope_value: form.scope === "GLOBAL" ? "" : form.scope_value.trim(),
    };
    setConfirm({
      title: standard ? `Save changes to "${payload.title}"?` : `Create "${payload.title}"?`,
      description: standard
        ? standard.status === "PUBLISHED"
          ? "This standard is live. The change reaches the next generation for every brand in scope."
          : "Saved as a draft until you publish it."
        : "It starts as a draft. Nothing reaches a client until you publish it.",
      confirmLabel: standard ? "Save" : "Create draft",
      run: async () => {
        if (standard) await updateStandard(standard.id, payload);
        else await createStandard(payload);
        toast.success(standard ? "Standard updated." : "Draft created.");
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
            <SheetTitle>{standard ? "Edit standard" : "New standard"}</SheetTitle>
            <SheetDescription>
              A claim plus the sentence a generation receives. It sits below every brand-specific
              rule, so it can never override what a client said.
            </SheetDescription>
          </SheetHeader>
          <div className="mt-6 space-y-4">
            <Field label="Title" id="std-title">
              <Input id="std-title" value={form.title} onChange={(e) => set("title", e.target.value)} />
            </Field>
            <Field label="Rationale" id="std-rationale" hint="For the team. Never sent to a provider.">
              <Textarea
                id="std-rationale"
                rows={2}
                value={form.rationale}
                onChange={(e) => set("rationale", e.target.value)}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Category" id="std-category" hint="e.g. COPY_STYLE">
                <Input
                  id="std-category"
                  value={form.category}
                  onChange={(e) => set("category", e.target.value)}
                />
              </Field>
              <Field label="Attribute" id="std-attribute" hint="e.g. length">
                <Input
                  id="std-attribute"
                  value={form.attribute}
                  onChange={(e) => set("attribute", e.target.value)}
                />
              </Field>
              <Field label="Value" id="std-value" hint="e.g. short">
                <Input id="std-value" value={form.value} onChange={(e) => set("value", e.target.value)} />
              </Field>
            </div>
            <Field label="Guidance" id="std-guidance" hint="The sentence the generation actually receives.">
              <Textarea
                id="std-guidance"
                rows={4}
                value={form.guidance}
                onChange={(e) => set("guidance", e.target.value)}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Scope" id="std-scope" hint={scopeMeta?.hint}>
                <Select value={form.scope} onValueChange={(v) => set("scope", v as UniversalScope)}>
                  <SelectTrigger id="std-scope" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SCOPES.map((s) => (
                      <SelectItem key={s.value} value={s.value}>
                        {s.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              {form.scope !== "GLOBAL" ? (
                <Field
                  label="Scope value"
                  id="std-scope-value"
                  hint="Exact match after trimming and case-folding. No fuzzy matching."
                >
                  <Input
                    id="std-scope-value"
                    value={form.scope_value}
                    onChange={(e) => set("scope_value", e.target.value)}
                  />
                </Field>
              ) : null}
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={save} disabled={!valid}>
                {standard ? "Save…" : "Create draft…"}
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </>
  );
}

/* ------------------------------------------------------------------ preview */

function PreviewDialog({
  standard,
  onClose,
}: {
  standard: UniversalStandard | null;
  onClose: () => void;
}) {
  const [preview, setPreview] = useState<StandardPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!standard) return;
    let cancelled = false;
    setPreview(null);
    setError(null);
    setLoading(true);
    previewStandard(standard.id)
      .then((value) => {
        if (!cancelled) setPreview(value);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(errorText(e, "Could not compute the preview."));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [standard]);

  return (
    <Dialog open={!!standard} onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Who "{standard?.title}" would reach</DialogTitle>
          <DialogDescription>
            Computed now against active brands. A published standard reaches exactly these on their
            next generation.
          </DialogDescription>
        </DialogHeader>
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Matching brands…
          </div>
        ) : error ? (
          <ErrorNote message={error} />
        ) : preview ? (
          <div className="space-y-4">
            <p className="font-display text-3xl font-semibold text-foreground">
              {preview.matched_brand_count}
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                of {preview.total_active_brands} active brand
                {preview.total_active_brands === 1 ? "" : "s"}
              </span>
            </p>
            {preview.exact_match_only ? (
              <p className="rounded-lg border border-amber-400/50 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                Scope matching is exact after trimming and case-folding. Brand industry is free text,
                so "Apparel" and "Apparel &amp; fashion" are different industries here — a standard
                that leaks into a neighbouring industry is worse than one that reaches nobody.
              </p>
            ) : null}
            {preview.note ? <p className="text-xs text-muted-foreground">{preview.note}</p> : null}
            <div className="max-h-72 overflow-auto">
              <RecordTable rows={preview.brands} empty="No brand matches this scope right now." />
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

/* --------------------------------------------------------------------- page */

function StandardsPage() {
  const [standards, setStandards] = useState<UniversalStandard[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("ALL");
  const [editing, setEditing] = useState<UniversalStandard | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [previewing, setPreviewing] = useState<UniversalStandard | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStandards(await fetchStandards());
    } catch (e: unknown) {
      setError(errorText(e, "Could not load standards."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const publish = (standard: UniversalStandard) =>
    setConfirm({
      title: `Publish "${standard.title}"?`,
      description:
        "From the next generation on, every brand in scope receives this guidance at universal rank — below every brand-specific rule. Cached context is invalidated immediately.",
      confirmLabel: "Publish",
      run: async () => {
        await publishStandard(standard.id);
        toast.success("Published.");
        await load();
      },
    });

  const retire = (standard: UniversalStandard) =>
    setConfirm({
      title: `Retire "${standard.title}"?`,
      description: "It stops reaching generations immediately. The row stays for lineage.",
      confirmLabel: "Retire",
      destructive: true,
      reason: { label: "Reason", placeholder: "Optional — why it is being retired" },
      run: async (reason) => {
        await retireStandard(standard.id, reason);
        toast.success("Retired.");
        await load();
      },
    });

  const visible = (standards ?? []).filter((s) => filter === "ALL" || s.status === filter);
  const counts = {
    ALL: standards?.length ?? 0,
    DRAFT: standards?.filter((s) => s.status === "DRAFT").length ?? 0,
    PUBLISHED: standards?.filter((s) => s.status === "PUBLISHED").length ?? 0,
    RETIRED: standards?.filter((s) => s.status === "RETIRED").length ?? 0,
  };

  return (
    <div>
      <PlatformPageHeader
        eyebrow="Platform"
        title="Standards"
        subtitle="Scaleezy's own craft rules. They reach every generation in scope at a rank weaker than anything a client stated, confirmed or was learned from their own behaviour."
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
              <Plus className="size-4" /> New standard
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

      {loading && !standards ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-xl" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="surface-card p-10 text-center">
          <p className="font-medium text-foreground">No standards {filter === "ALL" ? "yet" : "with this status"}.</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {filter === "ALL"
              ? "Write the first one. It stays a draft until you publish it."
              : "Try another filter."}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-[0.625rem] tracking-wide text-muted-foreground uppercase">
              <tr>
                <th className="px-3 py-2 font-semibold">Standard</th>
                <th className="px-3 py-2 font-semibold">Claim</th>
                <th className="px-3 py-2 font-semibold">Scope</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((standard) => (
                <tr key={standard.id} className="border-t border-border align-top">
                  <td className="max-w-md px-3 py-3">
                    <p className="font-medium text-foreground">{standard.title}</p>
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{standard.guidance}</p>
                  </td>
                  <td className="px-3 py-3 font-mono text-[0.6875rem] text-muted-foreground">
                    {standard.category} / {standard.attribute} = {standard.value}
                  </td>
                  <td className="px-3 py-3 text-xs">
                    <p className="text-foreground">
                      {SCOPES.find((s) => s.value === standard.scope)?.label ?? standard.scope}
                    </p>
                    {standard.scope_value ? (
                      <p className="text-muted-foreground">= {standard.scope_value}</p>
                    ) : null}
                  </td>
                  <td className="px-3 py-3 text-xs">
                    <StatusPill value={standard.status} />
                    <p className="mt-1 text-muted-foreground">
                      {standard.status === "PUBLISHED"
                        ? `since ${formatDate(standard.published_at)}`
                        : standard.status === "RETIRED"
                          ? `retired ${formatDate(standard.retired_at)}`
                          : `created ${formatDate(standard.updated_at ?? standard.created_at)}`}
                    </p>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      <Button size="sm" variant="outline" onClick={() => setPreviewing(standard)}>
                        <Eye className="size-3.5" /> Preview
                      </Button>
                      {standard.status !== "RETIRED" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setEditing(standard);
                            setEditorOpen(true);
                          }}
                        >
                          <Pencil className="size-3.5" /> Edit
                        </Button>
                      ) : null}
                      {standard.status === "DRAFT" ? (
                        <Button size="sm" onClick={() => publish(standard)}>
                          <Send className="size-3.5" /> Publish
                        </Button>
                      ) : null}
                      {standard.status === "PUBLISHED" ? (
                        <Button size="sm" variant="outline" onClick={() => retire(standard)}>
                          <Archive className="size-3.5" /> Retire
                        </Button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <EditorSheet
        standard={editing}
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        onSaved={() => void load()}
      />
      <PreviewDialog standard={previewing} onClose={() => setPreviewing(null)} />
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </div>
  );
}
