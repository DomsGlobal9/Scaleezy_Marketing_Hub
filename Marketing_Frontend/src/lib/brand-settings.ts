import { useCallback, useEffect, useRef, useState } from "react";

import { api, apiFetch } from "@/lib/api";

/**
 * Brand basics — identity, logo and the poster defaults the layout engine
 * reads.
 *
 * Server-backed. This used to live in localStorage, which meant the brand kit
 * was lost on a browser change and invisible to the server that actually
 * renders the posters. The shape below is kept stable for existing callers;
 * it is a view over the Brand record.
 */

/** One row of `products_services`. The API normalises to exactly these keys. */
export interface ProductService {
  name: string;
  description: string;
}

export interface BrandSettings {
  /** Public Supabase URL of the uploaded logo. */
  logoUrl: string;
  logoFileName: string;
  /** Default for the "show logo on poster" option in the generator. */
  showLogoOnPosters: boolean;
  phoneNumber: string;
  /** Default for the "show phone number on poster" option in the generator. */
  showPhoneOnPosters: boolean;

  // Wider brand identity, editable in Brand Master.
  name: string;
  industry: string;
  website: string;
  location: string;
  tagline: string;
  ctaKeyword: string;
  brandTone: string;
  instagramHandle: string;
  /** First-party prose. Compiles into the brain's identity/audience sections. */
  description: string;
  audience: string;
  palette: Record<string, string>;
  fonts: Record<string, string>;
  competitors: string[];
  productsServices: ProductService[];
  socialLinks: Record<string, string>;
  /** Default layout the server composes posters with. */
  layoutPreference: string;
}

export const DEFAULT_BRAND_SETTINGS: BrandSettings = {
  logoUrl: "",
  logoFileName: "",
  showLogoOnPosters: false,
  phoneNumber: "",
  showPhoneOnPosters: false,
  name: "",
  industry: "",
  website: "",
  location: "",
  tagline: "",
  ctaKeyword: "",
  brandTone: "",
  instagramHandle: "",
  description: "",
  audience: "",
  palette: {},
  fonts: {},
  competitors: [],
  productsServices: [],
  socialLinks: {},
  layoutPreference: "agency_column",
};

/** Raw Brand as the API returns it. */
interface BrandDto {
  id: string;
  name: string;
  industry: string;
  website: string;
  location: string;
  tagline: string;
  cta_keyword: string;
  brand_tone: string;
  instagram_handle: string;
  description: string;
  audience: string;
  palette: Record<string, string>;
  fonts: Record<string, string>;
  competitors: unknown[];
  products_services: unknown[];
  social_links: Record<string, unknown>;
  logo_url: string;
  logo_file_name: string;
  contact_phone: string;
  show_logo_on_posters: boolean;
  show_phone_on_posters: boolean;
  layout_preference: string;
}

/**
 * These three are JSONFields, so the column holds whatever any past client
 * wrote — including rows the current editors cannot render. Coercing on the
 * way in means a legacy blob shows up as an editable value instead of
 * crashing the panel that displays it.
 */
const toStringList = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.map((entry) => (typeof entry === "string" ? entry : String(entry ?? ""))).filter(Boolean)
    : [];

const toProducts = (value: unknown): ProductService[] =>
  Array.isArray(value)
    ? value.flatMap((entry) => {
        if (!entry || typeof entry !== "object") return [];
        const row = entry as { name?: unknown; description?: unknown };
        const name = typeof row.name === "string" ? row.name : "";
        if (!name.trim()) return [];
        return [{ name, description: typeof row.description === "string" ? row.description : "" }];
      })
    : [];

const toStringMap = (value: unknown): Record<string, string> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const out: Record<string, string> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    if (typeof raw === "string") out[key] = raw;
  }
  return out;
};

const toSettings = (b: BrandDto): BrandSettings => ({
  logoUrl: b.logo_url ?? "",
  logoFileName: b.logo_file_name ?? "",
  showLogoOnPosters: !!b.show_logo_on_posters,
  phoneNumber: b.contact_phone ?? "",
  showPhoneOnPosters: !!b.show_phone_on_posters,
  name: b.name ?? "",
  industry: b.industry ?? "",
  website: b.website ?? "",
  location: b.location ?? "",
  tagline: b.tagline ?? "",
  ctaKeyword: b.cta_keyword ?? "",
  brandTone: b.brand_tone ?? "",
  instagramHandle: b.instagram_handle ?? "",
  description: b.description ?? "",
  audience: b.audience ?? "",
  palette: toStringMap(b.palette),
  fonts: toStringMap(b.fonts),
  competitors: toStringList(b.competitors),
  productsServices: toProducts(b.products_services),
  socialLinks: toStringMap(b.social_links),
  layoutPreference: b.layout_preference || "agency_column",
});

