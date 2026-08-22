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
  tagline: string;
  ctaKeyword: string;
  brandTone: string;
  instagramHandle: string;
  palette: Record<string, string>;
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
  tagline: "",
  ctaKeyword: "",
  brandTone: "",
  instagramHandle: "",
  palette: {},
  layoutPreference: "agency_column",
};

/** Raw Brand as the API returns it. */
interface BrandDto {
  id: string;
  name: string;
  industry: string;
  tagline: string;
  cta_keyword: string;
  brand_tone: string;
  instagram_handle: string;
  palette: Record<string, string>;
  logo_url: string;
  logo_file_name: string;
  contact_phone: string;
  show_logo_on_posters: boolean;
  show_phone_on_posters: boolean;
  layout_preference: string;
}

const toSettings = (b: BrandDto): BrandSettings => ({
  logoUrl: b.logo_url ?? "",
  logoFileName: b.logo_file_name ?? "",
  showLogoOnPosters: !!b.show_logo_on_posters,
  phoneNumber: b.contact_phone ?? "",
  showPhoneOnPosters: !!b.show_phone_on_posters,
  name: b.name ?? "",
  industry: b.industry ?? "",
  tagline: b.tagline ?? "",
  ctaKeyword: b.cta_keyword ?? "",
  brandTone: b.brand_tone ?? "",
  instagramHandle: b.instagram_handle ?? "",
  palette: b.palette ?? {},
  layoutPreference: b.layout_preference || "agency_column",
});

/** Only the fields the API accepts; logo fields are set via the upload route. */
const toPayload = (patch: Partial<BrandSettings>) => {
  const out: Record<string, unknown> = {};
  if (patch.name !== undefined) out["name"] = patch.name;
  if (patch.industry !== undefined) out["industry"] = patch.industry;
  if (patch.tagline !== undefined) out["tagline"] = patch.tagline;
  if (patch.ctaKeyword !== undefined) out["cta_keyword"] = patch.ctaKeyword;
  if (patch.brandTone !== undefined) out["brand_tone"] = patch.brandTone;
  if (patch.instagramHandle !== undefined) out["instagram_handle"] = patch.instagramHandle;
  if (patch.palette !== undefined) out["palette"] = patch.palette;
  if (patch.phoneNumber !== undefined) out["contact_phone"] = patch.phoneNumber;
  if (patch.showLogoOnPosters !== undefined) out["show_logo_on_posters"] = patch.showLogoOnPosters;
  if (patch.showPhoneOnPosters !== undefined)
    out["show_phone_on_posters"] = patch.showPhoneOnPosters;
  if (patch.layoutPreference !== undefined) out["layout_preference"] = patch.layoutPreference;
  return out;
};

/**
 * Loads the workspace's brand and exposes an optimistic `update`.
 *
 * Text fields are debounced so typing a tagline does not fire a request per
 * keystroke; toggles save immediately. `onSaved` fires after the backend has
 * genuinely accepted a change, so a parent can refresh whatever depends on
 * the brand (readiness, the Brand Brain) without guessing when.
 */
export function useBrandSettings(options: { onSaved?: () => void } = {}) {
  const [settings, setSettings] = useState<BrandSettings>(DEFAULT_BRAND_SETTINGS);
  const [brandId, setBrandId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "pending" | "saving" | "saved" | "failed">(
    "idle",
  );

  const pending = useRef<Partial<BrandSettings>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onSaved = useRef(options.onSaved);
  onSaved.current = options.onSaved;

  useEffect(() => {
    let cancelled = false;
    api<BrandDto>("/api/marketing/brands/current/")
      .then((brand) => {
        if (cancelled) return;
        setBrandId(brand.id);
        setSettings(toSettings(brand));
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load brand.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const flush = useCallback(async ({ keepalive = false }: { keepalive?: boolean } = {}) => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    const patch = pending.current;
    pending.current = {};
    if (Object.keys(patch).length === 0) return;
    if (!brandId) {
      pending.current = { ...patch, ...pending.current };
      setSaveState("pending");
      return;
    }
    setSaving(true);
    setSaveState("saving");
    try {
      const updated = await api<BrandDto>(`/api/marketing/brands/${brandId}/`, {
        method: "PATCH",
        body: toPayload(patch),
        keepalive,
      });
      // New keystrokes may have arrived while this request was in flight.
      // The server response is canonical for the submitted patch, while the
      // still-pending patch remains the user's newest visible intent.
      setSettings({ ...toSettings(updated), ...pending.current });
      setError(null);
      setSaveState(Object.keys(pending.current).length ? "pending" : "saved");
      onSaved.current?.();
    } catch (e) {
      // A failed optimistic save must remain queued. Newer changes win for
      // the same field, and the visible Failed state prevents fake success.
      pending.current = { ...patch, ...pending.current };
      setError(e instanceof Error ? e.message : "Could not save brand.");
      setSaveState("failed");
    } finally {
      setSaving(false);
    }
  }, [brandId]);

  useEffect(() => {
    const persistBeforeLeaving = () => {
      if (Object.keys(pending.current).length > 0) void flush({ keepalive: true });
    };
    window.addEventListener("pagehide", persistBeforeLeaving);
    return () => {
      window.removeEventListener("pagehide", persistBeforeLeaving);
      persistBeforeLeaving();
    };
  }, [flush]);

  const update = useCallback(
    (patch: Partial<BrandSettings>, { immediate = false } = {}) => {
      // Optimistic: the UI reflects the change straight away.
      setSettings((prev) => ({ ...prev, ...patch }));
      pending.current = { ...pending.current, ...patch };
      setSaveState("pending");

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

  return {
    settings,
    update,
    flush,
    uploadLogo,
    removeLogo,
    loading,
    saving,
    saveState,
    error,
    brandId,
  };
}
