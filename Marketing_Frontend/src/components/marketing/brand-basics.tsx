/**
 * Brand basics — the identity Scaleezy starts from.
 *
 * Backed by the Brand record through `useBrandSettings`. Every field here is a
 * real column, including the three that were API-writable but had no editor at
 * all until now: palette, fonts and competitors. Text saves debounced, toggles
 * and pickers save immediately, and `onSaved` lets Brand Master refresh
 * readiness once the backend has actually accepted a change.
 *
 * Sections only, no panel: `BrandProfilePanel` (products-audience-panel.tsx)
 * composes them with the products and audience sections into the single Brand
 * profile form, over one shared `useBrandSettings` instance so nothing ever
 * holds two competing debounces over one brand.
 */
import { AlertCircle, CheckCircle2, ImagePlus, Loader2, Phone, Save, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Field,
  KeyValueEditor,
  PaletteEditor,
  TagListEditor,
  Toggle,
} from "@/components/marketing/brand-field-editors";
import { SectionTitle } from "@/components/marketing/primitives";
import type { BrandEditor } from "@/lib/brand-settings";
import { cn } from "@/lib/utils";

const MAX_LOGO_BYTES = 2 * 1024 * 1024;
const FONT_ROLES = ["primary", "secondary"];
const SOCIAL_PLATFORMS = [
  "instagram",
  "facebook",
  "linkedin",
  "youtube",
  "x",
  "tiktok",
  "pinterest",
];

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
    <p
      role="alert"
      className="rounded-xl border border-destructive/30 bg-destructive/8 px-3 py-2 text-sm text-destructive"
    >
      {error}
    </p>
  );
}

