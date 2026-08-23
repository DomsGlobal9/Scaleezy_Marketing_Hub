/**
 * Platform console data access, plus the handful of client-side endpoints the
 * universal layer added (natural-language notes, the Scaleezy library, own-site
 * enrichment, the team roster).
 *
 * Two worlds, one file, because they share the same envelope and the same
 * error shape — but they are gated very differently on the server:
 *
 * - `/api/platform/...` is reachable only by a PlatformAdmin. The `me` cache
 *   below is used ONLY to decide whether to SHOW the console; every request is
 *   re-checked server-side, so a stale or forged flag changes nothing.
 * - `/api/marketing/...` uses the normal tenant permissions. Nothing here sends
 *   a workspace id of its own — the X-Workspace-Id header is stamped by api().
 */
import { api, apiGet, apiPost } from "@/lib/api";
import { createAuthStore } from "@/lib/auth";

/* ------------------------------------------------------------------ identity */

export interface MeMembership {
  workspace_id: string;
  workspace_name: string;
  role: string;
  [key: string]: unknown;
}

export interface Me {
  id: number | string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  is_staff: boolean;
  is_platform_admin: boolean;
  memberships: MeMembership[];
}

const ME_PATH = "/api/auth/me/";
const isBrowser = () => typeof window !== "undefined";

let meCache: Promise<Me> | null = null;

// Any sign-in, sign-out or token rotation invalidates the cached identity, so
// the person who signs in next on this document never inherits the previous
// person's console link.
if (isBrowser()) {
  createAuthStore().subscribe(() => {
    meCache = null;
  });
}

/**
 * Who is signed in, cached for the life of the document. Resolves null off the
 * browser (no session there) and on any failure — callers treat null as
 * "not a platform admin", which is the safe default.
 */
export function fetchMe(options: { force?: boolean } = {}): Promise<Me | null> {
  if (!isBrowser()) return Promise.resolve(null);
  if (options.force || !meCache) {
    meCache = api<Me>(ME_PATH).catch((err: unknown) => {
      meCache = null;
      throw err;
    });
  }
  return meCache.catch(() => null);
}

export function clearMeCache() {
  meCache = null;
}

/* -------------------------------------------------------------------- health */

export interface HealthSignal {
  key: string;
  label: string;
  value: number | null;
  live: boolean;
  reason: string;
  actionable: boolean;
  display: string;
}

export interface PlatformHealth {
  signals: HealthSignal[];
  needs_attention: number;
  unmonitored: string[];
  generated_at: string;
}

export const fetchPlatformHealth = () => apiGet<PlatformHealth>("/api/platform/health/");

/* ------------------------------------------------------------------- signups */

export type BrandStatus = "PENDING" | "ACTIVE" | "ARCHIVED";

export interface SignupRow {
  brand_id: string;
  workspace_id: string;
  client_code: string;
  name: string;
  website: string;
  industry: string;
  status: BrandStatus | string;
  signed_up_at: string;
  signed_up_by: string;
  knowledge_sources: number;
  inspirations: number;
  team_size: number;
  reviewed_at: string | null;
  reviewed_by: string;
}

export interface SignupQueue {
  status: string;
  count: number;
  pending_total: number;
  signups: SignupRow[];
}

export const fetchSignups = (status: BrandStatus = "PENDING") =>
  apiGet<SignupQueue>(`/api/platform/signups/?status=${encodeURIComponent(status)}`);

export const approveSignup = (
  brandId: string,
  body: { name?: string; website?: string; plan?: string },
) => apiPost<SignupRow>(`/api/platform/signups/${brandId}/approve/`, body);

export const rejectSignup = (brandId: string, reason: string) =>
  apiPost<SignupRow>(`/api/platform/signups/${brandId}/reject/`, { reason });

export interface AttachUserResult {
  membership_id: string;
  role: string;
  status: string;
  /**
   * Other workspaces where this person is the sole member and the client was
   * never approved — the LIKELY duplicate signups. Reported for the operator
   * to archive deliberately; attach-user never archives anything itself.
   */
  duplicate_candidates: Array<{
    workspace_id: string;
    client_code: string;
    name: string;
    approval_status: string;
  }>;
}

export const attachUserToClient = (workspaceId: string, username: string, role: string) =>
  apiPost<AttachUserResult>(`/api/platform/clients/${workspaceId}/attach-user/`, {
    username,
    role,
  });

/* ------------------------------------------------------------------- clients */

export interface UsageCapability {
  capability: string;
  label: string;
  used: number;
  limit: number;
  remaining: number | null;
  overridden: boolean;
}

