/**
 * Brand Master data access.
 *
 * Every tab reads and writes the endpoint its own layer already shipped —
 * knowledge through the knowledge API, inspirations through the inspirations
 * API, rules through the learning API, the guided setup through onboarding.
 * Only the overview is Brand Master's own, because nothing else answers "how
 * well does Scaleezy understand this brand?".
 *
 * No workspace is sent from here. The backend resolves it from the session and
 * authorises the brand against it, so the browser never gets to assert which
 * tenant's intelligence it is allowed to see.
 */
import { api, apiFetch } from "@/lib/api";

export type ReadinessLevel = "STARTING" | "LEARNING" | "STRONG" | "READY";

export interface ReadinessDimension {
  key: string;
  label: string;
  weight: number;
  score: number;
  earned: number;
  complete: boolean;
  hint: string;
}

export interface Readiness {
  readiness_score: number;
  readiness_level: ReadinessLevel;
  completed_dimensions: string[];
  missing_dimensions: string[];
  dimensions: ReadinessDimension[];
  recommended_next_action: { key: string; label: string; detail: string };
  counts: {
    sources: number;
    memories: number;
    inspirations: number;
    inspiration_signals: number;
    preferences: number;
    rules: number;
    unresolved_conflicts: number;
  };
}

export interface BrandConflictClaim {
  source_type?: string;
  source_id?: string;
  value?: string;
  memory_type?: string;
  authority?: string;
}

export interface BrandConflict {
  category: string;
  attribute: string;
  authority: string;
  reason: string;
  claims: BrandConflictClaim[];
}

export interface BrainRule {
  id: string;
  text: string;
  priority: number;
  scope: string;
  origin: string;
}

export interface BrainClaim {
  category: string;
  attribute: string;
  value: string;
  sentiment: string;
  authority: string;
  source_type: string;
  source_id: string;
  confidence: number;
  weight: number;
}

export interface BrandMasterOverview {
  brand: {
    id: string;
    name: string;
    industry: string;
    tagline: string;
    brand_tone: string;
    logo_url: string;
    palette: Record<string, string>;
    status: string;
  };
  readiness: Readiness;
  brain: {
    compiled: boolean;
    brain_version: string;
    schema_version: number | null;
    compiled_at: string | null;
    positioning: { statements?: string[]; competitors?: string[] };
    unresolved_conflict_count: number;
  };
  conflicts: BrandConflict[];
}

export interface BrandBrain {
  schema_version: number;
  brain_version: string;
  compiled_at: string;
  identity: {
    name: string;
    industry: string;
    tagline: string;
    cta_keyword?: string;
    has_logo?: boolean;
    canon?: string[];
  };
  positioning: { statements?: string[]; competitors?: string[] };
  audiences: { pains?: string[]; objections?: string[] };
  voice: { tone: string; claims?: BrainClaim[] };
  visual_language: {
    palette?: Record<string, string>;
    fonts?: Record<string, string>;
    layout_preference?: string;
    claims?: BrainClaim[];
  };
  verified_product_truth: string[];
  hard_rules: BrainRule[];
  soft_rules: BrainRule[];
  preferences: BrainClaim[];
  win_patterns: string[];
  avoid_patterns: string[];
  unresolved_conflict_count: number;
  conflicts: BrandConflict[];
}

export interface KnowledgeSource {
  id: string;
  title: string;
  source_type: string;
  status: string;
  file_name: string | null;
  file_url: string | null;
  source_url: string | null;
  raw_text?: string | null;
  created_at: string;
  updated_at: string;
}

export type MemoryStatus = "CANDIDATE" | "CONFIRMED" | "REJECTED" | "SUPERSEDED" | "EXPIRED";

export interface BrandMemoryRow {
  id: string;
  source: string | null;
  memory_type: string;
  content: string;
  status: MemoryStatus;
  confidence: number;
  created_at: string;
}

