# Core Recovery Final Self-Review — 2026-08-22

This report is immutable evidence for the P0 recovery integration. PR0–PR6 remain frozen contracts. PR7 was not started.

## Code and architecture

| Gate | Status | Evidence |
| --- | --- | --- |
| Frozen ownership | PASS | Brand remains authoritative, Brand Brain remains derived, Context Gateway builds context, AIRouter selects capabilities, adapters alone contain vendor integration. |
| Multi-workspace isolation | PASS | Selected client is sent through `X-Workspace-Id`; mismatched/foreign workspace paths fail closed; the full 690-test suite includes tenant attack cases. |
| Add Client atomic readiness | PASS | Workspace, OWNER membership, default Brand and required AI routes commit together; unavailable platform AI returns 503 and rolls back. |
| Admin-only AI policy | PASS | Catalogue, credentials and ordered route-set APIs require ADMIN; product Settings contains no AI controls; frontend route is OWNER/ADMIN guarded. |
| Multiple AI redundancy | PASS | Gemini and OpenAI production adapters implement the frozen contract; ordered FAILOVER, ROUND_ROBIN and BEST_OF routes are covered by AI tests. No existing tenant is silently rerouted. |
| Credential safety | PASS | Workspace keys remain encrypted/write-only; server keys remain environment secrets; tests make no paid/live OpenAI call and never print the saved key. |
| Brand Master edit safety | PASS | Explicit Save, coherent dirty/error state, retry retention, serialized autosave and old-client unload addressing are implemented; final TypeScript/lint/build gates passed. |
| Durable generated images | PASS | Inline/temporary provider images are copied to workspace storage and linked to a MarketingAsset before the ContentItem response. `test_inline_provider_image_is_durable_before_content_is_returned` passed in focused and full gates. |
| Review/publish integrity | PASS | Only approved exact content/media can create a job; arbitrary publish captions are ignored; raw job mutation is disabled; Manager-only create/retry and tenant isolation tests passed. |
| Approved-content immutability | PASS | Layout render refuses non-DRAFT content and Review exposes Poster Studio only for drafts; regression tests passed. |
| Full backend regression | PASS | 690 tests, 0 failures, 1166.904 seconds. |
| Frontend release gate | PASS | TypeScript pass; ESLint across 21 changed files with zero substantive warnings; production client/SSR/Nitro build pass. |
| Schema/system gate | PASS | `makemigrations --check --dry-run`: no changes; Django check: no errors, only expected local placeholder-secret warning. |

## Deployment and remaining scope

| Gate | Status | Evidence / action |
| --- | --- | --- |
| Render task execution | FAIL | `render.yaml` starts Gunicorn only. Add a service/process running `python manage.py run_tasks`; otherwise queued generation and publishing remain queued. This is an infrastructure/cost decision and was not silently added. |
| Credentialed external smoke | NOT VERIFIED | After deployment, generate one real OpenAI-backed poster and publish one approved item to a connected social account. No paid/live call was made during tests. |
| Knowledge processing | FAIL | Automatic extraction/processing remains an explicit P1 gap. |
| Inspiration analysis | FAIL | Automatic analysis remains an explicit P1 gap. |
| Calibration influence | NOT VERIFIED | Existing modules/tests pass, but a dedicated later-generation influence/non-contamination proof remains P1. |

## Verdict

- **P0 code integration: PASS.**
- **Production full-loop release: BLOCKED by the missing task worker and live credentialed smoke.**
- **PR7: not started.**
