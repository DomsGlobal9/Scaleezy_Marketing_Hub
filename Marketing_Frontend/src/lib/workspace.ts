const ACTIVE_WORKSPACE_KEY = "scaleezy.activeWorkspaceId";
export const WORKSPACE_CHANGED_EVENT = "scaleezy:workspace-changed";
let volatileActiveWorkspaceId: string | null = null;

export function readActiveWorkspaceId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ACTIVE_WORKSPACE_KEY) || volatileActiveWorkspaceId;
  } catch {
    return volatileActiveWorkspaceId;
  }
}

export function setActiveWorkspaceId(workspaceId: string | null): void {
  if (typeof window === "undefined") return;
  volatileActiveWorkspaceId = workspaceId;
  try {
    if (workspaceId) window.localStorage.setItem(ACTIVE_WORKSPACE_KEY, workspaceId);
    else window.localStorage.removeItem(ACTIVE_WORKSPACE_KEY);
  } catch {
    // Private browsing can reject storage. The in-memory value still
    // addresses every request in this document.
  }
  window.dispatchEvent(new CustomEvent(WORKSPACE_CHANGED_EVENT, { detail: workspaceId }));
}