export interface Inspiration {
  id: string;
  title: string;
  inspiration_type: string;
  annotation: string;
  reference_url: string | null;
  file_url: string | null;
  mime_type?: string | null;
  external_platform: string;
  usage_scope: string;
  focus_areas: string[];
  analysis_status: string;
  lifecycle_status: string;
  retrieval_eligibility: { eligible: boolean; reason: string };
  created_at: string;
}

export type SignalSentiment = "LIKED" | "DISLIKED" | "NEUTRAL";

export interface InspirationSignalRow {
  id: string;
  inspiration: string;
  category: string;
  attribute: string;
  value: string;
  sentiment: SignalSentiment;
  origin: "USER" | "AI";
  user_confirmation: "CONFIRMED" | "PENDING" | "REJECTED";
  weight: number;
  confidence: number;
  superseded_at?: string | null;
  retrieval_eligibility: { eligible: boolean; reason: string };
}

export interface BrandPreferenceRow {
  id: string;
  category: string;
  attribute: string;
  value: string;
  state: "EMERGING" | "ESTABLISHED" | "RETIRED";
  evidence_count: number;
  evidence_event_ids: string[];
  weight: number;
  confidence: number;
}

export interface BrandRuleRow {
  id: string;
  text: string;
  hardness: "HARD" | "SOFT";
  origin: "EXPLICIT" | "LEARNED";
  priority: number;
  scope: string;
  is_active: boolean;
  evidence_event_ids: string[];
  created_at: string;
}

export interface LearningEventRow {
  id: string;
  event_type: string;
  outcome: string;
  subject_type: string;
  created_at: string;
  context: Record<string, unknown>;
}

export interface CurrentBrand {
  id: string;
  name: string;
}

export interface CalibrationDirection {
  id: string;
  label: string;
  tests_dimension: string;
  headline: string;
  caption: string;
  preview_url: string;
  verdict: "PENDING" | "LIKED" | "NOT_US" | "ADJUSTED";
  adjustment_note?: string;
}

export type OnboardingStage =
  "BASICS" | "KNOWLEDGE" | "INSPIRATIONS" | "CALIBRATION" | "FIRST_GENERATION" | "DONE";

export interface OnboardingSummary {
  onboarding: {
    current_stage: OnboardingStage;
    status: string;
    skipped_steps: string[];
  };
  readiness: Readiness;
  calibration: CalibrationDirection[];
  /** Brand.status as the server sees it; PENDING until Scaleezy approves. */
  brand_status?: string;
  /** True while the brand is PENDING: calibration and generation stay locked. */
  awaiting_approval?: boolean;
}

/* ------------------------------------------------------------- vocabularies */

/** Knowledge source types the backend accepts (apps.knowledge.BrandSource). */
export const SOURCE_TYPES: Array<{ value: string; label: string; kind: "file" | "text" | "url" }> =
  [
    { value: "TRANSCRIPT", label: "Meeting transcript", kind: "text" },
    { value: "MOM", label: "Minutes of meeting", kind: "text" },
    { value: "CUSTOMER_CALL", label: "Customer / client call", kind: "text" },
    { value: "SALES_CALL", label: "Sales call", kind: "text" },
    { value: "NOTE", label: "Founder / team notes", kind: "text" },
    { value: "PRODUCT_DOC", label: "Product or service document", kind: "file" },
    { value: "DOCUMENT", label: "Brand guidelines / deck / document", kind: "file" },
    { value: "PDF", label: "PDF", kind: "file" },
    { value: "EMAIL_EXPORT", label: "Email export", kind: "file" },
    { value: "WEBSITE", label: "Website", kind: "url" },
    { value: "URL", label: "Web page / link", kind: "url" },
    { value: "OTHER", label: "Other", kind: "file" },
  ];

/** Memory types a person can capture by hand (apps.knowledge.BrandMemory). */
export const MEMORY_TYPES: Array<{ value: string; label: string }> = [
  { value: "FACT", label: "Fact" },
  { value: "PRODUCT_TRUTH", label: "Product / service truth" },
  { value: "BRAND_CANON", label: "Brand canon" },
  { value: "POSITIONING_SIGNAL", label: "Positioning" },
  { value: "BUYER_PAIN", label: "Audience pain" },
  { value: "OBJECTION", label: "Objection" },
  { value: "FOUNDER_POV", label: "Founder point of view" },
  { value: "EVIDENCE", label: "Proof / evidence" },
  { value: "DECISION", label: "Decision" },
  { value: "CAMPAIGN_CONTEXT", label: "Campaign context" },
];