/** quota.summary(workspace) verbatim. Unsubscribed workspaces carry only the verdict. */
export interface UsageSummary {
  subscribed: boolean;
  plan: { key: string; name: string; description?: string; price?: string } | null;
  capabilities?: UsageCapability[];
  status?: string;
  period_start?: string;
  period_end?: string;
  generations_used?: number;
  generations_limit?: number;
  generations_remaining?: number | null;
  spend?: string;
  spend_cap?: string;
  spend_remaining?: string | null;
  allowed?: boolean;
  code?: string;
  message?: string;
}

export type ClientFlag =
  | "PENDING_APPROVAL"
  | "NO_AI_ROUTING"
  | "OVER_QUOTA"
  | "SPEND_CAP_REACHED"
  | "NEVER_GENERATED"
  | "INACTIVE"
  | "FAILING_PUBLISHES"
  | "SUSPENDED"
  | "ARCHIVED"
  | "BRAIN_STALE";

export interface ClientRow {
  workspace_id: string;
  client_code: string;
  name: string;
  status: "ACTIVE" | "SUSPENDED" | "ARCHIVED" | string;
  status_reason: string;
  created_at: string;
  brand: { id: string; name: string; status: string; industry: string; website: string } | null;
  plan: { key: string; name: string } | null;
  subscription_status: string | null;
  onboarding: { current_stage: string; status: string } | null;
  readiness: { score: number; level: string } | null;
  counts: {
    knowledge_sources: number;
    confirmed_facts: number;
    inspirations: number;
    rules: number;
    preferences: number;
    team: number;
  };
  content: { total: number; by_status: Record<string, number> };
  publishing: { published: number; failed: number; scheduled: number; queued: number };
  usage: UsageSummary;
  last_active_at: string | null;
  flags: Array<ClientFlag | string>;
}

export interface ClientList {
  count: number;
  filter: string;
  days: number;
  clients: ClientRow[];
}

export interface ClientDetail {
  client: ClientRow;
  brain: {
    compiled_at: string | null;
    version: string;
    last_error: string;
    stale: boolean;
  } | null;
  onboarding: Record<string, unknown> | null;
  recent_content: Array<Record<string, unknown>>;
  recent_publishing: Array<Record<string, unknown>>;
  recent_ai_calls: Array<Record<string, unknown>>;
  team: Array<Record<string, unknown>>;
  audit: Array<Record<string, unknown>>;
  universal: { standards_enabled: boolean; inspirations_enabled: boolean };
}

export const fetchClients = (params: { filter?: string; days?: number; q?: string } = {}) => {
  const search = new URLSearchParams();
  if (params.filter) search.set("filter", params.filter);
  if (params.days) search.set("days", String(params.days));
  if (params.q) search.set("q", params.q);
  const qs = search.toString();
  return apiGet<ClientList>(`/api/platform/clients/${qs ? `?${qs}` : ""}`);
};

export const fetchClient = (workspaceId: string) =>
  apiGet<ClientDetail>(`/api/platform/clients/${workspaceId}/`);

export const setClientLimits = (workspaceId: string, limits: Record<string, number>) =>
  apiPost<{ usage: UsageSummary }>(`/api/platform/clients/${workspaceId}/limits/`, { limits });

export const suspendClient = (workspaceId: string, reason: string) =>
  apiPost<{ status: string }>(`/api/platform/clients/${workspaceId}/suspend/`, { reason });

export const reactivateClient = (workspaceId: string, reason: string) =>
  apiPost<{ status: string }>(`/api/platform/clients/${workspaceId}/reactivate/`, { reason });

export const archiveClient = (workspaceId: string, reason: string) =>
  apiPost<{ status: string }>(`/api/platform/clients/${workspaceId}/archive/`, { reason });

export const setClientUniversal = (
  workspaceId: string,
  body: { standards?: boolean; inspirations?: boolean },
) => apiPost<unknown>(`/api/platform/clients/${workspaceId}/universal/`, body);

export const setClientPlan = (workspaceId: string, plan: string) =>
  apiPost<unknown>(`/api/platform/clients/${workspaceId}/plan/`, { plan });

export const setClientSpendCap = (workspaceId: string, spendCap: string) =>
  apiPost<unknown>(`/api/platform/clients/${workspaceId}/spend-cap/`, { spend_cap: spendCap });

export const recompileClientBrain = (workspaceId: string) =>
  apiPost<unknown>(`/api/platform/clients/${workspaceId}/recompile-brain/`, {});

/* ----------------------------------------------------------------- standards */

export type UniversalScope = "GLOBAL" | "INDUSTRY" | "CHANNEL" | "CONTENT_TYPE";
export type LifecycleStatus = "DRAFT" | "PUBLISHED" | "RETIRED";

