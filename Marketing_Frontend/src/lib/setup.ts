/**
 * First-run setup state — whether a client still owes the setup wizard.
 *
 * "Done" is derived from the onboarding summary the backend already keeps:
 * the brand has produced content, or the person explicitly chose to do the
 * first poster later. Nothing is stored in the browser, so the decision is
 * the same on every device and survives a cleared cache.
 *
 * Cached per document and per workspace, exactly like the membership list:
 * the hub guard consults it on every page load and must not pay two
 * requests each time.
 */
import { api } from "@/lib/api";
import { createAuthStore } from "@/lib/auth";
import { fetchOnboarding, type OnboardingSummary } from "@/lib/brand-master";
import type { BrandDto } from "@/lib/brand-settings";
import { generationDecision } from "@/lib/generation-state";
import { readSelectedWorkspaceId } from "@/lib/workspace";

export interface SetupState {
  brand: BrandDto;
  summary: OnboardingSummary;
  done: boolean;
}

/** Roles that may edit the brand; anyone else is never sent to the wizard. */
export const SETUP_ROLES = new Set(["OWNER", "ADMIN", "MANAGER", "EDITOR"]);

let cache: { workspaceId: string; promise: Promise<SetupState> } | null = null;

if (typeof window !== "undefined") {
  createAuthStore().subscribe(() => {
    cache = null;
  });
}

export function setupDone(summary: OnboardingSummary): boolean {
  const { status, skipped_steps } = summary.onboarding;
  return status === "COMPLETED" || (skipped_steps ?? []).includes("FIRST_GENERATION");
}

export function loadSetupState(options: { force?: boolean } = {}): Promise<SetupState> {
  const workspaceId = readSelectedWorkspaceId() ?? "";
  if (options.force || !cache || cache.workspaceId !== workspaceId) {
    const promise = (async () => {
      const brand = await api<BrandDto>("/api/marketing/brands/current/");
      const summary = await fetchOnboarding(brand.id);
      return { brand, summary, done: setupDone(summary) };
    })().catch((err: unknown) => {
      cache = null;
      throw err;
    });
    cache = { workspaceId, promise };
  }
  return cache.promise;
}

/** The wizard finished or was deferred — stop sending this document back to it. */
export function markSetupDone() {
  cache = null;
}

/* ------------------------------------------------------------ first poster */

export interface FirstPoster {
  contentItemId: string | null;
  headline: string;
  caption: string;
  imageUrl: string;
  imageFailed: boolean;
}

/**
 * The studio's generate-and-poll, reduced to what the wizard needs: one
 * poster from one brief. Same endpoints, same status rules, so a poster made
 * here is indistinguishable from one made in Create Studio.
 */
export async function generateFirstPoster(
  brief: string,
  campaignName: string,
  signal: AbortSignal,
): Promise<FirstPoster> {
  const queued = await api<{ generationId: string }>(
    "/api/marketing/ai-generation/generate-async/",
    {
      method: "POST",
      body: {
        instruction: brief,
        campaignName,
        contentType: "poster",
        platform: "instagram_post",
        creativeMode: "AI_ORIGINAL",
        inspirationSelections: [],
        layout: "",
      },
      signal,
    },
  );
  const id = queued.generationId;
  const started = Date.now();
  while (Date.now() - started < 10 * 60 * 1000) {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    if (signal.aborted) throw new DOMException("Cancelled", "AbortError");
    const request = await api<{
      status?: string;
      error_message?: string;
      execution?: { terminal: boolean; state: string; retry_allowed: boolean };
    }>(`/api/marketing/ai-generation/${id}/`, { signal });
    const decision = generationDecision(request);
    if (decision === "wait") continue;
    if (decision === "failed") throw new Error(request.error_message || "Generation failed.");
    const result = await api<{
      generated_text?: string;
      generated_asset_url?: string;
      metadata?: {
        contentItemId?: string;
        postTitle?: string;
        media?: { status?: string };
      };
    }>(`/api/marketing/ai-generation/${id}/results/`, { signal });
    const metadata = result.metadata ?? {};
    return {
      contentItemId: metadata.contentItemId ?? null,
      headline: metadata.postTitle ?? "",
      caption: result.generated_text ?? "",
      imageUrl: result.generated_asset_url ?? "",
      imageFailed: metadata.media?.status === "FAILED",
    };
  }
  throw new Error(
    "This is taking longer than expected. If it finishes, the poster will appear under Content.",
  );
}