export const INSPIRATION_LINK_TYPES: Array<{ value: string; label: string }> = [
  { value: "POST", label: "Social post" },
  { value: "REEL", label: "Reel / short video" },
  { value: "VIDEO", label: "Video" },
  { value: "AD", label: "Advertisement" },
  { value: "PIN", label: "Pinterest pin" },
  { value: "WEB_PAGE", label: "Web page" },
  { value: "COMPETITOR", label: "Competitor reference" },
  { value: "REFERENCE", label: "General reference" },
  { value: "URL", label: "Link" },
  { value: "OTHER", label: "Other" },
];

export const INSPIRATION_UPLOAD_TYPES: Array<{ value: string; label: string }> = [
  { value: "IMAGE", label: "Image" },
  { value: "SCREENSHOT", label: "Screenshot" },
  { value: "MOODBOARD", label: "Moodboard" },
  { value: "AD", label: "Advertisement" },
  { value: "COMPETITOR", label: "Competitor reference" },
];

/** Signal categories (apps.inspirations.SignalCategory). */
export const SIGNAL_CATEGORIES: Array<{ value: string; label: string }> = [
  { value: "TYPOGRAPHY", label: "Typography" },
  { value: "COLOR", label: "Colour" },
  { value: "LAYOUT", label: "Layout" },
  { value: "COMPOSITION", label: "Composition" },
  { value: "IMAGERY", label: "Imagery" },
  { value: "PHOTOGRAPHY", label: "Photography" },
  { value: "ILLUSTRATION", label: "Illustration" },
  { value: "MOTION", label: "Motion" },
  { value: "PACING", label: "Pacing" },
  { value: "TONE", label: "Tone of voice" },
  { value: "COPY_STYLE", label: "Copy style" },
  { value: "HOOK", label: "Hook" },
  { value: "CTA", label: "Call to action" },
  { value: "STRUCTURE", label: "Structure" },
  { value: "MOOD", label: "Mood" },
  { value: "BRANDING", label: "Branding" },
  { value: "OTHER", label: "Other" },
];

/* ------------------------------------------------------------------ helpers */

/** DRF list endpoints return a bare array; tolerate a paginated shape too. */
function asList<T>(payload: unknown): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === "object") {
    const inner = payload as { results?: T[] };
    if (Array.isArray(inner.results)) return inner.results;
  }
  return [];
}

/**
 * Multipart POST. `apiFetch` rather than `api()` so the browser writes the
 * boundary itself; the envelope is unwrapped here the same way `api()` does.
 */
export async function postMultipart<T>(path: string, form: FormData): Promise<T> {
  const res = await apiFetch(path, { method: "POST", body: form });
  const json = (await res.json().catch(() => null)) as {
    success?: boolean;
    data?: T;
    message?: string;
    error?: unknown;
  } | null;
  if (!res.ok || json?.success === false) {
    const error = json?.error as { message?: string } | Record<string, string[]> | undefined;
    const firstField =
      error && typeof error === "object" && !("message" in error)
        ? Object.values(error as Record<string, string[]>)[0]?.[0]
        : undefined;
    throw new Error(
      (error as { message?: string } | undefined)?.message ||
        firstField ||
        json?.message ||
        `Upload failed (${res.status}).`,
    );
  }
  return (json?.data ?? json) as T;
}

/* ----------------------------------------------------------------- overview */

export const fetchCurrentBrand = () => api<CurrentBrand>("/api/marketing/brands/current/");

export const fetchOverview = (brandId: string) =>
  api<BrandMasterOverview>(`/api/marketing/brand-master/${brandId}/`);

export const fetchBrain = (brandId: string) =>
  api<BrandBrain>(`/api/marketing/brand-master/${brandId}/brain/`);

