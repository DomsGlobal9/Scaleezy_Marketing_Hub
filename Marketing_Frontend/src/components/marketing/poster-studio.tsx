import { Download, Loader2, Wand2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, apiPost } from "@/lib/api";
import { cn } from "@/lib/utils";

/** The words on the poster, editable in place. Blank means "use the item's own". */
interface PosterCopy {
  headline: string;
  subheadline: string;
  offer: string;
  cta: string;
}

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
  initialHeadline,
  initialOffer,
  initialSubheadline,
  initialCta,
  onRendered,
}: {
  contentItemId: string;
  layouts: LayoutOption[];
  sizes: SizeOption[];
  defaultLayout?: string | undefined;
  initialHeadline?: string | undefined;
  initialOffer?: string | undefined;
  initialSubheadline?: string | undefined;
  initialCta?: string | undefined;
  onRendered?: (() => void) | undefined;
}) {
  const [layout, setLayout] = useState(defaultLayout || layouts[0]?.key || "");
  const [copy, setCopy] = useState<PosterCopy>({
    headline: initialHeadline ?? "",
    subheadline: initialSubheadline ?? "",
    offer: initialOffer ?? "",
    cta: initialCta ?? "",
  });
  const [preview, setPreview] = useState<string>("");
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState<"render" | "export" | null>(null);
  const [chosen, setChosen] = useState<string[]>(["instagram_portrait"]);
  const [exported, setExported] = useState<{ label: string; url: string }[]>([]);

  // Preview requests are superseded as the user clicks through layouts or
  // types; only the newest response may paint, or a slow earlier one wins.
  const request = useRef(0);

  // Headline and offer are omitted when blank, so the server falls back to
  // the item's generated copy. Subheadline and CTA are ALWAYS sent — an
  // explicit blank is how a saved line gets removed rather than resurrected.
  const copyOverrides = useCallback(
    (values: PosterCopy) => ({
      ...(values.headline.trim() !== "" ? { headline: values.headline } : {}),
      ...(values.offer.trim() !== "" ? { offer: values.offer } : {}),
      subheadline: values.subheadline,
      cta: values.cta,
    }),
    [],
  );

  const loadPreview = useCallback(
    async (key: string, values: PosterCopy) => {
      if (!key) return;
      const ticket = ++request.current;
      setPreviewing(true);
      try {
        const data = await apiPost<{ preview: string }>("/api/marketing/layouts/preview/", {
          content_item: contentItemId,
          layout: key,
          ...copyOverrides(values),
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
    [contentItemId, copyOverrides],
  );

  // One debounced effect covers layout clicks and typing alike: the preview
  // follows whatever is on screen, 400ms behind the last keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      void loadPreview(layout, copy);
    }, 400);
    return () => clearTimeout(timer);
  }, [layout, copy, loadPreview]);

  const setField = (field: keyof PosterCopy) => (value: string) =>
    setCopy((prev) => ({ ...prev, [field]: value }));

  const render = async () => {
    setBusy("render");
    try {
      await apiPost("/api/marketing/layouts/render/", {
        content_item: contentItemId,
        layout,
        // The same words as the preview on screen — the render must never
        // quietly differ from what was approved by eye.
        ...copyOverrides(copy),
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
        // The words on screen, on every exported size — an export must never
        // quietly ship different copy than the preview beside its button.
        ...copyOverrides(copy),
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

      {/* The words on the poster, editable next to the preview they change. */}
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="space-y-1">
          <label
            htmlFor={`studio-headline-${contentItemId}`}
            className="text-[0.6875rem] font-medium text-foreground"
          >
            Headline
          </label>
          <Input
            id={`studio-headline-${contentItemId}`}
            value={copy.headline}
            maxLength={500}
            disabled={busy !== null}
            placeholder="The big line on the poster"
            onChange={(e) => setField("headline")(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label
            htmlFor={`studio-subheadline-${contentItemId}`}
            className="text-[0.6875rem] font-medium text-foreground"
          >
            Subheadline
          </label>
          <Input
            id={`studio-subheadline-${contentItemId}`}
            value={copy.subheadline}
            maxLength={500}
            disabled={busy !== null}
            placeholder="Supporting line (optional)"
            onChange={(e) => setField("subheadline")(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label
            htmlFor={`studio-offer-${contentItemId}`}
            className="text-[0.6875rem] font-medium text-foreground"
          >
            Offer
          </label>
          <Input
            id={`studio-offer-${contentItemId}`}
            value={copy.offer}
            maxLength={255}
            disabled={busy !== null}
            placeholder="e.g. 50% OFF"
            onChange={(e) => setField("offer")(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label
            htmlFor={`studio-cta-${contentItemId}`}
            className="text-[0.6875rem] font-medium text-foreground"
          >
            Call to action
          </label>
          <Input
            id={`studio-cta-${contentItemId}`}
            value={copy.cta}
            maxLength={255}
            disabled={busy !== null}
            placeholder="e.g. Shop the collection"
            onChange={(e) => setField("cta")(e.target.value)}
          />
        </div>
      </div>
      <p className="mt-1.5 text-[0.6875rem] text-muted-foreground">
        The preview follows as you type. A blank headline or offer falls back to the
        generated copy; a blank subheadline or call to action removes that line.
      </p>

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
