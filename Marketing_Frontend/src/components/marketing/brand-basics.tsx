/**
 * Brand basics — the identity Scaleezy starts from.
 *
 * Backed by the Brand record through `useBrandSettings`. Every field here is
 * a real column: name, industry, tagline, tone, CTA keyword and Instagram
 * handle feed the Brand Brain's identity and voice sections; the logo, phone
 * and layout default are what the poster engine composes with. Text saves
 * debounced, toggles save immediately, and `onSaved` lets Brand Master refresh
 * readiness once the backend has actually accepted a change.
 */
import { ImagePlus, Loader2, Phone, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useLayoutCatalogue } from "@/components/marketing/poster-studio";
import { SectionTitle } from "@/components/marketing/primitives";
import { useBrandSettings } from "@/lib/brand-settings";
import { cn } from "@/lib/utils";

const MAX_LOGO_BYTES = 2 * 1024 * 1024;

export function BrandBasicsPanel({ onSaved }: { onSaved?: () => void }) {
  const { settings, update, uploadLogo, removeLogo, loading, saving, error } = useBrandSettings({
    ...(onSaved ? { onSaved } : {}),
  });
  const logoInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const { layouts } = useLayoutCatalogue();

  const handleLogoPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // let the same file be re-picked after a remove
    if (!file) return;

    if (!file.type.startsWith("image/")) {
      toast.error("Logo must be an image (PNG, JPG or SVG).");
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      toast.error("Logo must be 2 MB or smaller.");
      return;
    }

    setUploading(true);
    try {
      // Uploaded straight to the bucket — the URL is only stored once the
      // upload genuinely succeeded.
      await uploadLogo(file);
      toast.success("Logo uploaded.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Logo upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleRemoveLogo = async () => {
    try {
      await removeLogo();
      toast("Logo removed.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not remove the logo.");
    }
  };

  const hasLogo = !!settings.logoUrl;

  return (
    <div className="space-y-8">
      {error ? (
        <p className="rounded-xl border border-destructive/30 bg-destructive/8 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <section>
        <SectionTitle
          title="Identity"
          description="What the brand is called and how it speaks. Saved as you type."
          action={
            saving ? (
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" /> Saving…
              </span>
            ) : null
          }
        />
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Field label="Brand name">
            <Input
              placeholder="Acme Coffee"
              value={settings.name}
              disabled={loading}
              onChange={(e) => update({ name: e.target.value })}
            />
          </Field>
          <Field label="Industry / category">
            <Input
              placeholder="Specialty coffee"
              value={settings.industry}
              disabled={loading}
              onChange={(e) => update({ industry: e.target.value })}
            />
          </Field>
          <Field label="Tagline / positioning line" className="sm:col-span-2">
            <Input
              placeholder="Roasted this week"
              value={settings.tagline}
              disabled={loading}
              onChange={(e) => update({ tagline: e.target.value })}
            />
          </Field>
          <Field
            label="Brand tone"
            hint="How generated copy should sound. A short phrase is enough."
            className="sm:col-span-2"
          >
            <Input
              placeholder="Warm, unfussy, expert without the jargon"
              value={settings.brandTone}
              disabled={loading}
              onChange={(e) => update({ brandTone: e.target.value })}
            />
          </Field>
          <Field label="CTA keyword" hint="The action your posts push toward.">
            <Input
              placeholder="Order now"
              value={settings.ctaKeyword}
              disabled={loading}
              onChange={(e) => update({ ctaKeyword: e.target.value })}
            />
          </Field>
          <Field label="Instagram handle">
            <Input
              placeholder="@acmecoffee"
              value={settings.instagramHandle}
              disabled={loading}
              onChange={(e) => update({ instagramHandle: e.target.value })}
            />
          </Field>
        </div>
      </section>

      <section>
        <SectionTitle
          title="Logo"
          description="Used on generated posters and in Brand Master. PNG with a transparent background works best."
        />
        <div className="mt-4 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-4">
          <div className="grid size-20 shrink-0 place-items-center overflow-hidden rounded-xl border border-border bg-secondary/40">
            {hasLogo ? (
              <img
                src={settings.logoUrl}
                alt="Brand logo"
                className="size-full object-contain p-2"
              />
            ) : (
              <ImagePlus className="size-6 text-muted-foreground" />
            )}
          </div>
          <div className="min-w-0">
            {hasLogo ? (
              <p className="truncate text-sm font-medium text-foreground">
                {settings.logoFileName || "Brand logo"}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">No logo uploaded yet.</p>
            )}
            <div className="mt-2 flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={loading || uploading}
                onClick={() => logoInputRef.current?.click()}
              >
                <ImagePlus className="size-4" />
                {uploading ? "Uploading…" : hasLogo ? "Replace" : "Upload logo"}
              </Button>
              {hasLogo ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={handleRemoveLogo}
                >
                  <Trash2 className="size-4" /> Remove
                </Button>
              ) : null}
            </div>
          </div>
        </div>
        <input
          ref={logoInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={handleLogoPick}
        />
      </section>

      <section>
        <SectionTitle
          title="Poster defaults"
          description="What the layout engine stamps onto composed posters. Each can be overridden per poster."
        />
        <div className="mt-4 grid gap-4">
          <Toggle
            label="Show logo on generated posters"
            hint={hasLogo ? undefined : "Upload a logo first."}
            checked={settings.showLogoOnPosters}
            disabled={!hasLogo}
            onChange={(v) => update({ showLogoOnPosters: v }, { immediate: true })}
          />
          <Field
            label="Contact phone number"
            hint="Optionally printed at the bottom of a poster after it is generated."
          >
            <div className="relative">
              <Phone className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="tel"
                className="pl-9"
                placeholder="+91 98765 43210"
                value={settings.phoneNumber}
                disabled={loading}
                onChange={(e) => update({ phoneNumber: e.target.value })}
              />
            </div>
          </Field>
          <Toggle
            label="Show phone number on posters"
            hint={settings.phoneNumber.trim() ? undefined : "Add a phone number first."}
            checked={settings.showPhoneOnPosters}
            disabled={!settings.phoneNumber.trim()}
            onChange={(v) => update({ showPhoneOnPosters: v }, { immediate: true })}
          />
          <div>
            <Label className="text-xs tracking-wide uppercase">Default poster layout</Label>
            {layouts.length === 0 ? (
              <p className="mt-1.5 text-xs text-muted-foreground">
                Layout catalogue unavailable right now.
              </p>
            ) : (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {layouts.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    title={option.description}
                    onClick={() => update({ layoutPreference: option.key }, { immediate: true })}
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-xs transition-colors",
                      settings.layoutPreference === option.key
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {option.display_name}
                  </button>
                ))}
              </div>
            )}
            <p className="mt-1.5 text-xs text-muted-foreground">
              Used whenever a poster is composed from your brand rather than generated. Can be
              changed per poster in Review.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}

function Field({
  label,
  hint,
  className,
  children,
}: {
  label: string;
  hint?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={className}>
      <Label className="text-xs tracking-wide uppercase">{label}</Label>
      <div className="mt-1.5">{children}</div>
      {hint ? <p className="mt-1.5 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Toggle({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  hint?: string | undefined;
  checked: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
      <div className="min-w-0">
        <Label className="text-sm font-normal">{label}</Label>
        {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
      </div>
      <Switch checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </div>
  );
}