/** One explicit commit point for every Brand Master editing panel. */
export function BrandSaveControl({
  editor,
  extraDirty = false,
  blockedReason,
}: {
  editor: BrandEditor;
  /** A local draft that cannot enter the shared save queue yet. */
  extraDirty?: boolean;
  blockedReason?: string | null;
}) {
  const hasUnsavedWork = editor.dirty || extraDirty;
  const canSave = editor.dirty && !editor.loading && !editor.saving && !!editor.brandId;

  let message = "No unsaved changes.";
  let tone = "text-muted-foreground";
  let icon = <CheckCircle2 className="size-4" />;

  if (editor.loading) {
    message = "Loading brand…";
    icon = <Loader2 className="size-4 animate-spin" />;
  } else if (editor.saving) {
    message = "Saving changes…";
    icon = <Loader2 className="size-4 animate-spin" />;
  } else if (editor.saveState === "failed") {
    message = editor.error || "Save failed. Your changes are still here — try again.";
    tone = "text-destructive";
    icon = <AlertCircle className="size-4" />;
  } else if (blockedReason) {
    message = editor.dirty ? `Unsaved changes. ${blockedReason}` : blockedReason;
    tone = "text-amber-700 dark:text-amber-400";
    icon = <AlertCircle className="size-4" />;
  } else if (hasUnsavedWork) {
    message = "Unsaved changes. Autosave will run shortly, or save now.";
    tone = "text-amber-700 dark:text-amber-400";
    icon = <AlertCircle className="size-4" />;
  } else if (editor.saveState === "saved") {
    message = "All changes saved.";
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3">
      <span aria-live="polite" className={cn("flex min-w-0 items-center gap-2 text-sm", tone)}>
        {icon}
        <span>{message}</span>
      </span>
      <Button type="button" size="sm" disabled={!canSave} onClick={() => void editor.flush()}>
        {editor.saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
        {editor.saving ? "Saving…" : "Save changes"}
      </Button>
    </div>
  );
}

/* ------------------------------------------------------------ who they are */

export function ClientBasicsSection({ editor }: { editor: BrandEditor }) {
  const { settings, update, loading, saving } = editor;
  return (
    <section>
      <SectionTitle
        title="Your brand"
        description="The basics. Everything saves as you type."
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
        <Field label="What you do" hint="Your industry, in your words.">
          <Input
            placeholder="Specialty coffee"
            value={settings.industry}
            disabled={loading}
            onChange={(e) => update({ industry: e.target.value })}
          />
        </Field>
        <Field label="Website" hint="Optional.">
          <Input
            type="url"
            placeholder="https://acmecoffee.com"
            value={settings.website}
            disabled={loading}
            onChange={(e) => update({ website: e.target.value })}
          />
        </Field>
        <Field label="Where you are" hint="The city or region you sell in.">
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

/* --------------------------------------------------- administrative details */

export function AdminDetailsSection({ editor }: { editor: BrandEditor }) {
  const { settings, update, loading } = editor;
  return (
    <section>
      <SectionTitle
        title="Business details"
        description="For Scaleezy's records. None of this appears in your posts."
      />
      <div className="mt-4 grid gap-5 sm:grid-cols-2">
        <Field label="Registered business name" hint="Optional.">
          <Input
            aria-label="Legal business name"
            maxLength={255}
            placeholder="Acme Beverages Pvt Ltd"
            value={settings.legalName}
            disabled={loading}
            onChange={(e) => update({ legalName: e.target.value })}
          />
        </Field>
        <Field label="Contact person" hint="Optional.">
          <Input
            aria-label="Contact person"
            maxLength={150}
            placeholder="Priya Sharma"
            value={settings.contactPerson}
            disabled={loading}
            onChange={(e) => update({ contactPerson: e.target.value })}
          />
        </Field>
        <Field label="Instagram handle" hint="Optional.">
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

/* ------------------------------------------------------------- how it talks */

export function VoiceSection({ editor }: { editor: BrandEditor }) {
  const { settings, update, loading, saving } = editor;
  return (
    <section>
      <SectionTitle
        title="How you sound"
        description="Captions and headlines follow this."
        action={<SavingHint saving={saving} />}
      />
      <div className="mt-4 grid gap-5 sm:grid-cols-2">
        <Field label="Tagline" hint="Optional." className="sm:col-span-2">
          <Input
            placeholder="Roasted this week"
            value={settings.tagline}
            disabled={loading}
            onChange={(e) => update({ tagline: e.target.value })}
          />
        </Field>
        <Field
          label="Tone"
          hint="A few words is enough — warm, playful, no-nonsense."
          className="sm:col-span-2"
        >
          <Input
            placeholder="Warm, unfussy, expert without the jargon"
            value={settings.brandTone}
            disabled={loading}
            onChange={(e) => update({ brandTone: e.target.value })}
          />
        </Field>
        <Field
          label="What should people do?"
          hint="The one action your posts ask for."
          className="sm:col-span-2"
        >
          <Input
            placeholder="Order now · Visit the store · DM us"
            value={settings.ctaKeyword}
            disabled={loading}
            onChange={(e) => update({ ctaKeyword: e.target.value })}
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
        description="Goes on every poster. A PNG with a transparent background looks best."
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
            <p className="text-sm text-muted-foreground">No logo yet.</p>
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
        title="Colours and fonts"
        description="Posters are composed with these. Leave fonts empty and Scaleezy picks ones that suit the brand."
        action={<SavingHint saving={saving} />}
      />
      <div className="mt-4 space-y-6">
        <Field label="Colours">
          <PaletteEditor
            value={settings.palette}
            disabled={loading}
            onChange={(palette) => update({ palette })}
          />
        </Field>
        <Field label="Fonts" hint="Optional. Type a font name, e.g. DM Sans.">
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
        title="Competitors and links"
        description="Optional."
        action={<SavingHint saving={saving} />}
      />
      <div className="mt-4 space-y-6">
        <Field label="Brands you do not want to sound like">
          <TagListEditor
            value={settings.competitors}
            disabled={loading}
            placeholder="Competitor name"
            emptyHint="Name a few and Scaleezy steers clear of their style."
            onChange={(competitors) => update({ competitors })}
          />
        </Field>
        <Field label="Where you already post" hint="Links to your profiles.">
          <KeyValueEditor
            value={settings.socialLinks}
            disabled={loading}
            keyLabel="Platform"
            valuePlaceholder="https://instagram.com/acmecoffee"
            suggestions={SOCIAL_PLATFORMS}
            emptyHint="No links yet."
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
  const hasLogo = !!settings.logoUrl;

  return (
    <section>
      <SectionTitle
        title="On every poster"
        description="You can still turn these off for any single poster."
      />
      <div className="mt-4 grid gap-4">
        <Toggle
          label="Show the logo"
          hint={hasLogo ? undefined : "Upload a logo first."}
          checked={settings.showLogoOnPosters}
          disabled={!hasLogo}
          onChange={(v) => update({ showLogoOnPosters: v }, { immediate: true })}
        />
        <Field label="Phone number" hint="Printed at the bottom when the switch below is on.">
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
          label="Show the phone number"
          hint={settings.phoneNumber.trim() ? undefined : "Add a phone number first."}
          checked={settings.showPhoneOnPosters}
          disabled={!settings.phoneNumber.trim()}
          onChange={(v) => update({ showPhoneOnPosters: v }, { immediate: true })}
        />
      </div>
    </section>
  );
}
