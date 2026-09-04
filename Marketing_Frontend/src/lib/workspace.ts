/**
 * Which client (workspace) every request is addressed to.
 *
 * Modelled on lib/auth.ts: the selection itself lives in localStorage, which
 * only exists on the client, so a server runtime — where a module is a
 * per-isolate singleton shared by concurrent requests — has nothing to leak.
 * The in-memory list is filled only by loadWorkspaces(), which refuses to run
 * off the browser for the same reason.
 *
 * The header this store feeds is ADDRESSING, never authorisation. The backend
 * re-checks membership on every request (apps/common/permissions.py), so a
 * forged or stale id is rejected there. Nothing in here may be treated
 * client-side as a grant — it only decides which tenant we are asking about.
 */
import { useSyncExternalStore } from "react";

import { api } from "@/lib/api";

const STORAGE_KEY = "scaleezy.workspace";

/**
 * Membership discovery goes through /api/auth/me/, NOT
 * /api/marketing/workspaces/. The workspace list endpoint sits behind
 * HasWorkspaceRole, which resolves the caller's workspace from the header or
 * from a single membership — so the moment someone has two clients and no
 * header yet, listing their clients 403s and they can never get one. /auth/me/
 * is IsAuthenticated only and returns the same memberships, which is what
 * breaks the chicken and egg.
 */
const ME_PATH = "/api/auth/me/";
const WORKSPACES_PATH = "/api/marketing/workspaces/";

export interface Workspace {
  id: string;
  name: string;
  role: string | null;
}

export type WorkspaceStatus = "idle" | "loading" | "ready" | "error";

export interface WorkspaceState {
  status: WorkspaceStatus;
  workspaces: Workspace[];
  selectedId: string | null;
  /** Navigation hint only; every platform endpoint still authorises server-side. */
  isPlatformAdmin: boolean;
  /** True from the moment a switch is committed until the document is gone. */
  switching: boolean;
  error: string | null;
}

const isBrowser = () => typeof window !== "undefined";

function readStoredId(): string | null {
  if (!isBrowser()) return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY) || null;
  } catch {
    return null;
  }
}

function writeStoredId(id: string | null) {
  if (!isBrowser()) return;
  try {
    if (id) window.localStorage.setItem(STORAGE_KEY, id);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Quota or private mode — the in-memory selection still addresses this tab.
  }
}

const EMPTY: WorkspaceState = {
  status: "idle",
  workspaces: [],
  selectedId: null,
  isPlatformAdmin: false,
  switching: false,
  error: null,
};

/**
 * The stored id is trusted provisionally, before the membership list lands.
 * Withholding it would 400 (NO_WORKSPACE) every request a multi-client user
 * makes during boot — the exact failure this store exists to remove — and it
 * was only ever written from a list the server confirmed. loadWorkspaces()
 * discards it the moment the server says that membership is gone.
 */
let state: WorkspaceState = { ...EMPTY, selectedId: readStoredId() };

const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((fn) => {
    try {
      fn();
    } catch {
      /* a bad listener must not break request addressing */
    }
  });
}

function setState(patch: Partial<WorkspaceState>) {
  state = { ...state, ...patch };
  notify();
}

export function getWorkspaceState(): WorkspaceState {
  return state;
}

/** The value api.ts stamps onto X-Workspace-Id. */
export function readSelectedWorkspaceId(): string | null {
  return state.selectedId;
}

export function getSelectedWorkspace(): Workspace | null {
  return state.workspaces.find((w) => w.id === state.selectedId) ?? null;
}

