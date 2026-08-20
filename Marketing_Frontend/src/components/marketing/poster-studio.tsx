import { Download, Loader2, Wand2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api, apiPost } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface LayoutOption {
  key: string;
  display_name: string;
  description: string;
  uses_photo: boolean;
}

export interface SizeOption {
  key: string;
  label: string;
  width: number;
  height: number;
  platform: string;
  format: string;
}

interface Catalogue {
  layouts: LayoutOption[];
  sizes: SizeOption[];
}

/**
 * The layout catalogue is global and small, so it is fetched once and shared
 * rather than re-requested per card.
 */
export function useLayoutCatalogue() {
  const [catalogue, setCatalogue] = useState<Catalogue>({ layouts: [], sizes: [] });

  useEffect(() => {
    let cancelled = false;
    void api<Catalogue>("/api/marketing/layouts/")
      .then((data) => {
        if (!cancelled) setCatalogue({ layouts: data.layouts ?? [], sizes: data.sizes ?? [] });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return catalogue;
}

/**
 * Compose a poster server-side from the brand's own palette, fonts and photo,
 * then export it at each platform's dimensions.
 *
 * The preview is composed by the same code that produces the final file, so
 * what is shown here is what ships — no separate client-side approximation to
 * drift out of sync.
 */
export function PosterStudio({
  contentItemId,
  layouts,
  sizes,
  defaultLayout,
  onRendered,
}: {
  contentItemId: string;
  layouts: LayoutOption[];
  sizes: SizeOption[];
  defaultLayout?: string | undefined;
  onRendered?: (() => void) | undefined;
}) {
  const [layout, setLayout] = useState(defaultLayout || layouts[0]?.key || "");
  const [preview, setPreview] = useState<string>("");
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState<"render" | "export" | null>(null);
  const [chosen, setChosen] = useState<string[]>(["instagram_portrait"]);
  const [exported, setExported] = useState<{ label: string; url: string }[]>([]);

  // Preview requests are superseded as the user clicks through layouts; only
  // the newest response may paint, or a slow earlier one wins the race.
  const request = useRef(0);

  const loadPreview = useCallback(
    async (key: string) => {
      if (!key) return;
      const ticket = ++request.current;
      setPreviewing(true);
      try {
        const data = await apiPost<{ preview: string }>("/api/marketing/layouts/preview/", {
          content_item: contentItemId,
          layout: key,
        });
        if (ticket === request.current) setPreview(data.preview);
      } catch (e) {
        if (ticket === request.current) {
          setPreview("");
          toast.error(e instanceof Error ? e.message : "Could not compose a preview.");
        }
      } finally {
        if (ticket === request.current) setPreviewing(false);
      }
    },
    [contentItemId],
  );

  useEffect(() => {
    void loadPreview(layout);
  }, [layout, loadPreview]);

  const render = async () => {
    setBusy("render");
    try {
      await apiPost("/api/marketing/layouts/render/", {
        content_item: contentItemId,
        layout,
      });
      toast.success("Composed on-brand and saved.");
      onRendered?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not compose the poster.");
    } finally {
      setBusy(null);
    }
  };

  const runExport = async () => {
    if (chosen.length === 0) return;
    setBusy("export");
    try {
      const data = await apiPost<{
        exports: { label: string; url: string }[];
        failures: { size: string; error: string }[];
      }>("/api/marketing/layouts/export/", {
        content_item: contentItemId,
        layout,
        sizes: chosen,
      });
      setExported(data.exports ?? []);
      if (data.failures?.length) {
        toast.warning(`${data.failures.length} size(s) could not be exported.`);
      } else {
        toast.success(`Exported ${data.exports.length} size(s).`);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Export failed.");
    } finally {
      setBusy(null);
    }
  };

  const toggleSize = (key: string) =>
    setChosen((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));

  return (
    <div className="mt-4 rounded-xl border border-border bg-secondary/20 p-4">
      <p className="text-xs font-medium text-foreground">Compose on-brand</p>
      <p className="mt-0.5 text-[0.6875rem] text-muted-foreground">
        Built server-side from your palette, fonts and photo — identical every time, at any
        size.
      </p>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {layouts.map((option) => (
          <button
            key={option.key}
            type="button"
            title={option.description}
            disabled={busy !== null}
            onClick={() => setLayout(option.key)}
            className={cn(
              "rounded-full border px-2.5 py-1 text-[0.6875rem] transition-colors",
              layout === option.key
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-background text-muted-foreground hover:text-foreground",
            )}
          >
            {option.display_name}
          </button>
        ))}
      </div>

      <div className="relative mt-3 overflow-hidden rounded-lg border border-border bg-background">
        {preview ? (
          <img src={preview} alt="Composed poster preview" className="w-full" />
        ) : (
          <div className="grid h-40 place-items-center text-xs text-muted-foreground">
            {previewing ? "Composing…" : "No preview"}
          </div>
        )}
        {previewing && preview ? (
          <div className="absolute inset-0 grid place-items-center bg-background/60">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : null}
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {sizes.map((size) => (
          <button
            key={size.key}
            type="button"
            disabled={busy !== null}
            onClick={() => toggleSize(size.key)}
            className={cn(
              "rounded-md border px-2 py-1 text-[0.6875rem] transition-colors",
              chosen.includes(size.key)
                ? "border-primary bg-primary/10 font-medium text-foreground"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {size.label}
            <span className="ml-1 opacity-60">
              {size.width}×{size.height}
            </span>
          </button>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" disabled={busy !== null || !layout} onClick={() => void render()}>
          {busy === "render" ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Wand2 className="size-4" />
          )}
          Use this poster
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy !== null || chosen.length === 0}
          onClick={() => void runExport()}
        >
          {busy === "export" ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Download className="size-4" />
          )}
          Export {chosen.length} size{chosen.length === 1 ? "" : "s"}
        </Button>
      </div>

      {exported.length > 0 ? (
        <ul className="mt-3 space-y-1">
          {exported.map((file) => (
            <li key={file.url} className="text-[0.6875rem]">
              <a
                href={file.url}
                target="_blank"
                rel="noreferrer"
                className="text-foreground underline underline-offset-2"
              >
                {file.label}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
