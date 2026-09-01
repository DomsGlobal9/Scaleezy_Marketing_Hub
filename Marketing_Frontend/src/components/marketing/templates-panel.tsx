/**
 * The template catalogue, finally visible.
 *
 * The founder asked "where to find the templates". A template is a layout
 * skeleton dressed by a style variant (colour scheme x photo grading x paper
 * tint x casing x type pairing), which multiplies six hand-tuned skeletons
 * into 1,200+ distinct looks. This panel shows each skeleton rendered live
 * with the brand's own palette and fonts, explains the style axes, and lets
 * the reviewer either pin one skeleton for every poster or leave Scaleezy
 * rotating through the whole catalogue (the default, and the recommendation).
 */
import { Check, Loader2, Shuffle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";
import { Failed, Loading } from "@/components/marketing/brand-master-primitives";
import { SectionTitle } from "@/components/marketing/primitives";

interface LayoutInfo {
  key: string;
  display_name: string;
  description: string;
  uses_photo: boolean;
  /** Lowercase tags; empty means the skeleton fits any industry. */
  industries?: string[];
}

interface TemplatesInfo {
  total: number;
  axes: Record<string, string[]>;
}

interface CatalogueResponse {
  layouts: LayoutInfo[];
  templates?: TemplatesInfo;
}

interface PreviewResponse {
  preview: string;
}

interface BrandLite {
  id: string;
  layout_preference?: string;
  industry?: string;
}

const AXIS_LABELS: Record<string, string> = {
  palette: "Colour scheme",
  photo: "Photo grading",
  paper: "Background tint",
  casing: "Headline casing",
  pairing: "Type pairing",
};

const pretty = (value: string) => value.replace(/_/g, " ");

/** 288 or 48 — how many dressed variations one skeleton yields. */
function variantsPerLayout(layout: LayoutInfo, axes: Record<string, string[]>) {
  return Object.entries(axes).reduce(
    (count, [axis, options]) =>
      count * (axis === "photo" && !layout.uses_photo ? 1 : options.length),
    1,
  );
}

export function TemplatesPanel() {
  const [layouts, setLayouts] = useState<LayoutInfo[]>([]);
  const [templates, setTemplates] = useState<TemplatesInfo | null>(null);
  const [brand, setBrand] = useState<BrandLite | null>(null);
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [industry, setIndustry] = useState("all");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [catalogue, current] = await Promise.all([
          api<CatalogueResponse>("/api/marketing/layouts/"),
          api<BrandLite>("/api/marketing/brands/current/"),
        ]);
        if (cancelled) return;
        setLayouts(catalogue.layouts ?? []);
        setTemplates(catalogue.templates ?? null);
        setBrand(current);
        setLoading(false);

        // Previews render server-side with the brand's real palette, fonts,
        // tagline and logo — sequentially, so six PIL renders do not pile on
        // the backend at once. Each card fills in as its render lands.
        for (const layout of catalogue.layouts ?? []) {
          if (cancelled) return;
          try {
            const rendered = await api<PreviewResponse>("/api/marketing/layouts/preview/", {
              method: "POST",
              body: {
                layout: layout.key,
                headline: "This weekend only",
                offer: "30% OFF",
              },
            });
            if (!cancelled) {
              setPreviews((prev) => ({ ...prev, [layout.key]: rendered.preview }));
            }
          } catch {
            // A failed preview leaves a labelled card, not a broken gallery.
          }
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load the template catalogue.");
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const locked = brand?.layout_preference || "";

  const setPreference = async (value: string) => {
    if (!brand) return;
    setSaving(value || "rotate");
    try {
      const updated = await api<BrandLite>(`/api/marketing/brands/${brand.id}/`, {
        method: "PATCH",
        body: { layout_preference: value },
      });
      setBrand(updated);
      toast.success(
        value
          ? "Locked — every poster now uses this skeleton."
          : "Unlocked — Scaleezy rotates through the whole catalogue again.",
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the choice.");
    } finally {
      setSaving(null);
    }
  };

  const axes = templates?.axes ?? {};
  const axisEntries = useMemo(() => Object.entries(axes), [axes]);

  // Filter tags come from the patterns themselves, so newly added
  // industry-specific templates grow the filter row with zero UI changes.
  const industryTags = useMemo(
    () => [...new Set(layouts.flatMap((l) => l.industries ?? []))].sort(),
    [layouts],
  );
  const brandIndustry = (brand?.industry ?? "").toLowerCase();
  const suitsBrand = (layout: LayoutInfo) =>
    !!brandIndustry &&
    (layout.industries ?? []).some((tag) => brandIndustry.includes(tag));
  const visible = layouts.filter(
    (l) =>
      industry === "all" ||
      (l.industries ?? []).length === 0 ||
      (l.industries ?? []).includes(industry),
  );

  if (loading) return <Loading rows={3} />;
  if (error) return <Failed message={error} onRetry={() => window.location.reload()} />;

  return (
    <div className="space-y-8">
      <SectionTitle
        label="Templates"
        title="How your posters can look"
        description="Six skeletons, dressed by the style axes below. Every poster picks its own combination unless you lock one."
        action={
          templates ? (
            <Badge variant="secondary" className="text-sm">
              {templates.total.toLocaleString()} templates
            </Badge>
          ) : undefined
        }
      />

      {locked ? (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
            <p className="text-sm text-muted-foreground">
              Every poster is locked to{" "}
              <span className="font-medium text-foreground">
                {layouts.find((l) => l.key === locked)?.display_name ?? locked}
              </span>
              . Unlock to let each poster pick its own look.
            </p>
            <Button
              size="sm"
              variant="outline"
              disabled={saving !== null}
              onClick={() => setPreference("")}
            >
              {saving === "rotate" ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Shuffle className="size-3.5" />
              )}
              Let Scaleezy rotate
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {industryTags.length ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setIndustry("all")}
            className={
              industry === "all"
                ? "rounded-full bg-primary px-3 py-1 text-xs font-medium text-primary-foreground"
                : "rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:border-primary hover:text-foreground"
            }
          >
            All industries
          </button>
          {industryTags.map((tag) => (
            <button
              key={tag}
              type="button"
              onClick={() => setIndustry(tag)}
              className={
                industry === tag
                  ? "rounded-full bg-primary px-3 py-1 text-xs font-medium text-primary-foreground capitalize"
                  : "rounded-full border border-border px-3 py-1 text-xs text-muted-foreground capitalize hover:border-primary hover:text-foreground"
              }
            >
              {tag}
            </button>
          ))}
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        {visible.map((layout) => {
          const isLocked = locked === layout.key;
          return (
            <Card key={layout.key} className={isLocked ? "ring-2 ring-primary" : undefined}>
              <CardContent className="space-y-2 p-3">
                <div className="relative aspect-[4/5] w-full overflow-hidden rounded-md bg-secondary">
                  {previews[layout.key] ? (
                    <img
                      src={previews[layout.key]}
                      alt={`${layout.display_name} rendered with your brand identity`}
                      loading="lazy"
                      decoding="async"
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center">
                      <Loader2 className="size-5 animate-spin text-muted-foreground" />
                    </div>
                  )}
                  {suitsBrand(layout) ? (
                    <Badge className="absolute top-1.5 left-1.5" variant="secondary">
                      Suits your industry
                    </Badge>
                  ) : null}
                </div>
                <div>
                  <p className="text-sm font-medium">{layout.display_name}</p>
                  <p className="text-xs text-muted-foreground">
                    {templates
                      ? `${variantsPerLayout(layout, axes).toLocaleString()} variations`
                      : layout.description}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant={isLocked ? "secondary" : "outline"}
                  className="w-full"
                  disabled={saving !== null || isLocked}
                  onClick={() => setPreference(layout.key)}
                >
                  {saving === layout.key ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : isLocked ? (
                    <>
                      <Check className="size-3.5" /> In use everywhere
                    </>
                  ) : (
                    "Use for every poster"
                  )}
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {axisEntries.length ? (
        <div className="space-y-3">
          <SectionTitle
            title="Style axes"
            description="Each poster combines one option from every axis with a skeleton above — that multiplication is the template count."
          />
          <div className="space-y-2">
            {axisEntries.map(([axis, options]) => (
              <div key={axis} className="flex flex-wrap items-center gap-1.5">
                <span className="w-36 shrink-0 text-xs font-medium text-muted-foreground">
                  {AXIS_LABELS[axis] ?? pretty(axis)}
                </span>
                {options.map((option) => (
                  <Badge key={option} variant="outline" className="font-normal capitalize">
                    {pretty(option)}
                  </Badge>
                ))}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
