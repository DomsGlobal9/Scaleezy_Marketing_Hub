/**
 * The Scaleezy library, as this client may see it.
 *
 * Curated references the platform publishes — a link and an annotation, never
 * re-hosted media. Adopt copies one into the brand's OWN inspirations, where
 * it is treated like anything the client added themselves. The server decides
 * what is visible (published only, and nothing if the client opted out of the
 * universal layer), so an empty gallery is reported as empty rather than
 * padded.
 */
import { BookMarked, Check, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Chip, Empty, InlineError, Loading } from "@/components/marketing/brand-master-primitives";
import { SectionTitle } from "@/components/marketing/primitives";
import {
  adoptLibraryItem,
  errorText,
  fetchLibraryGallery,
  type LibraryItem,
} from "@/lib/platform";

export function LibraryGallery({ brandId, onChanged }: { brandId: string; onChanged?: () => void }) {
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adopting, setAdopting] = useState<string | null>(null);
  const [adopted, setAdopted] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await fetchLibraryGallery());
    } catch (e: unknown) {
      setError(errorText(e, "Could not load the Scaleezy library."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const adopt = async (item: LibraryItem) => {
    if (adopting) return;
    setAdopting(item.id);
    setError(null);
    try {
      const result = await adoptLibraryItem(item.id, brandId);
      const message = result.created ? "Added to your inspirations." : "Already in your inspirations.";
      setAdopted((prev) => ({ ...prev, [item.id]: message }));
      toast.success(message);
      if (result.created) onChanged?.();
    } catch (e: unknown) {
      setError(errorText(e, "That reference could not be adopted."));
    } finally {
      setAdopting(null);
    }
  };

  return (
    <section>
      <SectionTitle
        label="Scaleezy library"
        title="References curated by Scaleezy"
        description="Good work the team keeps for everyone. Adopt one and it becomes part of your own inspirations, with the annotation Scaleezy wrote."
        action={
          <Button variant="ghost" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={loading ? "size-4 animate-spin" : "size-4"} /> Refresh
          </Button>
        }
      />

      <InlineError message={error} />

      {loading && !items ? (
        <Loading rows={3} />
      ) : items && items.length === 0 ? (
        <Empty
          title="Nothing in the library for you yet"
          hint="Scaleezy has not published references this client can see. Your own inspirations above are what generation reads."
        />
      ) : items ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => {
            const done = adopted[item.id];
            return (
              <article key={item.id} className="flex flex-col rounded-xl border border-border bg-card p-4">
                <div className="flex items-start gap-2">
                  <BookMarked className="mt-0.5 size-4 shrink-0 text-gold" strokeWidth={1.75} />
                  <h3 className="min-w-0 font-medium text-foreground">{item.title}</h3>
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
                    <Chip key={tag} tone="soft">
                      {tag}
                    </Chip>
                  ))}
                  {item.industry ? <Chip tone="ai">{item.industry}</Chip> : null}
                  {item.channel ? <Chip tone="ai">{item.channel}</Chip> : null}
                </div>
                <div className="mt-auto pt-4">
                  {done ? (
                    <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700">
                      <Check className="size-3.5" /> {done}
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void adopt(item)}
                      disabled={adopting !== null}
                    >
                      {adopting === item.id ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <Check className="size-3.5" />
                      )}
                      Adopt
                    </Button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
