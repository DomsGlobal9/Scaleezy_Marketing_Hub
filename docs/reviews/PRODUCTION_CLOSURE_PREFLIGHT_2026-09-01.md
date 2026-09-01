# Production Closure — Immutable Execution Preflight

## Identity

- PR: Production Closure — real carousel and video generation
- Commit/branch at preflight: `cdb34ba9` / `feat/production-closure`
- Authorized scope: implement Slice B of
  `docs/SCALEEZY_AUTONOMOUS_SOCIAL_OS_CLOSURE.md` through the existing Context
  Gateway, `AIRouter`, durable storage, generation request/task, content item,
  layout registry and Publishing wizard.
- Explicitly out of scope: a second provider contract, engagement inbox,
  performance ingestion, monetization, autopilot and changes to publishing
  authorization/platform APIs.
- Repository gap: `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` are not
  present. Existing models, tests and the frozen closure contract govern this
  slice.

## Current truth

- Poster generation already routes TEXT and IMAGE independently and preserves
  partial success.
- Carousel requests are queued but call the poster path once; their slide
  descriptions are persisted without generated slide media.
- Video is deliberately disabled in the UI because queued video requests also
  call the poster path; the `VIDEO` router capability is not invoked.
- The administrator-owned `SCALEEZY_JSON` adapter can expose any capability,
  including VIDEO. OpenAI-compatible endpoints intentionally remain limited to
  their standard protocol capabilities.
- `MarketingAsset` and `ContentItem` already represent durable VIDEO and
  CAROUSEL outputs; no schema addition is required.

## Dependency graph

User → auth → selected workspace → approved brand → creative direction →
task-specific Context Gateway brief → capability-specific AIRouter route →
provider result → safe bounded media retrieval → workspace storage →
MarketingAsset/ContentItem → polling UI → preview/edit/review.

## Entry paths

| Path | Required behaviour |
|---|---|
| Poster sync | Existing TEXT+IMAGE behavior and partial-success semantics remain unchanged. |
| Carousel async | Generate one TEXT package and every ordered IMAGE slide; persist durable URLs and per-slide trace. |
| Video async | Generate TEXT/script direction and one VIDEO output using the workspace route; persist a durable video asset. |
| Worker retry | Revalidate references and rerun only an unfinished request; never claim COMPLETED without required media. |
| Poll/result | Return `videoUrl`/`slideImageUrls` and content/asset ids without changing the existing copy fields. |
| Frontend | Enable video settings only now that they reach the server; show actual video or ordered slide previews. |

## Requirements and proof

| ID | Requirement | Planned path | Proof |
|---|---|---|---|
| PC-001 | VIDEO capability is selected by content type, never provider name | generation service → `AIRouter.dispatch(VIDEO)` | router-spy test |
| PC-002 | Video controls reach the provider-neutral brief | async view + worker | stored brief and worker test |
| PC-003 | Video output is durable and typed VIDEO | bounded media persistence + `MarketingAsset` | base64/ephemeral result test |
| PC-004 | Every carousel slide is generated in order | queued generation service | multi-slide router-call and persistence test |
| PC-005 | Carousel URLs are durable and returned to the UI | storage + result metadata + ContentItem.slides | API result/ContentItem test |
| PC-006 | Required media failure is honest | worker FAILED state and error | missing-route/provider-output tests |
| PC-007 | Poster behavior does not regress | unchanged poster branch | existing generation-routing suite |
| PC-008 | Cross-tenant and approval gates remain authoritative | existing endpoints/router | tenant/approval regression tests |

## Risk scan

- Provider URLs: generated ephemeral media can be a network boundary. Validate
  HTTPS/public targets before each redirect, stream with a byte cap and reject
  content-type mismatches.
- Memory/storage: base64 and downloads are capped; large provider bodies cannot
  be buffered without a limit.
- Partial carousel: a carousel is not complete if any required slide is
  missing. Preserve the trace and fail the request rather than returning a
  misleading COMPLETE state.
- Video availability: enable the UI generically; if the client has no VIDEO
  route the queued request must fail visibly with configuration guidance.
- Provider ownership: no hard-coded OpenAI/Gemini/video vendor and no automatic
  default provider.

## Stop decision

- PROCEED
- Reason: this closes already-declared formats and capabilities through frozen
  owners. No tenancy, Brain, router, credential, publishing or infrastructure
  semantics are replaced.
