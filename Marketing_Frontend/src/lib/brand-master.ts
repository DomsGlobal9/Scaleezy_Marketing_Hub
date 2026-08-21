/**
 * Brand Master data access.
 *
 * Every tab reads the endpoint its own layer already shipped — knowledge from
 * the knowledge API, inspirations from the inspirations API, and so on. Only
 * the overview is new, because nothing else answers "how well does Scaleezy
 * understand this brand?".
 *
 * No workspace is sent from here. The backend resolves it from the session and
 * authorises the brand against it, so the browser never gets to assert which
 * tenant's intelligence it is allowed to see.
 */
import { api } from "@/lib/api";

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
  identity: { name: string; industry: string; tagline: string; canon?: string[] };
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
  created_at: string;
  updated_at: string;
}

export interface Inspiration {
  id: string;
  title: string;
  inspiration_type: string;
  annotation: string;
  reference_url: string | null;
  file_url: string | null;
  external_platform: string;
  usage_scope: string;
  focus_areas: string[];
  analysis_status: string;
  lifecycle_status: string;
  retrieval_eligibility: { eligible: boolean; reason: string };
  created_at: string;
}

export interface InspirationSignalRow {
  id: string;
  inspiration: string;
  category: string;
  attribute: string;
  value: string;
  sentiment: "LIKED" | "DISLIKED" | "NEUTRAL";
  origin: "USER" | "AI";
  user_confirmation: "CONFIRMED" | "PENDING" | "REJECTED";
  weight: number;
  confidence: number;
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

export interface CurrentBrand {
  id: string;
  name: string;
}

/** DRF list endpoints return a bare array; tolerate a paginated shape too. */
function asList<T>(payload: unknown): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === "object") {
    const inner = payload as { results?: T[] };
    if (Array.isArray(inner.results)) return inner.results;
  }
  return [];
}

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

export const fetchKnowledge = async (brandId: string) =>
  asList<KnowledgeSource>(
    await api(`/api/marketing/knowledge/sources/?brand_id=${brandId}`),
  );

export const fetchInspirations = async (brandId: string) =>
  asList<Inspiration>(await api(`/api/marketing/inspirations/?brand_id=${brandId}`));

export const fetchSignals = async (brandId: string) =>
  asList<InspirationSignalRow>(
    await api(`/api/marketing/inspiration-signals/?brand_id=${brandId}`),
  );

export const fetchPreferences = async (brandId: string) =>
  asList<BrandPreferenceRow>(
    await api(`/api/marketing/brand-preferences/?brand_id=${brandId}`),
  );

export const fetchRules = async (brandId: string) =>
  asList<BrandRuleRow>(await api(`/api/marketing/brand-rules/?brand_id=${brandId}`));

export const confirmSignal = (signalId: string) =>
  api(`/api/marketing/inspiration-signals/${signalId}/confirm/`, { method: "POST" });

export const rejectSignal = (signalId: string) =>
  api(`/api/marketing/inspiration-signals/${signalId}/reject/`, { method: "POST" });

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