export interface UniversalStandard {
  id: string;
  title: string;
  rationale: string;
  category: string;
  attribute: string;
  value: string;
  guidance: string;
  scope: UniversalScope | string;
  scope_value: string;
  status: LifecycleStatus | string;
  supersedes?: string | null;
  authored_by?: string | null;
  published_at: string | null;
  retired_at: string | null;
  created_at: string;
  /** Not every server build sends it; fall back to created_at when absent. */
  updated_at?: string | null;
}

export interface StandardInput {
  title: string;
  rationale: string;
  category: string;
  attribute: string;
  value: string;
  guidance: string;
  scope: UniversalScope;
  scope_value: string;
}

export interface StandardPreview {
  standard?: UniversalStandard;
  matched_brand_count: number;
  total_active_brands: number;
  brands: Array<Record<string, unknown>>;
  exact_match_only: boolean;
  note: string;
}

/**
 * List endpoints are read tolerantly: a bare array, `{<key>: [...]}` or a DRF
 * page all become rows, so a wording difference on the server is not a blank
 * screen here.
 */
function rows<T>(payload: unknown, key: string): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === "object") {
    const inner = payload as Record<string, unknown>;
    const named = inner[key];
    if (Array.isArray(named)) return named as T[];
    const results = inner["results"];
    if (Array.isArray(results)) return results as T[];
  }
  return [];
}

export const fetchStandards = async () =>
  rows<UniversalStandard>(await apiGet<unknown>("/api/platform/standards/"), "standards");

export const createStandard = (input: StandardInput) =>
  apiPost<unknown>("/api/platform/standards/", input);

export const updateStandard = (id: string, input: Partial<StandardInput>) =>
  api<unknown>(`/api/platform/standards/${id}/`, { method: "PATCH", body: input });

export const publishStandard = (id: string) =>
  apiPost<unknown>(`/api/platform/standards/${id}/publish/`, {});

export const retireStandard = (id: string, reason: string) =>
  apiPost<unknown>(`/api/platform/standards/${id}/retire/`, { reason });

export const previewStandard = (id: string) =>
  apiGet<StandardPreview>(`/api/platform/standards/${id}/preview/`);

/* ------------------------------------------------------------ learned patterns */

export interface LearnedPattern {
  id: string;
  category: string;
  attribute: string;
  value: string;
  industry: string;
  channel: string;
  contributor_count: number;
  supporting_brand_count: number;
  confidence: number;
  status: LifecycleStatus | string;
  compiled_at: string;
  pattern_version: string;
  published_at: string | null;
  retired_at: string | null;
}

export interface PatternContributor {
  workspace_id: string;
  client_code: string;
  name: string;
}

export const fetchLearnedPatterns = async () =>
  rows<LearnedPattern>(await apiGet<unknown>("/api/platform/patterns/"), "patterns");

export const compileLearnedPatterns = () =>
  apiPost<{ status: string; task_id: string; pattern_version: string | null }>(
    "/api/platform/patterns/compile/",
    {},
  );

export const publishLearnedPattern = (id: string) =>
  apiPost<unknown>(`/api/platform/patterns/${id}/publish/`, {});

export const retireLearnedPattern = (id: string, reason: string) =>
  apiPost<unknown>(`/api/platform/patterns/${id}/retire/`, { reason });

export const fetchPatternContributors = (id: string) =>
  apiGet<{ pattern_id: string; contributors: PatternContributor[] }>(
    `/api/platform/patterns/${id}/contributors/`,
  );

/* ------------------------------------------------------------------- library */

export interface PlatformInspiration {
  id: string;
  title: string;
  reference_url: string;
  annotation: string;
  tags: string[];
  industry: string;
  channel: string;
  status: LifecycleStatus | string;
  curated_by?: string | null;
  published_at: string | null;
  created_at: string;
  updated_at?: string | null;
  adoption_count?: number;
}

export interface PlatformInspirationInput {
  title: string;
  reference_url: string;
  annotation: string;
  tags: string[];
  industry: string;
  channel: string;
}

export const fetchPlatformInspirations = async () =>
  rows<PlatformInspiration>(await apiGet<unknown>("/api/platform/inspirations/"), "inspirations");

export const createPlatformInspiration = (input: PlatformInspirationInput) =>
  apiPost<unknown>("/api/platform/inspirations/", input);

export const updatePlatformInspiration = (id: string, input: Partial<PlatformInspirationInput>) =>
  api<unknown>(`/api/platform/inspirations/${id}/`, { method: "PATCH", body: input });

export const publishPlatformInspiration = (id: string) =>
  apiPost<unknown>(`/api/platform/inspirations/${id}/publish/`, {});

export const retirePlatformInspiration = (id: string, reason: string) =>
  apiPost<unknown>(`/api/platform/inspirations/${id}/retire/`, { reason });