export const rebuildBrain = (brandId: string) =>
  api<{ brain_version: string; compiled_at: string; unresolved_conflict_count: number }>(
    `/api/marketing/brand-master/${brandId}/rebuild-brain/`,
    { method: "POST" },
  );

/* ---------------------------------------------------------------- knowledge */

export const fetchKnowledge = async (brandId: string) =>
  asList<KnowledgeSource>(await api(`/api/marketing/knowledge/sources/?brand_id=${brandId}`));

export const createTextSource = (
  brandId: string,
  input: { source_type: string; title: string; raw_text?: string; source_url?: string },
) =>
  api<KnowledgeSource>("/api/marketing/knowledge/sources/", {
    method: "POST",
    body: { brand: brandId, ...input },
  });

export const uploadSource = (
  brandId: string,
  file: File,
  input: { source_type: string; title: string },
) => {
  const form = new FormData();
  form.append("brand", brandId);
  form.append("file", file);
  form.append("source_type", input.source_type);
  if (input.title) form.append("title", input.title);
  return postMultipart<KnowledgeSource>("/api/marketing/knowledge/sources/upload/", form);
};

export const revokeSource = (sourceId: string) =>
  api(`/api/marketing/knowledge/sources/${sourceId}/revoke/`, { method: "POST" });

export const fetchMemories = async (brandId: string) =>
  asList<BrandMemoryRow>(await api(`/api/marketing/knowledge/memories/?brand_id=${brandId}`));

export const createMemory = (
  brandId: string,
  input: { source?: string | null; memory_type: string; content: string },
) =>
  api<BrandMemoryRow>("/api/marketing/knowledge/memories/", {
    method: "POST",
    body: { brand: brandId, ...input },
  });

export const confirmMemory = (memoryId: string) =>
  api(`/api/marketing/knowledge/memories/${memoryId}/confirm/`, { method: "POST" });

export const rejectMemory = (memoryId: string) =>
  api(`/api/marketing/knowledge/memories/${memoryId}/reject/`, { method: "POST" });

/* ------------------------------------------------------------- inspirations */

export const fetchInspirations = async (brandId: string) =>
  asList<Inspiration>(await api(`/api/marketing/inspirations/?brand_id=${brandId}`));

export const fetchSignals = async (brandId: string) =>
  asList<InspirationSignalRow>(
    await api(`/api/marketing/inspiration-signals/?brand_id=${brandId}`),
  );

export interface InspirationInput {
  title: string;
  inspiration_type: string;
  annotation: string;
  external_platform: string;
  usage_scope: "FULL_REFERENCE" | "SPECIFIC_ELEMENTS";
  focus_areas: string[];
}

export const createInspiration = (
  brandId: string,
  input: InspirationInput & { reference_url: string },
) =>
  api<Inspiration>("/api/marketing/inspirations/", {
    method: "POST",
    body: { brand: brandId, ...input },
  });

export const uploadInspiration = (brandId: string, file: File, input: InspirationInput) => {
  const form = new FormData();
  form.append("brand", brandId);
  form.append("file", file);
  form.append("inspiration_type", input.inspiration_type);
  if (input.title) form.append("title", input.title);
  form.append("annotation", input.annotation);
  form.append("external_platform", input.external_platform);
  form.append("usage_scope", input.usage_scope);
  for (const area of input.focus_areas) form.append("focus_areas", area);
  return postMultipart<Inspiration>("/api/marketing/inspirations/upload/", form);
};

export const archiveInspiration = (inspirationId: string) =>
  api(`/api/marketing/inspirations/${inspirationId}/archive/`, { method: "POST" });

export const createSignal = (input: {
  inspiration: string;
  category: string;
  attribute: string;
  value: string;
  sentiment: SignalSentiment;
}) =>
  api<InspirationSignalRow>("/api/marketing/inspiration-signals/", {
    method: "POST",
    body: input,
  });

export const confirmSignal = (signalId: string) =>
  api(`/api/marketing/inspiration-signals/${signalId}/confirm/`, { method: "POST" });

