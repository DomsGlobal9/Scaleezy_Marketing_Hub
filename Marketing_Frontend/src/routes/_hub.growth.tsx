import { createFileRoute } from "@tanstack/react-router";
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  Inbox,
  Lightbulb,
  Loader2,
  LockKeyhole,
  MessageSquareReply,
  Radar,
  RefreshCw,
  Search,
  Send,
  Sparkles,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost } from "@/lib/api";
import { fetchCurrentBrand } from "@/lib/brand-master";
import type { BrandDto } from "@/lib/brand-settings";
import { buildGuidedResearchText } from "@/lib/guided-workflows";

export const Route = createFileRoute("/_hub/growth")({
  head: () => ({
    meta: [
      { title: "Growth Engine — Scaleezy Marketing Hub" },
      {
        name: "description",
        content: "Discover cited creative references and operate a governed social inbox.",
      },
    ],
  }),
  component: GrowthEnginePage,
});

interface Finding {
  id: string;
  kind: string;
  title: string;
  source_url: string;
  preview_url: string;
  source_name: string;
  platform: string;
  excerpt: string;
  rights_status: string;
  verification_status: string;
  verification_error: string;
  adopted_inspiration: string | null;
}

interface ResearchRun {
  id: string;
  query: string;
  status: string;
  provider_name: string;
  error: string;
  created_at: string;
  findings: Finding[];
}

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

interface ListEnvelope<T> {
  results?: T[];
}

function rows<T>(value: T[] | ListEnvelope<T>): T[] {
  return Array.isArray(value) ? value : (value.results ?? []);
}

const LOOP = ["Research", "Direct", "Create", "Review", "Publish", "Engage", "Learn"];
const ACTIVE_RESEARCH = new Set(["QUEUED", "PROCESSING"]);
const ACTIVE_DRAFT = new Set(["QUEUED", "PROCESSING"]);

