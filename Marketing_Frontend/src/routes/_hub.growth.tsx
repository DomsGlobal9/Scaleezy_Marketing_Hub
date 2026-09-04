import { createFileRoute } from "@tanstack/react-router";
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  Inbox,
  Loader2,
  LockKeyhole,
  LockKeyholeOpen,
  MessageSquareReply,
  RefreshCw,
  Send,
  Sparkles,
  UserPlus,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { PageHeader, StatusBadge } from "@/components/marketing/primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch, apiGet, apiPost } from "@/lib/api";
import { fetchCurrentBrand } from "@/lib/brand-master";
import type { BrandDto } from "@/lib/brand-settings";
import { useWorkspaces } from "@/lib/workspace";
import { hasStringFields, isRecord, parseList } from "@/lib/list-response";
import { isSyncRun, mergeSyncRun, useSyncRunPolling, type SyncRun } from "@/lib/sync-run";

export const Route = createFileRoute("/_hub/growth")({
  head: () => ({
    meta: [
      { title: "Engagement — Scaleezy Marketing Hub" },
      {
        name: "description",
        content:
          "A governed engagement inbox: claim a conversation, draft with AI, approve, and send platform-confirmed replies.",
      },
    ],
  }),
  component: EngagementPage,
});

interface Connection {
  id: string;
  platform: string;
  account_name: string;
  status: string;
}

interface InboxItem {
  id: string;
  platform: string;
  kind: string;
  author_name: string;
  author_handle: string;
  body: string;
  source_url: string;
  occurred_at: string;
  status: string;
  sentiment: string;
  urgency: string;
  assigned_to_name: string;
  locked_by_name: string;
  lock_expires_at: string | null;
  ai_draft: string;
  draft_status: string;
  ai_provider_name: string;
  ai_risk_flags: string[];
  approved_response: string;
  last_error: string;
}

interface SavedReply {
  id: string;
  name: string;
  body: string;
}

/** The slice of apps/analytics GrowthLeadSerializer this page reads. */
interface GrowthLead {
  id: string;
  engagement_item: string | null;
  status: string;
}

function isInboxItem(value: unknown): value is InboxItem {
  return (
    isRecord(value) &&
    hasStringFields(value, [
      "id",
      "platform",
      "kind",
      "author_name",
      "author_handle",
      "body",
      "source_url",
      "occurred_at",
      "status",
      "sentiment",
      "urgency",
      "assigned_to_name",
      "locked_by_name",
      "ai_draft",
      "draft_status",
      "ai_provider_name",
      "approved_response",
      "last_error",
    ]) &&
    (value["lock_expires_at"] === null || typeof value["lock_expires_at"] === "string") &&
    Array.isArray(value["ai_risk_flags"]) &&
    value["ai_risk_flags"].every((flag) => typeof flag === "string")
  );
}

const ACTIVE_DRAFT = new Set(["QUEUED", "PROCESSING"]);

