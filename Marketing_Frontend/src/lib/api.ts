/**
 * The single place the frontend talks to the backend.
 *
 * Replaces ~24 hand-rolled fetch calls that each duplicated URL building,
 * response unwrapping and error handling in three mutually inconsistent ways.
 */
import { clearSession, readSession, writeSession } from "@/lib/auth";

/**
 * Read once. Every previous call site did `VITE_API_URL + "/api/..."`, which
 * bakes in the literal string "undefined" when the variable is missing at build
 * time — producing a silent request to /undefined/api/... instead of an error.
 */
const BASE = (import.meta.env["VITE_API_URL"] ?? "").replace(/\/+$/, "");

const REFRESH_PATH = "/api/auth/refresh/";

export class ApiError extends Error {
  status: number;
  code: string | undefined;
  payload: unknown;

  constructor(status: number, message: string, code?: string, payload?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

export interface ApiOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Skip the Authorization header and the 401 refresh/redirect handling. */
  public?: boolean;
  /** Internal: marks a replayed request so it can never retry twice. */
  _retried?: boolean;
}

function buildUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  if (!BASE) {
    throw new ApiError(
      0,
      "VITE_API_URL is not configured. Set it in Marketing_Frontend/.env and restart the dev server.",
      "NO_API_BASE",
    );
  }
  return `${BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

/**
 * Bodies the browser must serialise itself. FormData in particular has to keep
 * its own Content-Type so the multipart boundary is generated — setting the
 * header manually makes Django's parser reject the upload.
 */
function isPassthroughBody(body: unknown): boolean {
  return (
    (typeof FormData !== "undefined" && body instanceof FormData) ||
    (typeof Blob !== "undefined" && body instanceof Blob) ||
    (typeof ArrayBuffer !== "undefined" && body instanceof ArrayBuffer) ||
    (typeof URLSearchParams !== "undefined" && body instanceof URLSearchParams) ||
    typeof body === "string"
  );
}

// ---------------------------------------------------------------------------
// Single-flight refresh
// ---------------------------------------------------------------------------

/**
 * Concurrent 401s must not each POST to /api/auth/refresh/. With
 * ROTATE_REFRESH_TOKENS enabled, parallel refreshes fork the session into two
 * chains; once the blacklist is enabled they would log the user out at random.
 * The first 401 owns the refresh, everyone else awaits the same promise.
 */
let inflightRefresh: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const session = readSession();
  if (!session?.refresh) return null;

  const res = await fetch(buildUrl(REFRESH_PATH), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh: session.refresh }),
  });

  if (!res.ok) return null;

  const json = await res.json().catch(() => null);
  // Responses come wrapped in the APIResponse envelope: {success, data:{...}}.
  const data = (json?.data ?? json) as { access?: string; refresh?: string } | null;
  if (!data?.access) return null;

  // Rotation is on, so the response carries a NEW refresh token. Dropping it
  // would strand the session on a token the server has already rotated past.
  writeSession({
    access: data.access,
    refresh: data.refresh ?? session.refresh,
  });
  return data.access;
}

function runRefresh(): Promise<string | null> {
  if (!inflightRefresh) {
    inflightRefresh = refreshAccessToken().finally(() => {
      // Always cleared, so one failure cannot poison later attempts.
      inflightRefresh = null;
    });
  }
  return inflightRefresh;
}

/** Called when refresh fails, so the route guard can bounce to /login. */
let onSessionExpired: (() => void) | null = null;
export function setSessionExpiredHandler(fn: (() => void) | null) {
  onSessionExpired = fn;
}

// ---------------------------------------------------------------------------
// Response unwrapping
// ---------------------------------------------------------------------------

/**
 * The backend speaks three dialects: a bare array, the {success, data, message}
 * envelope, and plain keyed objects. Callers should not have to know which.
 */
function unwrap<T>(json: unknown): T {
  if (json && typeof json === "object" && !Array.isArray(json) && "success" in json) {
    const envelope = json as { success: boolean; data?: unknown; message?: string };
    return (envelope.data ?? envelope) as T;
  }
  return json as T;
}

function errorFrom(status: number, json: unknown, fallback: string): ApiError {
  if (json && typeof json === "object") {
    const e = json as {
      message?: string;
      detail?: string;
      error?: { code?: string; message?: string };
    };
    const message = e.error?.message || e.message || e.detail || fallback;
    return new ApiError(status, message, e.error?.code, json);
  }
  return new ApiError(status, fallback, undefined, json);
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

export async function api<T = unknown>(path: string, options: ApiOptions = {}): Promise<T> {
  const { body, public: isPublic, _retried, headers, ...rest } = options;

  const finalHeaders = new Headers(headers as HeadersInit | undefined);

  let finalBody: BodyInit | undefined;
  if (body !== undefined && body !== null) {
    if (isPassthroughBody(body)) {
      finalBody = body as BodyInit;
    } else {
      finalBody = JSON.stringify(body);
      if (!finalHeaders.has("Content-Type")) {
        finalHeaders.set("Content-Type", "application/json");
      }
    }
  }

  const token = readSession()?.access;
  // Public calls still send the token when one exists — the OAuth callbacks
  // benefit from it — but are never redirected away on 401, because they hold
  // a single-use authorization code that cannot be replayed.
  if (token && !finalHeaders.has("Authorization")) {
    finalHeaders.set("Authorization", `Bearer ${token}`);
  }

  // `body: undefined` is rejected under exactOptionalPropertyTypes; null is the
  // correct "no body" value for RequestInit.
  const res = await fetch(buildUrl(path), {
    ...rest,
    headers: finalHeaders,
    body: finalBody ?? null,
  });

  if (res.status === 401 && !isPublic && !_retried && !path.startsWith(REFRESH_PATH)) {
    const fresh = await runRefresh();
    if (fresh) {
      return api<T>(path, { ...options, _retried: true });
    }
    clearSession();
    onSessionExpired?.();
    throw new ApiError(401, "Your session has expired. Please sign in again.", "SESSION_EXPIRED");
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let json: unknown = null;
  if (text) {
    try {
      json = JSON.parse(text);
    } catch {
      json = text;
    }
  }

  if (!res.ok) {
    throw errorFrom(res.status, json, `Request failed (${res.status})`);
  }

  // A 200 carrying {success:false} is still a failure — several endpoints
  // report business errors this way rather than with a status code.
  if (json && typeof json === "object" && "success" in json) {
    const envelope = json as { success: boolean };
    if (envelope.success === false) {
      throw errorFrom(res.status, json, "Request was not successful.");
    }
  }

  return unwrap<T>(json);
}

/**
 * Drop-in replacement for `fetch` that adds the base URL, the bearer token and
 * the single-flight refresh, and otherwise leaves the request and response
 * untouched.
 *
 * Used by the migrated call sites, which already build their own bodies and
 * read `res.json()` themselves. Prefer `api()` for new code — it also unwraps
 * the response envelope and throws typed errors.
 *
 * The body is passed through verbatim: several callers send FormData with no
 * headers on purpose so the browser can generate the multipart boundary.
 */
export async function apiFetch(
  path: string,
  init: RequestInit & { public?: boolean; _retried?: boolean } = {},
): Promise<Response> {
  const { public: isPublic, _retried, headers, ...rest } = init;

  const finalHeaders = new Headers(headers);
  const token = readSession()?.access;
  if (token && !finalHeaders.has("Authorization")) {
    finalHeaders.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(buildUrl(path), { ...rest, headers: finalHeaders });

  if (res.status === 401 && !isPublic && !_retried && !path.startsWith(REFRESH_PATH)) {
    const fresh = await runRefresh();
    if (fresh) {
      return apiFetch(path, { ...init, _retried: true });
    }
    clearSession();
    onSessionExpired?.();
  }

  return res;
}

export const apiGet = <T = unknown>(path: string, options?: ApiOptions) =>
  api<T>(path, { ...options, method: "GET" });

export const apiPost = <T = unknown>(path: string, body?: unknown, options?: ApiOptions) =>
  api<T>(path, { ...options, method: "POST", body });

export const apiPut = <T = unknown>(path: string, body?: unknown, options?: ApiOptions) =>
  api<T>(path, { ...options, method: "PUT", body });