/* -------------------------------------------------------------------- admins */

export interface PlatformAdminRow {
  user_id: number | string;
  username: string;
  email: string;
  is_active: boolean;
  note: string;
  granted_at: string | null;
  granted_by: string;
  revoked_at: string | null;
}

export const fetchPlatformAdmins = async () =>
  rows<PlatformAdminRow>(await apiGet<unknown>("/api/platform/admins/"), "admins");

export const grantPlatformAdmin = (username: string, note: string) =>
  apiPost<unknown>("/api/platform/admins/", { username, note });

export const revokePlatformAdmin = (userId: number | string) =>
  apiPost<unknown>(`/api/platform/admins/${userId}/revoke/`, {});

/* -------------------------------------------------------- client: NL notes */

export interface NoteProposal {
  kind: string;
  category: string;
  attribute: string;
  value: string;
  text: string;
  quote: string;
  accepted: boolean;
}

export interface NoteResult {
  note_id: string;
  note_text: string;
  proposals: NoteProposal[];
  note: string;
}

export interface AcceptProposalResult {
  kind: string;
  id: string;
  message: string;
}

export const submitBrandNote = (brandId: string, text: string) =>
  apiPost<NoteResult>(`/api/marketing/brands/${brandId}/notes/`, { text });

export const acceptNoteProposal = (brandId: string, noteId: string, proposal: NoteProposal) =>
  apiPost<AcceptProposalResult>(`/api/marketing/brands/${brandId}/notes/${noteId}/accept/`, {
    proposal,
  });

/* --------------------------------------------------------- client: library */

export interface LibraryItem {
  id: string;
  title: string;
  reference_url: string;
  annotation: string;
  tags: string[];
  industry: string;
  channel: string;
}

/**
 * `/api/marketing/inspirations/library/` is also registered, but the
 * inspirations router is included before the universal module and its detail
 * route (`inspirations/<pk>/`) claims "library" as a pk. The `universal/`
 * spelling resolves to the same views and nothing else owns it.
 */
const LIBRARY_PATH = "/api/marketing/universal/library/";

export const fetchLibraryGallery = async () =>
  rows<LibraryItem>(await apiGet<unknown>(LIBRARY_PATH), "inspirations");

export interface AdoptResult {
  inspiration_id: string;
  platform_inspiration_id: string;
  brand_id: string;
  created: boolean;
}

export const adoptLibraryItem = (itemId: string, brandId: string) =>
  apiPost<AdoptResult>(`${LIBRARY_PATH}${itemId}/adopt/`, { brand_id: brandId });

/* ------------------------------------------------------ client: enrichment */

export interface EnrichReport {
  skipped: boolean;
  reason?: string;
  host?: string;
  pages_fetched: number;
  pages_unchanged?: number;
  sources_created?: Array<Record<string, unknown> | string>;
  errors?: Array<Record<string, unknown> | string>;
  note?: string;
}

export const enrichBrandFromSite = (brandId: string) =>
  apiPost<EnrichReport>(`/api/marketing/brands/${brandId}/enrich/`, {});

/* ------------------------------------------------------------ client: team */

export interface TeamMember {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: string;
  rank: number;
  status: string;
  last_active_at: string | null;
  invited_by_username: string;
  created_at: string;
}

export interface TeamPermissions {
  roles: Array<{ role: string; rank: number }>;
  capabilities: Array<{
    key: string;
    label: string;
    minimum_role: string;
    granted_to: string[];
  }>;
}

export interface TeamData {
  members: TeamMember[];
  permissions: TeamPermissions;
  can_invite: boolean;
  invite_note: string;
}

export const fetchTeam = () => apiGet<TeamData>("/api/marketing/team/");

export const setTeamRole = (memberId: string, role: string) =>
  apiPost<unknown>(`/api/marketing/team/${memberId}/role/`, { role });

export const suspendTeamMember = (memberId: string) =>
  apiPost<unknown>(`/api/marketing/team/${memberId}/suspend/`, {});

export const reactivateTeamMember = (memberId: string) =>
  apiPost<unknown>(`/api/marketing/team/${memberId}/reactivate/`, {});

export const removeTeamMember = (memberId: string) =>
  api<unknown>(`/api/marketing/team/${memberId}/`, { method: "DELETE" });

/* ------------------------------------------------------------------ helpers */

export const errorText = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** "3 days ago" style, for last-active columns. Empty input stays honest: "never". */
export function formatAgo(value: string | null | undefined): string {
  if (!value) return "never";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return String(value);
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 60) return `${days} d ago`;
  const months = Math.round(days / 30);
  return `${months} mo ago`;
}
