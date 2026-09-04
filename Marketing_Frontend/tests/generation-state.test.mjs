import assert from "node:assert/strict";
import test from "node:test";
import {
  canCreateGeneration,
  canDiscardRejectedDelivery,
  generationDecision,
  hasSavedGenerationImage,
} from "../src/lib/generation-state.ts";

test("replay HTTP errors never discard an accepted delivery ID", () => {
  for (const status of [400, 401, 403, 409, 500, 503]) {
    assert.equal(canDiscardRejectedDelivery(true, status, ""), false);
  }
  assert.equal(canDiscardRejectedDelivery(false, 400, ""), true);
  assert.equal(canDiscardRejectedDelivery(false, 503, "QUEUE_FAILED"), true);
  assert.equal(canDiscardRejectedDelivery(false, 503, ""), false);
});

test("image recovery success requires a durable ready image, not partial completion", () => {
  const result = {
    assetId: "saved-asset",
    posterImageUrl: "https://storage.test/saved.png",
    metadata: { media: { status: "READY" } },
  };
  assert.equal(hasSavedGenerationImage(result), true);
  assert.equal(hasSavedGenerationImage({ ...result, assetId: null }), false);
  assert.equal(
    hasSavedGenerationImage({ ...result, metadata: { media: { status: "FAILED" } } }),
    false,
  );
});

const brief = {
  awaitingApproval: false,
  pending: false,
  mode: "AI_ORIGINAL",
  brief: ["Launch"],
  hasReference: false,
  layout: "",
  catalogueReady: true,
};

test("request failure remains owned while the worker retry is pending", () => {
  assert.equal(
    generationDecision({
      status: "FAILED",
      execution: { state: "RETRY_PENDING", terminal: false, retry_allowed: false },
    }),
    "wait",
  );
});

test("only terminal request outcomes end polling", () => {
  assert.equal(
    generationDecision({
      status: "FAILED",
      execution: { state: "FAILED", terminal: true, retry_allowed: true },
    }),
    "failed",
  );
  assert.equal(
    generationDecision({
      status: "COMPLETED",
      execution: { state: "PARTIAL", terminal: true, retry_allowed: false },
    }),
    "complete",
  );
  assert.equal(generationDecision({ status: "GENERATING" }), "wait");
});

test("blank brief and unselected direction cannot enable generation", () => {
  assert.equal(canCreateGeneration({ ...brief, mode: null }), false);
  assert.equal(canCreateGeneration({ ...brief, brief: [" ", ""] }), false);
  assert.equal(canCreateGeneration(brief), true);
});

test("template mode requires an explicit loaded selection", () => {
  assert.equal(canCreateGeneration({ ...brief, mode: "CATALOG_TEMPLATE" }), false);
  assert.equal(
    canCreateGeneration({
      ...brief,
      mode: "CATALOG_TEMPLATE",
      layout: "editorial",
      catalogueReady: false,
    }),
    false,
  );
  assert.equal(
    canCreateGeneration({ ...brief, mode: "CATALOG_TEMPLATE", layout: "editorial" }),
    true,
  );
});

test("reference mode needs a reference but original mode does not", () => {
  assert.equal(canCreateGeneration({ ...brief, mode: "REFERENCE" }), false);
  assert.equal(canCreateGeneration({ ...brief, mode: "REFERENCE", hasReference: true }), true);
});

test("accepted work can be resumed even after form or approval changes", () => {
  assert.equal(
    canCreateGeneration({ ...brief, pending: true, awaitingApproval: true, mode: null, brief: [] }),
    true,
  );
  assert.equal(canCreateGeneration({ ...brief, awaitingApproval: true }), false);
});
