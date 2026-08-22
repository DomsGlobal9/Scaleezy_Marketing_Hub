/**
 * Brand basics — the identity Scaleezy starts from.
 *
 * Backed by the Brand record through `useBrandSettings`. Every field here is a
 * real column, including the three that were API-writable but had no editor at
 * all until now: palette, fonts and competitors. Text saves debounced, toggles
 * and pickers save immediately, and `onSaved` lets Brand Master refresh
 * readiness once the backend has actually accepted a change.
 *
 * The sections are exported individually because the onboarding wizard splits
 * the same fields across its steps. It passes its own `useBrandSettings`
 * instance so the wizard and this panel never hold two competing debounces
 * over one brand.
 */
import { ImagePlus, Loader2, Phone, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  FONT_ROLES,
  Field,
  KeyValueEditor,
  PaletteEditor,
  SOCIAL_PLATFORMS,
  TagListEditor,
  Toggle,
} from "@/components/marketing/brand-field-editors";
import { useLayoutCatalogue } from "@/components/marketing/poster-studio";
import { SectionTitle } from "@/components/marketing/primitives";
import { useBrandSettings, type BrandEditor } from "@/lib/brand-settings";
import { cn } from "@/lib/utils";

const MAX_LOGO_BYTES = 2 * 1024 * 1024;

export function SavingHint({ saving }: { saving: boolean }) {
  if (!saving) return null;
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" /> Saving…
    </span>
  );
}

export function BrandError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p className="rounded-xl border border-destructive/30 bg-destructive/8 px-3 py-2 text-sm text-destructive">
      {error}
    </p>
  );
}

/* ------------------------------------------------------------ who they are */

export function ClientBasicsSection({ editor }: { editor: BrandEditor }) {
  const { settings, update, loading, saving } = editor;
  return (
    <section>
      <SectionTitle
        title="Client basics"
        description="Who this brand is and where it trades. Saved as you type."
        action={<SavingHint saving={saving} />}
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
        <Field label="Website" hint="Used as context, not fetched.">
          <Input
            type="url"
            placeholder="https://acmecoffee.com"
            value={settings.website}
            disabled={loading}
            onChange={(e) => update({ website: e.target.value })}
          />
        </Field>
        <Field label="Location" hint="Where the brand operates or sells.">
          <Input
            placeholder="Bengaluru, India"
            value={settings.location}
            disabled={loading}
            onChange={(e) => update({ location: e.target.value })}
          />
        </Field>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------- how it talks */

export function VoiceSection({ editor }: { editor: BrandEditor }) {
  const { settings, update, loading, saving } = editor;
  return (
    <section>
      <SectionTitle
        title="Voice"
        description="How generated copy should sound, and what it should push toward."
        action={<SavingHint saving={saving} />}
      />
      <div className="mt-4 grid gap-5 sm:grid-cols-2">
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
          hint="A short phrase is enough."
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
  );
}

/* -------------------------------------------------------------------- logo */

export function LogoSection({ editor }: { editor: BrandEditor }) {
  const { settings, uploadLogo, removeLogo, loading } = editor;
  const logoInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const hasLogo = !!settings.logoUrl;

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

  return (
    <section>
      <SectionTitle
        title="Logo"
        description="Used on generated posters and in Brand Master. PNG with a transparent background works best."
      />
      <div className="mt-4 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-4">
        <div className="grid size-20 shrink-0 place-items-center overflow-hidden rounded-xl border border-border bg-secondary/40">
          {hasLogo ? (
            <img src={settings.logoUrl} alt="Brand logo" className="size-full object-contain p-2" />
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
            <p className="text-sm text-muted-foreground">
              No logo uploaded yet. Add one so posters can carry it.
            </p>
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
  );
}

/* -------------------------------------------------------- visual identity */

export function VisualIdentitySection({ editor }: { editor: BrandEditor }) {
  const { settings, update, loading, saving } = editor;
  return (
    <section>
      <SectionTitle
        title="Visual identity"
        description="The palette and type the poster engine composes with, and the brain reports as visual language."
        action={<SavingHint saving={saving} />}
      />
      <div className="mt-4 space-y-6">
        <Field label="Colour palette">
          <PaletteEditor
            value={settings.palette}
            disabled={loading}
            onChange={(palette) => update({ palette })}
          />
        </Field>
        <Field label="Fonts" hint="Named for the renderer, not loaded from here.">
          <KeyValueEditor
            value={settings.fonts}
            disabled={loading}
            keyLabel="Role, e.g. primary"
            valuePlaceholder="DM Sans"
            suggestions={FONT_ROLES}
            emptyHint="No fonts set. Add a primary typeface to start."
            onChange={(fonts) => update({ fonts })}
          />
        </Field>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ market context */

export function MarketSection({ editor }: { editor: BrandEditor }) {
  const { settings, update, loading, saving } = editor;
  return (
    <section>
      <SectionTitle
        title="Market context"
        description="Who this brand is measured against, and where it already publishes."
        action={<SavingHint saving={saving} />}
      />
      <div className="mt-4 space-y-6">
        <Field
          label="Competitors"
          hint="Compiled into the brain's positioning so generation can differentiate rather than echo."
        >
          <TagListEditor
            value={settings.competitors}
            disabled={loading}
            placeholder="Competitor name"
            emptyHint="No competitors listed. Name a few and Scaleezy will avoid sounding like them."
            onChange={(competitors) => update({ competitors })}
          />
        </Field>
        <Field
          label="Social links"
          hint="Stored as given — a link without https:// is accepted but will not open as one."
        >
          <KeyValueEditor
            value={settings.socialLinks}
            disabled={loading}
            keyLabel="Platform"
            valuePlaceholder="https://instagram.com/acmecoffee"
            suggestions={SOCIAL_PLATFORMS}
            emptyHint="No links yet. Add the profiles this brand already posts to."
            onChange={(socialLinks) => update({ socialLinks })}
          />
        </Field>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------- poster defaults */

export function PosterDefaultsSection({ editor }: { editor: BrandEditor }) {
  const { settings, update, loading } = editor;
  const { layouts } = useLayoutCatalogue();
  const hasLogo = !!settings.logoUrl;

  return (
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
            Used whenever a poster is composed from your brand rather than generated. Can be changed
            per poster in Review.
          </p>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------- panel */

export function BrandBasicsPanel({
  onSaved,
  brandId,
}: {
  onSaved?: () => void;
  brandId?: string | null;
}) {
  const editor = useBrandSettings({
    ...(onSaved ? { onSaved } : {}),
    ...(brandId !== undefined ? { brandId } : {}),
  });

  return (
    <div className="space-y-8">
      <BrandError error={editor.error} />
      <ClientBasicsSection editor={editor} />
      <VoiceSection editor={editor} />
      <LogoSection editor={editor} />
      <VisualIdentitySection editor={editor} />
      <MarketSection editor={editor} />
      <PosterDefaultsSection editor={editor} />
    </div>
  );
}
