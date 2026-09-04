/** The task owner, not a transient request failure, decides when polling ends. */
export function generationDecision(request: {
  status?: string;
  execution?: { terminal: boolean; state: string; retry_allowed: boolean };
}): "wait" | "failed" | "complete" {
  if (request.execution && !request.execution.terminal) return "wait";
  if (request.status === "FAILED") return "failed";
  return request.status === "COMPLETED" ? "complete" : "wait";
}

export function canDiscardRejectedDelivery(
  pending: boolean,
  status: number,
  code: string,
): boolean {
  // An HTTP failure while resuming says nothing about the already queued task.
  return !pending && (code === "QUEUE_FAILED" || (status >= 400 && status < 500));
}

export function hasSavedGenerationImage(result: {
  assetId?: string | null;
  posterImageUrl?: string;
  metadata?: { media?: { status?: string } };
}): boolean {
  return Boolean(
    result.assetId && result.posterImageUrl && result.metadata?.media?.status === "READY",
  );
}

export function canCreateGeneration(input: {
  awaitingApproval: boolean;
  pending: boolean;
  mode: string | null;
  brief: string[];
  hasReference: boolean;
  layout: string;
  catalogueReady: boolean;
}): boolean {
  // Resuming accepted work is a read, not a new generation or template choice.
  if (input.pending) return true;
  if (input.awaitingApproval || !input.mode || !input.brief.some((text) => text.trim()))
    return false;
  if (input.mode === "REFERENCE" && !input.hasReference) return false;
  if (input.mode === "CATALOG_TEMPLATE" && (!input.layout || !input.catalogueReady)) return false;
  return true;
}