function GrowthEnginePage() {
  const [brand, setBrand] = useState<BrandDto | null>(null);
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [savedReplies, setSavedReplies] = useState<SavedReply[]>([]);
  const [selectedConnection, setSelectedConnection] = useState("");
  const [selectedItemId, setSelectedItemId] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const brand = await fetchCurrentBrand();
    setBrand(brand);
    const [runPayload, itemPayload, accountPayload, replyPayload] = await Promise.all([
      apiGet<ResearchRun[] | ListEnvelope<ResearchRun>>(
        `/api/marketing/research-runs/?brand_id=${brand.id}`,
      ),
      apiGet<InboxItem[] | ListEnvelope<InboxItem>>(
        `/api/marketing/engagement/items/?brand_id=${brand.id}`,
      ),
      apiGet<Connection[] | ListEnvelope<Connection>>("/api/marketing/social-accounts/"),
      apiGet<SavedReply[] | ListEnvelope<SavedReply>>("/api/marketing/engagement/saved-replies/"),
    ]);
    const nextRuns = rows(runPayload);
    const nextItems = rows(itemPayload);
    const nextConnections = rows(accountPayload).filter((item) => item.status === "CONNECTED");
    setRuns(nextRuns);
    setItems(nextItems);
    setConnections(nextConnections);
    setSavedReplies(rows(replyPayload));
    setSelectedConnection((current) => current || nextConnections[0]?.id || "");
    setSelectedItemId((current) =>
      current && nextItems.some((item) => item.id === current) ? current : (nextItems[0]?.id ?? ""),
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    load()
      .catch((cause: unknown) => {
        if (!cancelled)
          setError(cause instanceof Error ? cause.message : "Could not load Growth Engine.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const shouldPoll = useMemo(
    () =>
      runs.some((run) => ACTIVE_RESEARCH.has(run.status)) ||
      items.some((item) => ACTIVE_DRAFT.has(item.draft_status) || item.status === "SENDING"),
    [items, runs],
  );

  useEffect(() => {
    if (!shouldPoll) return;
    const timer = window.setInterval(() => void load().catch(() => undefined), 3000);
    return () => window.clearInterval(timer);
  }, [load, shouldPoll]);

  const selectedItem = items.find((item) => item.id === selectedItemId) ?? null;

  async function act<T>(key: string, request: () => Promise<T>, success: string) {
    setWorking(key);
    try {
      await request();
      toast.success(success);
      await load();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Action failed.");
    } finally {
      setWorking("");
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Autonomous social operating system"
        title="Growth Engine"
        subtitle={`Discover what is working, turn it into governed brand direction, and respond from one workspace for ${brand?.name || "this client"}.`}
        backTo="/"
      />

      <div className="mb-8 overflow-x-auto rounded-2xl border border-border bg-black px-4 py-4 text-white">
        <div className="flex min-w-max items-center gap-2" aria-label="Scaleezy operating loop">
          {LOOP.map((step, index) => (
            <div key={step} className="flex items-center gap-2">
              <span className="rounded-full border border-white/15 px-3 py-1.5 text-xs font-semibold tracking-wide uppercase">
                {index + 1}. {step}
              </span>
              {index < LOOP.length - 1 ? <span className="text-primary">→</span> : null}
            </div>
          ))}
        </div>
      </div>

      {error ? (
        <div className="mb-6 flex items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <CircleAlert className="size-5" /> {error}
        </div>
      ) : null}

      <Tabs defaultValue="research" className="space-y-6">
        <TabsList className="h-auto w-full justify-start rounded-xl bg-secondary p-1 sm:w-auto">
          <TabsTrigger value="research" className="gap-2 px-4 py-2.5">
            <Radar className="size-4" /> Research & inspirations
          </TabsTrigger>
          <TabsTrigger value="inbox" className="gap-2 px-4 py-2.5">
            <Inbox className="size-4" /> Engagement inbox
            {items.filter((item) => item.status === "NEW").length ? (
              <span className="rounded-full bg-primary px-1.5 text-[10px] text-primary-foreground">
                {items.filter((item) => item.status === "NEW").length}
              </span>
            ) : null}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="research">
          <ResearchPanel
            key={brand?.id ?? "loading"}
            brand={brand}
            runs={runs}
            loading={loading}
            working={working}
            act={act}
          />
        </TabsContent>

        <TabsContent value="inbox">
          <InboxPanel
            brandId={brand?.id ?? ""}
            connections={connections}
            selectedConnection={selectedConnection}
            setSelectedConnection={setSelectedConnection}
            items={items}
            selectedItem={selectedItem}
            setSelectedItemId={setSelectedItemId}
            savedReplies={savedReplies}
            working={working}
            act={act}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function ResearchPanel({
  brand,
  runs,
  loading,
  working,
  act,
}: {
  brand: BrandDto | null;
  runs: ResearchRun[];
  loading: boolean;
  working: string;
  act: <T>(key: string, request: () => Promise<T>, success: string) => Promise<void>;
}) {
  const guided = brand ? buildGuidedResearchText(brand) : { query: "", objectives: "" };
  const [query, setQuery] = useState(guided.query);
  const [objectives, setObjectives] = useState(guided.objectives);
  const [sources, setSources] = useState("");
  const latest = runs[0];

  const start = () =>
    act(
      "research",
      () =>
        apiPost("/api/marketing/research-runs/", {
          brand: brand?.id,
          query,
          objectives: objectives
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
          sources: sources
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
        }),
      "Research queued. Scaleezy will verify every cited source.",
    );

  return (
    <div className="grid gap-6 xl:grid-cols-[22rem_minmax(0,1fr)]">
      <section className="surface-card h-fit p-5 xl:sticky xl:top-6">
        <p className="label-eyebrow">Creative discovery</p>
        <h2 className="mt-2 text-2xl font-bold tracking-tight">Start with a ready brief.</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Scaleezy drafted this from Brand Master. Edit anything, or run it as-is to discover cited
          public references from any industry. You decide what enters Brand Master.
        </p>
        <div className="mt-5 space-y-4">
          <div>
            <Label htmlFor="research-query">What should Scaleezy find?</Label>
            <Textarea
              id="research-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Example: bold ecommerce launch posters in premium skincare, including unconventional references outside our industry"
              className="mt-2 min-h-28"
            />
          </div>
          <details className="rounded-xl border p-4">
            <summary className="cursor-pointer text-sm font-semibold">
              Fine-tune focus or preferred sources (optional)
            </summary>
            <div className="mt-4 space-y-4">
              <div>
                <Label htmlFor="research-objectives">Focus areas</Label>
                <Input
                  id="research-objectives"
                  value={objectives}
                  onChange={(event) => setObjectives(event.target.value)}
                  placeholder="layout, hook, product staging"
                  className="mt-2"
                />
              </div>
              <div>
                <Label htmlFor="research-sources">Preferred places</Label>
                <Input
                  id="research-sources"
                  value={sources}
                  onChange={(event) => setSources(event.target.value)}
                  placeholder="Leave blank to search the unrestricted public web"
                  className="mt-2"
                />
              </div>
            </div>
          </details>
          <Button
            className="w-full"
            disabled={!brand?.id || query.trim().length < 3 || working === "research"}
            onClick={start}
          >
            {working === "research" ? <Loader2 className="animate-spin" /> : <Search />}
            Find ideas for {brand?.name || "this brand"}
          </Button>
          <p className="text-xs leading-5 text-muted-foreground">
            References default to “rights unknown.” Scaleezy does not copy or grant rights to
            third-party work.
          </p>
        </div>
      </section>

      <section>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="label-eyebrow">Cited reference board</p>
            <h2 className="mt-1 text-2xl font-bold">Industry-wide inspiration</h2>
          </div>
          {latest ? <StatusBadge status={latest.status.replaceAll("_", " ")} /> : null}
        </div>
        {loading ? (
          <div className="surface-card p-10 text-center text-sm text-muted-foreground">
            Loading research…
          </div>
        ) : !latest ? (
          <div className="surface-card p-10 text-center">
            <Lightbulb className="mx-auto size-8 text-primary" />
            <p className="mt-3 font-semibold">Your first reference board starts here.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Describe anything you want to explore.
            </p>
          </div>
        ) : latest.error ? (
          <div className="surface-card border-destructive/30 p-5 text-sm text-destructive">
            {latest.error}
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {latest.findings.map((finding) => (
              <FindingCard key={finding.id} finding={finding} working={working} act={act} />
            ))}
            {!latest.findings.length ? (
              <div className="surface-card col-span-full p-10 text-center text-sm text-muted-foreground">
                {ACTIVE_RESEARCH.has(latest.status)
                  ? "Research is running in the background. You can leave this page."
                  : "No source passed verification. Try a broader query or route a web-enabled research provider."}
              </div>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}

function FindingCard({
  finding,
  working,
  act,
}: {
  finding: Finding;
  working: string;
  act: <T>(key: string, request: () => Promise<T>, success: string) => Promise<void>;
}) {
  const verified = finding.verification_status === "VERIFIED";
  return (
    <article className="surface-card overflow-hidden">
      <div className="aspect-[4/3] bg-black/5">
        {finding.preview_url ? (
          <img
            src={finding.preview_url}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            className="size-full object-cover"
          />
        ) : (
          <div className="grid size-full place-items-center text-muted-foreground">
            <Sparkles className="size-8" />
          </div>
        )}
      </div>
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <span className="text-xs font-semibold tracking-wide text-primary uppercase">
            {finding.kind.replaceAll("_", " ")}
          </span>
          <StatusBadge
            status={finding.verification_status}
            tone={verified ? "success" : "danger"}
          />
        </div>
        <h3 className="mt-2 line-clamp-2 font-semibold">{finding.title}</h3>
        <p className="mt-2 line-clamp-3 text-sm leading-6 text-muted-foreground">
          {finding.excerpt}
        </p>
        <a
          href={finding.source_url}
          target="_blank"
          rel="noreferrer"
          className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-primary"
        >
          {finding.source_name || finding.platform || "Open source"}{" "}
          <ArrowUpRight className="size-3.5" />
        </a>
        <div className="mt-4">
          <Select
            value={finding.rights_status}
            disabled={!!finding.adopted_inspiration}
            onValueChange={(rights_status) =>
              void act(
                `rights-${finding.id}`,
                () =>
                  apiPost(`/api/marketing/research-findings/${finding.id}/set-rights/`, {
                    rights_status,
                  }),
                "Rights status updated.",
              )
            }
          >
            <SelectTrigger aria-label="Rights status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="UNKNOWN">Rights unknown</SelectItem>
              <SelectItem value="PUBLIC_REFERENCE">Public reference only</SelectItem>
              <SelectItem value="OWNED">Owned by this client</SelectItem>
              <SelectItem value="LICENSED">Licensed for reuse</SelectItem>
              <SelectItem value="RESTRICTED">Restricted — do not use</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button
          variant={finding.adopted_inspiration ? "outline" : "default"}
          className="mt-3 w-full"
          disabled={
            !verified ||
            !!finding.adopted_inspiration ||
            working === `adopt-${finding.id}` ||
            finding.rights_status === "RESTRICTED"
          }
          onClick={() =>
            void act(
              `adopt-${finding.id}`,
              () => apiPost(`/api/marketing/research-findings/${finding.id}/adopt/`, {}),
              "Added to Brand Master Inspirations.",
            )
          }
        >
          {finding.adopted_inspiration ? <Check /> : <Lightbulb />}
          {finding.adopted_inspiration ? "In Brand Master" : "Use as inspiration"}
        </Button>
      </div>
    </article>
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
  working,
  act,
}: {
  brandId: string;
  connections: Connection[];
  selectedConnection: string;
  setSelectedConnection: (value: string) => void;
  items: InboxItem[];
  selectedItem: InboxItem | null;
  setSelectedItemId: (value: string) => void;
  savedReplies: SavedReply[];
  working: string;
  act: <T>(key: string, request: () => Promise<T>, success: string) => Promise<void>;
}) {
  const [response, setResponse] = useState("");

  useEffect(() => {
    setResponse(selectedItem?.approved_response || selectedItem?.ai_draft || "");
  }, [selectedItem?.id, selectedItem?.approved_response, selectedItem?.ai_draft]);

  const sync = () =>
    act(
      "sync",
      () =>
        apiPost("/api/marketing/engagement/sync-runs/", {
          brand: brandId,
          social_connection: selectedConnection,
        }),
      "Inbox sync queued. New items will appear here.",
    );

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="label-eyebrow">Governed customer engagement</p>
          <h2 className="mt-1 text-2xl font-bold">One inbox, clear ownership.</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Live sync currently supports X mentions and YouTube comments. Replies require human
            approval.
          </p>
        </div>
        <div className="flex min-w-0 flex-1 items-center gap-2 sm:max-w-xl">
          <Select value={selectedConnection} onValueChange={setSelectedConnection}>
            <SelectTrigger className="min-w-0 flex-1">
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
            disabled={!selectedConnection || working === "sync"}
            onClick={() => void sync()}
          >
            {working === "sync" ? <Loader2 className="animate-spin" /> : <RefreshCw />} Sync
          </Button>
        </div>
      </div>

      <div className="grid min-h-[34rem] overflow-hidden rounded-2xl border border-border bg-background lg:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="border-b border-border lg:border-r lg:border-b-0">
          <div className="border-b border-border p-4 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            {items.length} conversations
          </div>
          <div className="max-h-[36rem] overflow-y-auto">
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
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
              <div className="p-8 text-center text-sm text-muted-foreground">
                Sync a supported account to populate the inbox.
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
              {selectedItem.source_url ? (
                <Button asChild variant="ghost">
                  <a href={selectedItem.source_url} target="_blank" rel="noreferrer">
                    Open source <ArrowUpRight />
                  </a>
                </Button>
              ) : null}
            </div>

            <div className="mt-6 border-t border-border pt-5">
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="response">Response for approval</Label>
                {selectedItem.ai_provider_name ? (
                  <span className="text-xs text-muted-foreground">
                    Drafted by {selectedItem.ai_provider_name}
                  </span>
                ) : null}
              </div>
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
