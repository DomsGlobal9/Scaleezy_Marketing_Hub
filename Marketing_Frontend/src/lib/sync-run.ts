import { useEffect } from "react";
import { apiGet } from "@/lib/api";
import { isRecord } from "@/lib/list-response";

export interface SyncRun {
  id: string;
  status: string;
  social_connection: string;
  error: string;
  created_at: string;
  account_name?: string;
  platform?: string;
  observed_count?: number;
  imported_count?: number;
  execution: { state: string; terminal: boolean; retry_allowed: boolean };
}

export function isSyncRun(value: unknown): value is SyncRun {
  if (!isRecord(value) || !isRecord(value["execution"])) return false;
  const execution = value["execution"];
  return (
    ["account_name", "platform"].every(
      (field) => value[field] === undefined || typeof value[field] === "string",
    ) &&
    ["observed_count", "imported_count"].every(
      (field) =>
        value[field] === undefined ||
        (typeof value[field] === "number" && Number.isInteger(value[field]) && value[field] >= 0),
    ) &&
    ["id", "status", "social_connection", "error", "created_at"].every(
      (field) => typeof value[field] === "string",
    ) &&
    typeof execution["state"] === "string" &&
    typeof execution["terminal"] === "boolean" &&
    typeof execution["retry_allowed"] === "boolean"
  );
}

export function mergeSyncRun(runs: SyncRun[], updated: SyncRun): SyncRun[] {
  return [updated, ...runs.filter((run) => run.id !== updated.id)];
}

/** Poll the scoped domain run, whose execution state is derived from TaskRun.
 * Chained timeouts avoid overlapping requests; route/workspace unmount stops polling. */
export function useSyncRunPolling(
  runs: SyncRun[],
  endpoint: string,
  onUpdate: (run: SyncRun) => void,
  onTerminal: () => Promise<void>,
  onError: (error: unknown) => void,
) {
  const pendingKey = runs
    .filter((run) => !run.execution.terminal)
    .map((run) => run.id)
    .sort()
    .join("|");
  useEffect(() => {
    if (!pendingKey) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const updates = await Promise.all(
          pendingKey.split("|").map(async (id) => {
            const payload = await apiGet<unknown>(`${endpoint}${encodeURIComponent(id)}/`);
            if (!isSyncRun(payload)) throw new Error("Sync status returned an invalid response.");
            return payload;
          }),
        );
        if (cancelled) return;
        if (updates.some((run) => run.execution.terminal)) {
          // A terminal update changes the effect key. Report a failed data
          // refresh before publishing that update, so cleanup cannot hide it.
          try {
            await onTerminal();
          } catch (error) {
            if (!cancelled) onError(error);
          }
        }
        if (!cancelled) updates.forEach(onUpdate);
      } catch (error) {
        if (!cancelled) onError(error);
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 3_000);
    };
    timer = setTimeout(() => void poll(), 1_000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [pendingKey, endpoint, onUpdate, onTerminal, onError]);
}
