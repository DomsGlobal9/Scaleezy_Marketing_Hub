/**
 * Templates — the brand's own uploaded poster designs.
 *
 * The founder removed the built-in template catalogue; this is its
 * replacement. Every design uploaded here becomes a BRAND_TEMPLATE
 * inspiration: stored and analysed through the same inspirations API as any
 * other reference, and offered as "Your templates" in Create Studio.
 * Archiving takes a template off those surfaces without destroying the
 * record.
 */
import { Archive, Image as ImageIcon, Loader2, Sparkles, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Empty,
  Failed,
  Loading,
  errorMessage,
  useSlice,
} from "@/components/marketing/brand-master-primitives";
import {
  analyzeInspiration,
  archiveInspiration,
  fetchBrandTemplates,
  humanize,
  uploadBrandTemplate,
  type Inspiration,
} from "@/lib/brand-master";

const ANALYSIS_LINE: Record<string, string> = {
  NOT_ANALYSED: "Not analysed yet — analyse it so generations can read its style.",
  QUEUED: "Analysis queued…",
  PROCESSING: "Scaleezy is reading this template…",
  NEEDS_REVIEW: "Analysed. Review the observations under Brand inspirations signals.",
  READY: "Analysed and ready.",
  FAILED: "Analysis failed. Retry it.",
};

export function TemplatesPanel({
  brandId,
  onChanged,
}: {
  brandId: string;
  onChanged: () => void;
}) {
  const templates = useSlice<Inspiration[]>(() => fetchBrandTemplates(brandId), true);
  const [uploading, setUploading] = useState(false);
  const [title, setTitle] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  // Same polling idiom as the inspirations panel: keep refreshing while any
  // template is being analysed so the status line tells the truth.
  useEffect(() => {
    if (
      !(templates.data ?? []).some((row) =>
        ["QUEUED", "PROCESSING"].includes(row.analysis_status),
      )
    )
      return;
    const timer = window.setInterval(() => templates.reload(), 3000);
    return () => window.clearInterval(timer);
  }, [templates.data, templates.reload]);

  const refresh = () => {
    templates.reload();
    onChanged();
  };

  const upload = async (file: File) => {
    setUploading(true);
    try {
      const created = await uploadBrandTemplate(brandId, file, title.trim());
      setTitle("");
      toast.success("Template uploaded. Analysing it teaches Scaleezy its style.");
      refresh();
      // Queue analysis immediately — a template exists to be matched, and
      // matching needs the extracted style observations. Best effort: the
      // card keeps a retry button if the queue is unavailable.
      try {
        await analyzeInspiration(created.id);
        templates.reload();
      } catch {
        /* the status line shows NOT_ANALYSED with a retry */
      }
    } catch (e) {
      toast.error(errorMessage(e, "Could not upload the template."));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  if (templates.loading && !templates.data) return <Loading />;
  if (templates.error) return <Failed message={templates.error} onRetry={templates.reload} />;

  const rows = templates.data ?? [];
  const active = rows.filter((row) => row.lifecycle_status !== "ARCHIVED");
  const archived = rows.filter((row) => row.lifecycle_status === "ARCHIVED");

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <p className="text-sm text-muted-foreground">
            Upload the poster designs your brand already uses. In Create Studio they appear as
            “Your templates”, and generations match the one you choose instead of a built-in
            pattern.
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            JPEG, PNG or WebP. Archived templates leave Create Studio but stay on record.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Template name (optional)"
            className="w-52"
            aria-label="Template name"
          />
          <Button disabled={uploading} onClick={() => fileRef.current?.click()}>
            {uploading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Upload className="size-4" />
            )}
            {uploading ? "Uploading…" : "Upload template"}
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            aria-label="Template file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
          />
        </div>
      </div>

      {active.length === 0 ? (
        <Empty
          title="No templates yet"
          hint="Upload your poster templates — every generation will match them."
          action={
            <Button variant="outline" disabled={uploading} onClick={() => fileRef.current?.click()}>
              <Upload className="size-4" /> Upload your first template
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {active.map((template) => (
            <TemplateCard key={template.id} template={template} onChanged={refresh} />
          ))}
        </div>
      )}

      {archived.length > 0 ? (
        <div>
          <p className="label-eyebrow mb-2">Archived</p>
          <ul className="space-y-2">
            {archived.map((template) => (
              <li
                key={template.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 opacity-70"
              >
                <span className="min-w-0 truncate text-sm">{template.title}</span>
                <Badge variant="outline">archived</Badge>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function TemplateCard({
  template,
  onChanged,
}: {
  template: Inspiration;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<"analyze" | "archive" | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const analysing = ["QUEUED", "PROCESSING"].includes(template.analysis_status);

  const analyze = async () => {
    setBusy("analyze");
    try {
      await analyzeInspiration(template.id);
      toast.success("Analysis queued.");
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e, "Could not analyse this template."));
    } finally {
      setBusy(null);
    }
  };

  const archive = async () => {
    setBusy("archive");
    try {
      await archiveInspiration(template.id);
      toast("Template archived. It no longer appears in Create Studio.");
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e, "Could not archive."));
    } finally {
      setBusy(null);
      setConfirmArchive(false);
    }
  };

  return (
    <Card className="overflow-hidden py-0">
      <CardContent className="p-0">
        {template.file_url ? (
          <a href={template.file_url} target="_blank" rel="noreferrer" className="block">
            <img
              src={template.file_url}
              alt={template.title}
              loading="lazy"
              decoding="async"
              className="aspect-[4/5] w-full border-b object-cover"
            />
          </a>
        ) : (
          <div className="grid aspect-[4/5] w-full place-items-center border-b text-muted-foreground">
            <ImageIcon className="size-8" aria-hidden="true" />
          </div>
        )}
        <div className="space-y-3 p-4">
          <div>
            <p className="truncate font-medium">{template.title}</p>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              {analysing ? <Loader2 className="size-3 animate-spin" aria-hidden="true" /> : null}
              {ANALYSIS_LINE[template.analysis_status] ?? humanize(template.analysis_status)}
            </p>
          </div>
          {confirmArchive ? (
            <div className="flex items-center gap-2">
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
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={busy === "analyze" || analysing}
                onClick={analyze}
              >
                {busy === "analyze" || analysing ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Sparkles className="size-3.5" />
                )}
                {template.analysis_status === "FAILED" ? "Retry analysis" : "Analyse"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmArchive(true)}>
                <Archive className="size-3.5" /> Archive
              </Button>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
