/**
 * What a client has actually made — and what the system learned from it.
 *
 * The console used to list content as four columns of metadata, which told
 * an operator that work existed but never what it looked like. This shows
 * the work.
 *
 * The second thing it shows is the one people assume and get wrong:
 * generating content teaches the brand nothing. Only a human verdict in
 * review writes to the learning ledger, so a card marked "not reviewed" is
 * work the system learned nothing from, however good it was. That is a real
 * state worth seeing at a glance, not a detail to dig for.
 */
import { Check, ImageOff } from "lucide-react";

import { StatusPill } from "@/components/platform/shared";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/platform";

export interface ClientContentRow {
  id: string;
  headline?: string;
  status?: string;
  format?: string;
  preview_url?: string;
  caption?: string;
  taught_learning?: boolean;
  created_at?: string;
}

export function ClientContentGallery({
  rows,
  empty,
}: {
  rows: ClientContentRow[] | undefined;
  empty: string;
}) {
  if (!rows?.length) return <p className="text-sm text-muted-foreground">{empty}</p>;

  const taught = rows.filter((r) => r.taught_learning).length;

  return (
    <div>
      <p className="mb-3 text-xs text-muted-foreground">
        {taught} of {rows.length} taught the brand something. Generating does not teach — only a
        human verdict in review does.
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {rows.map((item) => (
          <figure
            key={item.id}
            className="flex flex-col overflow-hidden rounded-xl border border-border bg-card"
          >
            {item.preview_url ? (
              <a
                href={item.preview_url}
                target="_blank"
                rel="noreferrer noopener"
                className="block bg-secondary"
              >
                <img
                  src={item.preview_url}
                  alt={item.headline || "Generated content"}
                  loading="lazy"
                  className="h-36 w-full object-cover"
                />
              </a>
            ) : (
              <div className="grid h-36 w-full place-items-center bg-secondary text-muted-foreground">
                <ImageOff className="size-5" strokeWidth={1.75} />
              </div>
            )}

            <figcaption className="flex min-w-0 flex-1 flex-col gap-1.5 p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="min-w-0 truncate text-sm font-medium text-foreground">
                  {item.headline || <span className="text-muted-foreground italic">No headline</span>}
                </p>
                {item.status ? <StatusPill value={item.status} /> : null}
              </div>

              {item.caption ? (
                <p className="line-clamp-2 text-xs text-muted-foreground">{item.caption}</p>
              ) : null}

              <div className="mt-auto flex flex-wrap items-center gap-2 pt-1 text-[0.625rem] text-muted-foreground">
                {item.format ? (
                  <span className="rounded-full border border-border bg-secondary px-2 py-0.5 uppercase">
                    {item.format}
                  </span>
                ) : null}
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
                    item.taught_learning
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700"
                      : "border-border bg-secondary",
                  )}
                  title={
                    item.taught_learning
                      ? "A human verdict on this item was recorded as evidence."
                      : "Nobody reviewed this, so the brand learned nothing from it."
                  }
                >
                  {item.taught_learning ? <Check className="size-3" /> : null}
                  {item.taught_learning ? "Taught" : "Not reviewed"}
                </span>
                <span className="ml-auto">{formatDate(item.created_at)}</span>
              </div>
            </figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}