/** Only the fields the API accepts; logo fields are set via the upload route. */
const toPayload = (patch: Partial<BrandSettings>) => {
  const out: Record<string, unknown> = {};
  if (patch.name !== undefined) out["name"] = patch.name;
  if (patch.industry !== undefined) out["industry"] = patch.industry;
  if (patch.website !== undefined) out["website"] = patch.website;
  if (patch.location !== undefined) out["location"] = patch.location;
  if (patch.tagline !== undefined) out["tagline"] = patch.tagline;
  if (patch.ctaKeyword !== undefined) out["cta_keyword"] = patch.ctaKeyword;
  if (patch.brandTone !== undefined) out["brand_tone"] = patch.brandTone;
  if (patch.instagramHandle !== undefined) out["instagram_handle"] = patch.instagramHandle;
  if (patch.description !== undefined) out["description"] = patch.description;
  if (patch.audience !== undefined) out["audience"] = patch.audience;
  if (patch.palette !== undefined) out["palette"] = patch.palette;
  if (patch.fonts !== undefined) out["fonts"] = patch.fonts;
  if (patch.competitors !== undefined) out["competitors"] = patch.competitors;
  // Sent as {name, description} only. The serializer rebuilds the list and
  // discards anything else, so an extra key here would vanish on the way in
  // and read back missing — never use one as a React list key.
  if (patch.productsServices !== undefined) {
    out["products_services"] = patch.productsServices.map((row) => ({
      name: row.name,
      description: row.description,
    }));
  }
  if (patch.socialLinks !== undefined) out["social_links"] = patch.socialLinks;
  if (patch.phoneNumber !== undefined) out["contact_phone"] = patch.phoneNumber;
  if (patch.showLogoOnPosters !== undefined) out["show_logo_on_posters"] = patch.showLogoOnPosters;
  if (patch.showPhoneOnPosters !== undefined)
    out["show_phone_on_posters"] = patch.showPhoneOnPosters;
  if (patch.layoutPreference !== undefined) out["layout_preference"] = patch.layoutPreference;
  return out;
};

export interface UseBrandSettingsOptions {
  onSaved?: () => void;
  /**
   * Which brand to edit. Omitted means the workspace default through
   * `/brands/current/` — the Brand Master behaviour. A string targets that
   * brand, which is how the Add Client wizard edits the brand it just created
   * rather than whichever one `/current/` would auto-create. `null` means "the
   * caller does not know yet": nothing loads and the panel stays disabled,
   * because saving before the target is known would write to the wrong brand.
   */
  brandId?: string | null;
}

/**
 * Loads a brand and exposes an optimistic `update`.
 *
 * Text fields are debounced so typing a tagline does not fire a request per
 * keystroke; toggles save immediately. `onSaved` fires after the backend has
 * genuinely accepted a change, so a parent can refresh whatever depends on
 * the brand (readiness, the Brand Brain) without guessing when.
 */
export function useBrandSettings(options: UseBrandSettingsOptions = {}) {
  const target = "brandId" in options ? options.brandId : undefined;

  const [settings, setSettings] = useState<BrandSettings>(DEFAULT_BRAND_SETTINGS);
  const [brandId, setBrandId] = useState<string | null>(typeof target === "string" ? target : null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pending = useRef<Partial<BrandSettings>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onSaved = useRef(options.onSaved);
  onSaved.current = options.onSaved;

  useEffect(() => {
    // Explicit null: the caller is still resolving which brand this is. Staying
    // in the loading state keeps every field disabled, so nothing can be typed
    // into a form that has nowhere to save it.
    if (target === null) {
      setLoading(true);
      return;
    }

    let cancelled = false;
    setLoading(true);
    api<BrandDto>(target ? `/api/marketing/brands/${target}/` : "/api/marketing/brands/current/")
      .then((brand) => {
        if (cancelled) return;
        setBrandId(brand.id);
        setSettings(toSettings(brand));
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load brand.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [target]);

  const flush = useCallback(async () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    // Kept until the request is actually going out. Clearing first meant a
    // flush that arrived before the brand id resolved threw the edit away.
    if (!brandId || Object.keys(pending.current).length === 0) return;
    const patch = pending.current;
    pending.current = {};
    setSaving(true);
    try {
      const updated = await api<BrandDto>(`/api/marketing/brands/${brandId}/`, {
        method: "PATCH",
        body: toPayload(patch),
      });
      setSettings(toSettings(updated));
      setError(null);
      onSaved.current?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save brand.");
    } finally {
      setSaving(false);
    }
  }, [brandId]);

  const update = useCallback(
    (patch: Partial<BrandSettings>, { immediate = false } = {}) => {
      // Optimistic: the UI reflects the change straight away.
      setSettings((prev) => ({ ...prev, ...patch }));
      pending.current = { ...pending.current, ...patch };

      if (timer.current) clearTimeout(timer.current);
      if (immediate) {
        void flush();
      } else {
        timer.current = setTimeout(() => void flush(), 600);
      }
    },
    [flush],
  );

  const uploadLogo = useCallback(
    async (file: File) => {
      if (!brandId) throw new Error("Brand is still loading.");
      const form = new FormData();
      form.append("file", file);
      // apiFetch, not api(): FormData must pass through with no Content-Type
      // so the browser writes the multipart boundary.
      const res = await apiFetch(`/api/marketing/brands/${brandId}/logo/`, {
        method: "POST",
        body: form,
      });
      const json = await res.json().catch(() => null);
      if (!res.ok || json?.success === false) {
        throw new Error(json?.error?.message || json?.message || "Logo upload failed.");
      }
      setSettings(toSettings(json.data as BrandDto));
      onSaved.current?.();
    },
    [brandId],
  );

  const removeLogo = useCallback(async () => {
    if (!brandId) return;
    const res = await apiFetch(`/api/marketing/brands/${brandId}/logo/`, { method: "DELETE" });
    const json = await res.json().catch(() => null);
    if (!res.ok || json?.success === false) {
      throw new Error(json?.error?.message || json?.message || "Could not remove the logo.");
    }
    if (json?.data) setSettings(toSettings(json.data as BrandDto));
    onSaved.current?.();
  }, [brandId]);

  return { settings, update, flush, uploadLogo, removeLogo, loading, saving, error, brandId };
}

/**
 * One loaded brand, passed to the field sections.
 *
 * The sections are composed differently by Brand Master and by the onboarding
 * wizard, but both must write through a single hook instance — two would each
 * hold their own debounce timer and the later flush would overwrite the
 * earlier one's optimistic state with a stale record.
 */
export type BrandEditor = ReturnType<typeof useBrandSettings>;
