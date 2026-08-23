/**
 * How one Scaleezy library entry shows its content, whatever its kind.
 *
 * Shared by the platform console card and the client gallery card so the
 * two can never render the same entry differently: an image is a picture, a
 * video plays inline, a file is a named chip you can open, text is quoted,
 * and a link is a link. A non-link entry may also carry a source URL, shown
 * as a credit line rather than as the content.
 */
import { ExternalLink, FileText, Image as ImageIcon, Link2, Quote, Video } from "lucide-react";

import type { LibraryEntryFields, LibraryKind } from "@/lib/platform";
import { cn } from "@/lib/utils";

export const KIND_LABEL: Record<LibraryKind, string> = {
  LINK: "Link",
  IMAGE: "Image",
  VIDEO: "Video",
  FILE: "File",
  TEXT: "Text",
};

const KIND_ICON: Record<LibraryKind, typeof Link2> = {
  LINK: Link2,
  IMAGE: ImageIcon,
  VIDEO: Video,
  FILE: FileText,
  TEXT: Quote,
};

export function asKind(value: string | undefined | null): LibraryKind {
  return value && value in KIND_LABEL ? (value as LibraryKind) : "LINK";
}

export function KindBadge({ kind, className }: { kind: string; className?: string }) {
  const k = asKind(kind);
  const Icon = KIND_ICON[k];
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border border-border bg-secondary px-2 py-0.5 text-[0.625rem] font-medium tracking-wide text-muted-foreground uppercase",
        className,
      )}
    >
      <Icon className="size-3" strokeWidth={1.75} /> {KIND_LABEL[k]}
    </span>
  );
}

function SourceLine({ url, label }: { url: string; label: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      className="inline-flex min-w-0 max-w-full items-center gap-1 truncate text-xs text-muted-foreground hover:text-foreground"
    >
      <ExternalLink className="size-3 shrink-0" />
      <span className="truncate">{label}</span>
    </a>
  );
}

export function LibraryEntryPreview({
  entry,
  className,
}: {
  entry: LibraryEntryFields;
  className?: string;
}) {
  const kind = asKind(entry.kind);
  const title = entry.title || entry.file_name || "Library entry";

  return (
    <div className={cn("mt-2 space-y-1.5", className)}>
      {kind === "IMAGE" && entry.file_url ? (
        <a href={entry.file_url} target="_blank" rel="noreferrer noopener" className="block">
          <img
            src={entry.file_url}
            alt={title}
            loading="lazy"
            className="h-44 w-full rounded-lg border border-border bg-secondary object-cover"
          />
        </a>
      ) : null}

      {kind === "VIDEO" && entry.file_url ? (
        <video
          src={entry.file_url}
          controls
          preload="metadata"
          playsInline
          className="h-44 w-full rounded-lg border border-border bg-black object-contain"
        />
      ) : null}

      {kind === "FILE" && entry.file_url ? (
        <a
          href={entry.file_url}
          target="_blank"
          rel="noreferrer noopener"
          className="flex items-center gap-2 rounded-lg border border-border bg-secondary/60 px-3 py-2 text-sm hover:bg-secondary"
        >
          <FileText className="size-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
          <span className="min-w-0 flex-1 truncate">{entry.file_name || "Open file"}</span>
          <span className="shrink-0 text-[0.625rem] text-muted-foreground uppercase">
            {entry.mime_type?.split("/").pop() ?? ""}
          </span>
        </a>
      ) : null}

      {kind === "TEXT" ? (
        <blockquote className="line-clamp-6 rounded-lg border-l-2 border-gold/70 bg-secondary/50 px-3 py-2 text-sm whitespace-pre-wrap text-foreground">
          {entry.body}
        </blockquote>
      ) : null}

      {kind === "LINK" && entry.reference_url ? (
        <SourceLine url={entry.reference_url} label={entry.reference_url} />
      ) : null}

      {kind !== "LINK" && entry.reference_url ? (
        <SourceLine url={entry.reference_url} label={`Source · ${entry.reference_url}`} />
      ) : null}
    </div>
  );
}
