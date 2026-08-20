/**
 * Client-side session storage.
 *
 * Deliberately holds NO token in module scope. On a server runtime a module is
 * a per-isolate singleton shared across concurrent SSR requests, so a cached
 * token would leak between users. Every read goes to localStorage, which only
 * exists on the client, so there is nothing to leak.
 *
 * Tokens live in localStorage rather than an httpOnly cookie because the API is
 * on a different registrable domain from the frontend — a third-party cookie
 * that Safari ITP and Firefox ETP block regardless of attributes. Revisit once
 * the API moves alongside the app.
 */

const STORAGE_KEY = "scaleezy.session";

export interface Session {
  access: string;
  refresh: string;
}

const isBrowser = () => typeof window !== "undefined";

export function readSession(): Session | null {
  if (!isBrowser()) return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Session>;
    if (!parsed?.access || !parsed?.refresh) return null;
    return { access: parsed.access, refresh: parsed.refresh };
  } catch {
    return null;
  }
}

export function writeSession(session: Session) {
  if (!isBrowser()) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    notify();
  } catch {
    // Quota or private mode — the request in flight still succeeds.
  }
}

export function clearSession() {
  if (!isBrowser()) return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  notify();
}

/** Subscribers are notified on sign-in/out so the UI can react. */
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((fn) => {
    try {
      fn();
    } catch {
      /* a bad listener must not break auth */
    }
  });
}

export interface AuthStore {
  isAuthenticated(): boolean;
  getAccessToken(): string | null;
  getRefreshToken(): string | null;
  signIn(session: Session): void;
  setAccess(access: string): void;
  signOut(): void;
  subscribe(fn: () => void): () => void;
}

/**
 * Built once per router instance (see src/router.tsx), mirroring how a fresh
 * QueryClient is created per request. Holds no state of its own.
 */
export function createAuthStore(): AuthStore {
  return {
    isAuthenticated: () => readSession() !== null,
    getAccessToken: () => readSession()?.access ?? null,
    getRefreshToken: () => readSession()?.refresh ?? null,
    signIn: (session) => writeSession(session),
    setAccess: (access) => {
      const current = readSession();
      if (current) writeSession({ ...current, access });
    },
    signOut: () => clearSession(),
    subscribe: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

/**
 * Only same-origin, non-protocol-relative paths are accepted as a post-login
 * destination. The router blocks dangerous protocols but not cross-origin
 * hosts, so "//evil.com" and "https://evil.com" would otherwise be open
 * redirects.
 */
export function safeInternalPath(value: unknown): string | null {
  if (typeof value !== "string" || !value) return null;
  if (!/^\/(?!\/)/.test(value)) return null;
  return value;
}