export function subscribeWorkspaces(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------

interface MeMembership {
  workspace_id?: unknown;
  workspace_name?: unknown;
  role?: unknown;
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function fromMemberships(rows: MeMembership[]): Workspace[] {
  const out: Workspace[] = [];
  for (const row of rows) {
    const id = asText(row?.workspace_id);
    if (!id) continue;
    out.push({
      id,
      name: asText(row?.workspace_name) ?? "Untitled client",
      role: asText(row?.role),
    });
  }
  return out;
}

/** The list endpoint answers as a bare array, an envelope, or a page. */
function fromWorkspaceList(payload: unknown): Workspace[] {
  const rows = Array.isArray(payload)
    ? payload
    : ((payload as { results?: unknown } | null)?.results ?? null);
  if (!Array.isArray(rows)) return [];

  const out: Workspace[] = [];
  for (const row of rows as Array<Record<string, unknown>>) {
    const id = asText(row?.["id"]);
    if (!id) continue;
    out.push({ id, name: asText(row?.["workspace_name"]) ?? "Untitled client", role: null });
  }
  return out;
}

/**
 * Decides what the stored id resolves to now that the server has spoken.
 *
 * A persisted id the user no longer belongs to is dropped rather than sent: it
 * would earn a 403 WORKSPACE_FORBIDDEN on every panel with no way out of it.
 * With nothing valid left we fall back to the first client instead of sending
 * no header at all, because a header-less request 400s the instant a user has
 * more than one membership. One client therefore auto-selects, several default
 * to the first, and the sidebar selector makes the choice visible and
 * changeable.
 */
function reconcile(rows: Workspace[], current: string | null): string | null {
  let next = current && rows.some((w) => w.id === current) ? current : null;
  if (!next) next = rows[0]?.id ?? null;
  if (next !== current) writeStoredId(next);
  return next;
}

let inflight: Promise<WorkspaceState> | null = null;

async function fetchWorkspaces(): Promise<WorkspaceState> {
  setState({ status: "loading", error: null });

  let rows: Workspace[] | null = null;
  let isPlatformAdmin = false;
  let failure: unknown = null;

  try {
    const me = await api<{
      memberships?: MeMembership[];
      is_platform_admin?: unknown;
    } | null>(ME_PATH);
    isPlatformAdmin = me?.is_platform_admin === true;
    const memberships = me?.memberships;
    if (Array.isArray(memberships)) rows = fromMemberships(memberships);
  } catch (err) {
    failure = err;
  }

  if (rows === null) {
    // Only reached when /auth/me/ cannot answer. It resolves for a caller the
    // backend can already place in a workspace, which is why it is the
    // fallback rather than the primary source.
    try {
      rows = fromWorkspaceList(await api<unknown>(WORKSPACES_PATH));
      failure = null;
    } catch (err) {
      failure = failure ?? err;
    }
  }

  if (rows === null) {
    // The server was unreachable, so the stored selection has not been
    // disproved and stays. Clearing it on a flaky network would eject people
    // from a client they still belong to.
    setState({
      status: "error",
      isPlatformAdmin: false,
      error: failure instanceof Error ? failure.message : "Could not load your clients.",
    });
    return state;
  }

  setState({
    status: "ready",
    workspaces: rows,
    selectedId: reconcile(rows, state.selectedId),
    isPlatformAdmin,
    error: null,
  });
  return state;
}

/**
 * Resolves once the selection is known to be real. Awaited in the /_hub
 * beforeLoad, which runs parent-first and serially — child loaders fire in
 * parallel afterwards, so this is the only hook that can guarantee no hub
 * request goes out addressed to a workspace the user has left.
 *
 * Never rejects: a failure here must degrade the sidebar, not blow up the
 * route with an error boundary.
 */
export function loadWorkspaces(options: { force?: boolean } = {}): Promise<WorkspaceState> {
  if (!isBrowser()) return Promise.resolve(state);
  if (!options.force && state.status === "ready") return Promise.resolve(state);
  if (!inflight) {
    inflight = fetchWorkspaces().finally(() => {
      // Always cleared, so one failure cannot poison later attempts.
      inflight = null;
    });
  }
  return inflight;
}

// ---------------------------------------------------------------------------
// Switching
// ---------------------------------------------------------------------------

/**
 * Changes the client, then reloads the document.
 *
 * A full reload rather than router.invalidate(): nothing in the app keys its
 * cache by workspace — the QueryClient, loader data, component state and the
 * brand context each page holds would all survive an invalidate and repaint
 * the previous client's rows while the new ones arrive. Reloading is the only
 * cheap way to guarantee no sibling-workspace data is ever on screen, and
 * `switching` covers the page opaquely until the navigation takes over.
 */
export function selectWorkspace(id: string): void {
  if (!id || id === state.selectedId) return;
  // Only ids the server has already confirmed are addressable, so the picker
  // cannot be used to probe a workspace the user was never listed in.
  if (!state.workspaces.some((w) => w.id === id)) return;

  const previousId = state.selectedId;
  writeStoredId(id);
  // Keep the in-memory request address on the OLD client until this document
  // is gone. Brand Master and other editors flush during pagehide/unmount; if
  // selectedId changed here first, those last PATCHes would carry the new
  // X-Workspace-Id with an old-client object id and be rejected. The new id is
  // already durable in localStorage and becomes state.selectedId when the new
  // document boots.
  setState({ switching: true });
  if (isBrowser()) {
    window.location.reload();
    // If beforeunload is cancelled because an editor still has work, this
    // document survives and the reload never completes. Restore its address
    // and controls instead of leaving an opaque switching overlay forever.
    window.setTimeout(() => {
      writeStoredId(previousId);
      setState({ switching: false });
    }, 1_000);
  }
}

/**
 * Called on sign-out. Whoever signs in next on this browser must not inherit
 * the previous person's client as their default.
 */
export function clearWorkspaces(): void {
  writeStoredId(null);
  state = { ...EMPTY };
  notify();
}

// ---------------------------------------------------------------------------
// React binding
// ---------------------------------------------------------------------------

export function useWorkspaces(): WorkspaceState {
  return useSyncExternalStore(subscribeWorkspaces, getWorkspaceState, () => EMPTY);
}
