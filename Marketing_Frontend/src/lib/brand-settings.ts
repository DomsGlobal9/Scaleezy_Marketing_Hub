import { useEffect, useState } from "react";

/**
 * Brand kit — the logo and contact details that can be stamped onto generated
 * posters. Persisted in localStorage for now; swap `load`/`save` for the
 * workspace settings API once the backend fields exist.
 */
export interface BrandSettings {
  /** Base64 preview held client-side until the logo is uploaded to the bucket. */
  logoDataUrl: string;
  /** Public Supabase URL, set once the backend upload endpoint exists. */
  logoUrl: string;
  logoFileName: string;
  /** Default for the "show logo on poster" option in the generator. */
  showLogoOnPosters: boolean;
  phoneNumber: string;
  /** Default for the "show phone number on poster" option in the generator. */
  showPhoneOnPosters: boolean;
}

export const DEFAULT_BRAND_SETTINGS: BrandSettings = {
  logoDataUrl: "",
  logoUrl: "",
  logoFileName: "",
  showLogoOnPosters: false,
  phoneNumber: "",
  showPhoneOnPosters: false,
};

const STORAGE_KEY = "scaleezy.brandSettings";

export function loadBrandSettings(): BrandSettings {
  if (typeof window === "undefined") return DEFAULT_BRAND_SETTINGS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_BRAND_SETTINGS;
    return { ...DEFAULT_BRAND_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_BRAND_SETTINGS;
  }
}

export function saveBrandSettings(settings: BrandSettings) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Quota or private mode — the in-memory copy still works for this session.
  }
}

/**
 * Reads the brand kit after mount. Deliberately not read during render so the
 * server-rendered HTML and the first client render match.
 */
export function useBrandSettings() {
  const [settings, setSettings] = useState<BrandSettings>(DEFAULT_BRAND_SETTINGS);

  useEffect(() => {
    setSettings(loadBrandSettings());
  }, []);

  const update = (patch: Partial<BrandSettings>) =>
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      saveBrandSettings(next);
      return next;
    });

  return { settings, update };
}