function EngagementPage() {
  const [brand, setBrand] = useState<BrandDto | null>(null);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [savedReplies, setSavedReplies] = useState<SavedReply[]>([]);
  const [leads, setLeads] = useState<GrowthLead[]>([]);
  const [selectedConnection, setSelectedConnection] = useState("");
  const [selectedItemId, setSelectedItemId] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [hasLoaded, setHasLoaded] = useState(false);
  const [syncRuns, setSyncRuns] = useState<SyncRun[]>([]);

  const load = useCallback(async () => {
    const brand = await fetchCurrentBrand();
    setBrand(brand);
    const [itemPayload, accountPayload, replyPayload, leadPayload, syncPayload] = await Promise.all(
      [
        apiGet<unknown>(`/api/marketing/engagement/items/?brand_id=${brand.id}`),
        apiGet<unknown>("/api/marketing/social-accounts/"),
        apiGet<unknown>("/api/marketing/engagement/saved-replies/"),
        // Reads are VIEWER+, so every member sees which conversations are
        // already in the pipeline; only capturing needs EDITOR.
        apiGet<unknown>("/api/marketing/analytics/leads/"),
        apiGet<unknown>(`/api/marketing/engagement/sync-runs/?brand_id=${brand.id}&page_size=10`),
      ],
    );
    const nextItems = parseList(itemPayload, isInboxItem, "Inbox");
    const nextConnections = parseList(
      accountPayload,
      (row): row is Connection =>
        hasStringFields(row, ["id", "platform", "account_name", "status"]),
      "Accounts",
    ).filter((item) => item.status === "CONNECTED" && ["X", "YOUTUBE"].includes(item.platform));
    const replies = parseList(
      replyPayload,
      (row): row is SavedReply => hasStringFields(row, ["id", "name", "body"]),
      "Saved replies",
    );
    const nextLeads = parseList(
      leadPayload,
      (row): row is GrowthLead =>
        isRecord(row) &&
        hasStringFields(row, ["id", "status"]) &&
        (row["engagement_item"] === null || typeof row["engagement_item"] === "string"),
      "Leads",
    );
    const nextRuns = parseList(syncPayload, isSyncRun, "Inbox syncs");
    setItems(nextItems);
    setConnections(nextConnections);
    setSavedReplies(replies);
    setLeads(nextLeads);
    setSyncRuns((current) => [
      ...nextRuns,
      ...current.filter(
        (run) => !run.execution.terminal && !nextRuns.some((next) => next.id === run.id),
      ),
    ]);
    setSelectedConnection((current) =>
      nextConnections.some((row) => row.id === current) ? current : nextConnections[0]?.id || "",
    );
    setSelectedItemId((current) =>
      current && nextItems.some((item) => item.id === current) ? current : (nextItems[0]?.id ?? ""),
    );
    setHasLoaded(true);
    setError("");
  }, []);

  const handleLoadError = useCallback(
    (cause: unknown) =>
      setError(cause instanceof Error ? cause.message : "Could not load the engagement inbox."),
    [],
  );
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      await load();
    } catch (cause) {
      handleLoadError(cause);
    } finally {
      setLoading(false);
    }
  }, [load, handleLoadError]);
  const updateSyncRun = useCallback(
    (run: SyncRun) => setSyncRuns((current) => mergeSyncRun(current, run)),
    [],
  );
  useSyncRunPolling(
    syncRuns,
    "/api/marketing/engagement/sync-runs/",
    updateSyncRun,
    load,
    handleLoadError,
  );
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const shouldPoll = useMemo(
    () => items.some((item) => ACTIVE_DRAFT.has(item.draft_status) || item.status === "SENDING"),
    [items],
  );

  useEffect(() => {
    if (!shouldPoll) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        await load();
      } catch (cause) {
        if (!cancelled) handleLoadError(cause);
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 3_000);
    };
    timer = setTimeout(() => void poll(), 3_000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [load, shouldPoll, handleLoadError]);

  const selectedItem = items.find((item) => item.id === selectedItemId) ?? null;

  // Mirrors the backend gate exactly (apps/analytics/views.py GrowthLeadView
  // via GovernedAnalyticsView: POST needs EDITOR or above). An unknown role —
  // the fallback membership path reports none — is not mutation authority.
  // The server re-checks every request as the final authority.
  const { workspaces, selectedId } = useWorkspaces();
  const role = workspaces.find((w) => w.id === selectedId)?.role ?? null;
  const canCapture = role !== null && ["EDITOR", "MANAGER", "ADMIN", "OWNER"].includes(role);

  const leadByItem = useMemo(() => {
    const map = new Map<string, GrowthLead>();
    for (const lead of leads) if (lead.engagement_item) map.set(lead.engagement_item, lead);
    return map;
  }, [leads]);

  async function act<T>(
    key: string,
    request: () => Promise<T>,
    success: string | ((result: T) => string),
  ) {
    setWorking(key);
    try {
      const result = await request();
      toast.success(typeof success === "function" ? success(result) : success);
      await load().catch(handleLoadError);
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Action failed.");
    } finally {
      setWorking("");
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Governed customer engagement"
        title="Engagement"
        subtitle={`X mentions and YouTube comments for ${brand?.name || "this client"} — claimed by a person, drafted with routed AI, and sent only after human approval.`}
        backTo="/"
      />

      {error ? (
        <div
          role="alert"
          className="mb-6 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
        >
          <p className="flex items-center gap-3">
            <CircleAlert className="size-5" /> {error}
            {hasLoaded ? " The last loaded inbox is still shown." : ""}
          </p>
          <Button
            className="mt-3"
            variant="outline"
            disabled={loading}
            onClick={() => void refresh()}
          >
            Try again
          </Button>
        </div>
      ) : null}
      {loading && hasLoaded ? (
        <p role="status" className="mb-4 text-sm text-muted-foreground">
          Refreshing inbox…
        </p>
      ) : null}
      {syncRuns.length ? (
        <div aria-live="polite" className="mb-5 space-y-2">
          {syncRuns.map((run) => (
            <div
              key={run.id}
              className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm"
            >
              <span>Inbox sync · {new Date(run.created_at).toLocaleString()}</span>
              <StatusBadge status={run.execution.state.replaceAll("_", " ")} />
              {run.execution.terminal && run.execution.state === "COMPLETED" ? (
                <span>{run.imported_count} new conversations</span>
              ) : null}
              {run.error ? (
                <p className="basis-full text-destructive">
                  {run.error}
                  {!run.execution.terminal ? " The background task still owns this attempt." : ""}
                </p>
              ) : null}
              {run.execution.retry_allowed && canCapture ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={working === `retry-${run.id}`}
                  onClick={() =>
                    void act(
                      `retry-${run.id}`,
                      async () => {
                        const result = await apiPost<unknown>(
                          `/api/marketing/engagement/sync-runs/${run.id}/retry/`,
                          {},
                        );
                        if (!isSyncRun(result))
                          throw new Error("Invalid sync response. Refresh before retrying.");
                        updateSyncRun(result);
                      },
                      "Inbox sync retry queued.",
                    )
                  }
                >
                  Retry sync
                </Button>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}

      <InboxPanel
        brandId={brand?.id ?? ""}
        connections={connections}
        selectedConnection={selectedConnection}
        setSelectedConnection={setSelectedConnection}
        items={items}
        selectedItem={selectedItem}
        setSelectedItemId={setSelectedItemId}
        savedReplies={savedReplies}
        loading={loading}
        hasLoaded={hasLoaded}
        syncPending={syncRuns.some(
          (run) => run.social_connection === selectedConnection && !run.execution.terminal,
        )}
        onSyncQueued={updateSyncRun}
        working={working}
        act={act}
        canCapture={canCapture}
        capturedLead={selectedItem ? (leadByItem.get(selectedItem.id) ?? null) : null}
      />
    </div>
  );
}

function InboxPanel({
  brandId,
  connections,
  selectedConnection,
  setSelectedConnection,
  items,
  selectedItem,
  setSelectedItemId,
  savedReplies,
  loading,
  hasLoaded,
  syncPending,
  onSyncQueued,
  working,
  act,
  canCapture,
  capturedLead,
}: {
  brandId: string;
  connections: Connection[];
  selectedConnection: string;
  setSelectedConnection: (value: string) => void;
  items: InboxItem[];
  selectedItem: InboxItem | null;
  setSelectedItemId: (value: string) => void;
  savedReplies: SavedReply[];
  loading: boolean;
  hasLoaded: boolean;
  syncPending: boolean;
  onSyncQueued: (run: SyncRun) => void;
  working: string;
  act: <T>(
    key: string,
    request: () => Promise<T>,
    success: string | ((result: T) => string),
  ) => Promise<void>;
  canCapture: boolean;
  capturedLead: GrowthLead | null;
}) {
  const [response, setResponse] = useState("");
  const [capturing, setCapturing] = useState(false);
  const [leadValue, setLeadValue] = useState("");
  const [leadNotes, setLeadNotes] = useState("");

  useEffect(() => {
    setResponse(selectedItem?.approved_response || selectedItem?.ai_draft || "");
  }, [selectedItem?.id, selectedItem?.approved_response, selectedItem?.ai_draft]);

  useEffect(() => {
    setCapturing(false);
    setLeadValue("");
    setLeadNotes("");
  }, [selectedItem?.id]);

  const sync = () =>
    act(
      "sync",
      async () => {
        const result = await apiPost<unknown>("/api/marketing/engagement/sync-runs/", {
          brand: brandId,
          social_connection: selectedConnection,
        });
        if (!isSyncRun(result))
          throw new Error("Invalid sync response. Refresh before starting another sync.");
        onSyncQueued(result);
      },
      "Inbox sync queued. New items will appear here.",
    );

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold">One inbox, clear ownership.</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Live sync currently supports X mentions and YouTube comments. Replies require human
            approval.
          </p>
        </div>
        <div className="flex min-w-0 flex-1 items-center gap-2 sm:max-w-xl">
          <Select value={selectedConnection} onValueChange={setSelectedConnection}>
            <SelectTrigger aria-label="Connected account for inbox sync" className="min-w-0 flex-1">
              <SelectValue placeholder="Choose a connected account" />
            </SelectTrigger>
            <SelectContent>
              {connections.map((connection) => (
                <SelectItem key={connection.id} value={connection.id}>
                  {connection.platform} · {connection.account_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            disabled={
              !canCapture || !hasLoaded || !selectedConnection || working === "sync" || syncPending
            }
            onClick={() => void sync()}
          >
            {working === "sync" ? <Loader2 className="animate-spin" /> : <RefreshCw />} Sync
          </Button>
        </div>
      </div>

      <div className="grid min-h-[34rem] overflow-hidden rounded-2xl border border-border bg-background lg:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="border-b border-border lg:border-r lg:border-b-0">
          <div className="border-b border-border p-4 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            {hasLoaded ? items.length : "—"} conversations
          </div>
          <div className="max-h-[36rem] overflow-y-auto">
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={selectedItem?.id === item.id}
                onClick={() => setSelectedItemId(item.id)}
                className={`w-full border-b border-border p-4 text-left transition-colors hover:bg-secondary/60 ${selectedItem?.id === item.id ? "bg-primary/8" : ""}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-primary">
                    {item.platform} · {item.kind}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {new Date(item.occurred_at).toLocaleDateString()}
                  </span>
                </div>
                <p className="mt-1 truncate font-medium">
                  {item.author_handle || item.author_name || "Unknown author"}
                </p>
                <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{item.body}</p>
                <div className="mt-2 flex items-center gap-2">
                  <StatusBadge status={item.status.replaceAll("_", " ")} />
                  {item.urgency === "HIGH" || item.urgency === "CRITICAL" ? (
                    <span className="text-xs font-semibold text-destructive">{item.urgency}</span>
                  ) : null}
                </div>
              </button>
            ))}
            {!items.length ? (
              <div role="status" className="p-8 text-center text-sm text-muted-foreground">
                {loading
                  ? "Loading conversations…"
                  : hasLoaded
                    ? "Sync a supported account to populate the inbox."
                    : "Inbox unavailable. Try loading it again."}
              </div>
            ) : null}
          </div>
        </div>

        {selectedItem ? (
          <article className="p-5 sm:p-7">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold">
                  {selectedItem.author_handle || selectedItem.author_name}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {selectedItem.platform} · {new Date(selectedItem.occurred_at).toLocaleString()}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <StatusBadge status={selectedItem.sentiment} />
                <StatusBadge
                  status={selectedItem.urgency}
                  tone={selectedItem.urgency === "CRITICAL" ? "danger" : "neutral"}
                />
              </div>
            </div>
            <div className="mt-5 rounded-xl bg-secondary p-4 text-sm leading-7">
              {selectedItem.body}
            </div>
            {selectedItem.locked_by_name ? (
              <p className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                <LockKeyhole className="size-3.5" /> Locked by {selectedItem.locked_by_name} until{" "}
                {selectedItem.lock_expires_at
                  ? new Date(selectedItem.lock_expires_at).toLocaleTimeString()
                  : "released"}
              </p>
            ) : null}
            {selectedItem.ai_risk_flags.length ? (
              <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                Risk review: {selectedItem.ai_risk_flags.join(", ")}
              </div>
            ) : null}
            {selectedItem.last_error ? (
              <div className="mt-4 rounded-xl border border-destructive/30 p-3 text-sm text-destructive">
                {selectedItem.last_error}
              </div>
            ) : null}

            <div className="mt-6 flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={working === `claim-${selectedItem.id}`}
                onClick={() =>
                  void act(
                    `claim-${selectedItem.id}`,
                    () => apiPost(`/api/marketing/engagement/items/${selectedItem.id}/claim/`, {}),
                    "Conversation claimed.",
                  )
                }
              >
                <LockKeyhole /> Claim
              </Button>
              {selectedItem.locked_by_name ? (
                <Button
                  variant="outline"
                  disabled={working === `release-${selectedItem.id}`}
                  onClick={() =>
                    void act(
                      `release-${selectedItem.id}`,
                      () =>
                        apiPost(`/api/marketing/engagement/items/${selectedItem.id}/release/`, {}),
                      "Lock released.",
                    )
                  }
                >
                  {working === `release-${selectedItem.id}` ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <LockKeyholeOpen />
                  )}{" "}
                  Release
                </Button>
              ) : null}
              <Button
                variant="outline"
                disabled={
                  ACTIVE_DRAFT.has(selectedItem.draft_status) ||
                  working === `draft-${selectedItem.id}`
                }
                onClick={() =>
                  void act(
                    `draft-${selectedItem.id}`,
                    () =>
                      apiPost(
                        `/api/marketing/engagement/items/${selectedItem.id}/draft-reply/`,
                        {},
                      ),
                    "AI draft queued for human review.",
                  )
                }
              >
                {ACTIVE_DRAFT.has(selectedItem.draft_status) ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Sparkles />
                )}{" "}
                Draft with routed AI
              </Button>
              {capturedLead ? (
                <Button variant="outline" disabled>
                  <Check />{" "}
                  {capturedLead.status === "CONVERTED" ? "Lead converted" : "Lead captured"}
                </Button>
              ) : (
                <Button
                  variant="outline"
                  disabled={!canCapture}
                  onClick={() => setCapturing((open) => !open)}
                >
                  <UserPlus /> Capture as lead
                </Button>
              )}
              {selectedItem.source_url ? (
                <Button asChild variant="ghost">
                  <a href={selectedItem.source_url} target="_blank" rel="noreferrer">
                    Open source <ArrowUpRight />
                  </a>
                </Button>
              ) : null}
            </div>

            {!canCapture && !capturedLead ? (
              // Same explanation the backend's 403 gives, shown before anyone
              // opens a form they cannot submit. The button stays visible so
              // the inbox reads the same for everyone.
              <p className="mt-3 rounded-lg border border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
                Only a marketing executive or above can capture leads.
              </p>
            ) : null}

            {capturing && !capturedLead && canCapture ? (
              <div className="mt-4 rounded-xl border border-border p-4">
                <p className="text-xs text-muted-foreground">
                  Adds {selectedItem.author_handle || selectedItem.author_name || "this author"} to
                  the growth pipeline. Name and handle are filled from the conversation.
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Input
                    type="number"
                    min="0"
                    placeholder="Estimated value (USD)"
                    className="w-44"
                    value={leadValue}
                    onChange={(event) => setLeadValue(event.target.value)}
                  />
                  <Input
                    placeholder="Notes (optional)"
                    className="min-w-44 flex-1"
                    value={leadNotes}
                    onChange={(event) => setLeadNotes(event.target.value)}
                  />
                  <Button
                    disabled={working === `lead-${selectedItem.id}`}
                    onClick={() =>
                      void act(
                        `lead-${selectedItem.id}`,
                        async () => {
                          // The one call here that needs the raw status: the
                          // backend answers 201 when it created the lead and
                          // 200 with the existing one when this conversation
                          // was already captured (it dedupes per item).
                          const res = await apiFetch("/api/marketing/analytics/leads/", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                              engagement_item: selectedItem.id,
                              estimated_value: leadValue.trim() || "0",
                              notes: leadNotes.trim(),
                            }),
                          });
                          const json = (await res.json().catch(() => null)) as {
                            success?: boolean;
                            message?: string;
                          } | null;
                          if (!res.ok || json?.success === false) {
                            throw new Error(json?.message || `Capture failed (${res.status})`);
                          }
                          return res.status;
                        },
                        (status) =>
                          status === 201
                            ? "Captured as a growth lead."
                            : "Already captured — this conversation has a lead.",
                      )
                    }
                  >
                    {working === `lead-${selectedItem.id}` ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <UserPlus />
                    )}{" "}
                    Capture lead
                  </Button>
                </div>
              </div>
            ) : null}

            <div className="mt-6 border-t border-border pt-5">
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="response">Response for approval</Label>
                {selectedItem.ai_provider_name ? (
                  <span className="text-xs text-muted-foreground">
                    Drafted by {selectedItem.ai_provider_name}
                  </span>
                ) : null}
              </div>
              {/* Rendered only when the workspace actually has saved replies:
                  there is no way to create one from here, so an empty
                  dropdown would be a dead end. */}
              {savedReplies.length ? (
                <Select
                  onValueChange={(id) =>
                    setResponse(savedReplies.find((reply) => reply.id === id)?.body ?? response)
                  }
                >
                  <SelectTrigger className="mt-2">
                    <SelectValue placeholder="Insert a saved reply" />
                  </SelectTrigger>
                  <SelectContent>
                    {savedReplies.map((reply) => (
                      <SelectItem key={reply.id} value={reply.id}>
                        {reply.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : null}
              <Textarea
                id="response"
                value={response}
                onChange={(event) => setResponse(event.target.value)}
                className="mt-2 min-h-32"
                placeholder="Write or review the response. Nothing sends automatically."
              />
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  disabled={!response.trim() || working === `approve-${selectedItem.id}`}
                  onClick={() =>
                    void act(
                      `approve-${selectedItem.id}`,
                      () =>
                        apiPost(`/api/marketing/engagement/items/${selectedItem.id}/approve/`, {
                          response,
                        }),
                      "Response approved. It is still not sent.",
                    )
                  }
                >
                  <Check /> Approve response
                </Button>
                <Button
                  variant="secondary"
                  disabled={
                    selectedItem.status !== "APPROVED" || working === `send-${selectedItem.id}`
                  }
                  onClick={() =>
                    void act(
                      `send-${selectedItem.id}`,
                      () => apiPost(`/api/marketing/engagement/items/${selectedItem.id}/send/`, {}),
                      "Response sent by the connected platform.",
                    )
                  }
                >
                  {working === `send-${selectedItem.id}` ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <Send />
                  )}{" "}
                  Send approved response
                </Button>
                <Button
                  variant="ghost"
                  onClick={() =>
                    void act(
                      `resolve-${selectedItem.id}`,
                      () =>
                        apiPost(`/api/marketing/engagement/items/${selectedItem.id}/resolve/`, {}),
                      "Conversation resolved.",
                    )
                  }
                >
                  <MessageSquareReply /> Resolve without reply
                </Button>
              </div>
            </div>
          </article>
        ) : (
          <div className="grid place-items-center p-10 text-center text-sm text-muted-foreground">
            <Inbox className="mb-3 size-8 text-primary" />
            Choose a conversation to work on.
          </div>
        )}
      </div>
    </div>
  );
}