export const rejectSignal = (signalId: string) =>
  api(`/api/marketing/inspiration-signals/${signalId}/reject/`, { method: "POST" });

/* --------------------------------------------------------- learning + rules */

export const fetchPreferences = async (brandId: string) =>
  asList<BrandPreferenceRow>(await api(`/api/marketing/brand-preferences/?brand_id=${brandId}`));

export const retirePreference = (preferenceId: string) =>
  api(`/api/marketing/brand-preferences/${preferenceId}/retire/`, { method: "POST" });

export const fetchLearningEvents = async (brandId: string) =>
  asList<LearningEventRow>(await api(`/api/marketing/learning-events/?brand_id=${brandId}`));

export const fetchRules = async (brandId: string) =>
  asList<BrandRuleRow>(await api(`/api/marketing/brand-rules/?brand_id=${brandId}`));

export const createRule = (brandId: string, input: { text: string; hardness: "HARD" | "SOFT" }) =>
  api<BrandRuleRow>("/api/marketing/brand-rules/", {
    method: "POST",
    body: { brand: brandId, ...input },
  });

export const deactivateRule = (ruleId: string) =>
  api(`/api/marketing/brand-rules/${ruleId}/deactivate/`, { method: "POST" });

/* ----------------------------------------------------- guided setup (PR6) */

export const fetchOnboarding = (brandId: string) =>
  api<OnboardingSummary>(`/api/marketing/onboarding/${brandId}/`);

export const skipOnboardingStage = (brandId: string, stage: string) =>
  api<OnboardingSummary>(`/api/marketing/onboarding/${brandId}/skip/`, {
    method: "POST",
    body: { stage },
  });

export const runCalibration = (brandId: string) =>
  api(`/api/marketing/onboarding/${brandId}/calibrate/`, { method: "POST" });

export const reactToDirection = (
  directionId: string,
  reaction: "like" | "not_us" | "adjust",
  note = "",
) =>
  api<{ learned: boolean; summary: OnboardingSummary }>(
    `/api/marketing/calibration-directions/${directionId}/react/`,
    { method: "POST", body: { reaction, note } },
  );

/* --------------------------------------------------------------------- copy */

export const READINESS_COPY: Record<ReadinessLevel, { label: string; blurb: string }> = {
  STARTING: {
    label: "Starting out",
    blurb: "Scaleezy knows the basics. Feed it more and the work gets sharper.",
  },
  LEARNING: {
    label: "Learning",
    blurb: "Enough to be useful, not yet enough to sound like you every time.",
  },
  STRONG: {
    label: "Strong",
    blurb: "Scaleezy has a real picture of this brand.",
  },
  READY: {
    label: "Ready",
    blurb: "Scaleezy understands this brand well enough to work unsupervised.",
  },
};

/** Brand Master tabs. Kept in the URL so every card and link can target one. */
export type BrandMasterTab =
  | "overview"
  | "basics"
  | "products"
  | "knowledge"
  | "inspirations"
  | "learning"
  | "rules"
  | "brain"
  | "attention"
  | "teach";

export const BRAND_MASTER_TABS: BrandMasterTab[] = [
  "overview",
  "basics",
  "products",
  "knowledge",
  "inspirations",
  "learning",
  "rules",
  "brain",
  "attention",
  "teach",
];

/** Where the readiness engine's "do this next" actually lives. */
export function tabForReadinessKey(key: string): BrandMasterTab | "create" {
  switch (key) {
    case "identity":
    case "voice":
      return "basics";
    // What the brand sells and who for is now its own surface, so the
    // readiness engine's audience gap points at the fields that close it.
    case "audience":
    case "products":
      return "products";
    case "knowledge":
    case "positioning":
      return "knowledge";
    case "visual_language":
    case "inspirations":
      return "inspirations";
    case "learning":
      return "teach";
    case "resolve_conflicts":
      return "attention";
    case "generate":
      return "create";
    default:
      return "teach";
  }
}

export const humanize = (value: string | null | undefined) =>
  (value ?? "").replaceAll("_", " ").toLowerCase();
