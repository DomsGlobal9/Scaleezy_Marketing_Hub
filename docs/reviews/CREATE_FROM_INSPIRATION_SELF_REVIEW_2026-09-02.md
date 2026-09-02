# Create From Inspiration — Evidence Gate

## Build identity
- PR: additive Content → Create from inspiration vertical slice
- Branch: `codex/create-from-inspiration`
- Reviewer mode run after implementation: YES

## Requirement traceability
| Req ID | Status | Evidence | Notes |
|---|---|---|---|
| CFI-001 | PASS | `CreateFromInspiration` is mounted in Publishing and accepts one upload or one public HTTPS page. Frontend typecheck, targeted lint, and production build pass. | Client/brand changes abort and clear the active flow. |
| CFI-002 | PASS | Default editable instruction is “Create a similar poster”; async payload tests pass. | Instruction is length-bounded and subordinate to policy. |
| CFI-003 | PASS | Worker passes the exact validated brand to `generate_marketing_payload`; `test_default_brand_switch_cannot_reassign_inspiration_output` passes. | Current Brand Brain is resolved at execution, not frozen in the queue row. |
| CFI-004 | PASS | Creative direction labels the reference as untrusted evidence and requires original, brand-governed output. Focused prompt tests pass. | No exact-clone promise. |
| CFI-005 | PASS | `test_reference_is_preprocessed_then_saved_as_draft_with_id_only_provenance` passes. | Queue stores IDs only; final draft stores lineage/brain/provider trace. |
| CFI-006 | PASS | Image signature/MIME/size and HTTPS/SSRF tests pass. | Release scope is JPEG/PNG/WebP plus public page text; other types fail honestly. |
| CFI-007 | PASS | Worker creates `ContentItem.Status.DRAFT`; existing review/publishing gates remain unchanged. | No automatic approval or publishing. |
| CFI-008 | PASS | Queue failure, concurrent analysis, result-write rollback, compose failure, and retry-ambiguity paths are covered. | User retry is disabled after successful queue ownership. |

## Dependency verification
| Dependency | Status | Evidence |
|---|---|---|
| Auth → workspace | PASS | Existing `X-Workspace-Id` resolution plus tenant attack tests in the 151-test focused run. |
| Workspace → brand | PASS | Exact brand is passed through Context Gateway and persistence; default-switch test passes. |
| Input → validation | PASS | Real image signature, MIME, extension, dimensions, byte cap, URL and role tests pass. |
| Validation → persistence | PASS | Invalid inputs and cross-tenant references produce no inspiration/generation/content rows. |
| Persistence → service/job | PASS | Saved inspiration ID is queued to the existing durable generation task. |
| Job → honest state | PASS | Missing image, no grounded observations, revocation and persistence failures become FAILED with no draft. |
| State → downstream consumer | PASS | Result polling returns the saved draft/asset IDs to the existing preview and Review flow. |
| API → UI | PASS | Publishing UI saves, queues, polls, handles cancellation, and prevents ambiguous duplicate retry. |
| Failure → user-visible/error state | PASS | Unsupported input, queue failure, timeout/cancel and worker failure have explicit messages. |
| Provenance/lineage | PASS | Inspiration selection, creative direction, current brain version and provider trace persist on the final draft. |

## Test evidence
- Changed-module tests: PASS — 151 tests (`apps.inspirations.tests`, `apps.gemini.test_create_from_inspiration`, `apps.gemini.test_creative_command`, `apps.gemini.test_async_generation`).
- Security/adversarial tests: PASS — cross-tenant/brand, VIEWER whitespace/case bypass, SSRF, lifecycle revocation, concurrent analysis, default-brand switch, atomic draft/result, provider partial failure.
- Full backend: 1130/1131 PASS in the last full run. The sole failure is the pre-existing `RecentHeadlineMemoryTests.test_newest_distinct_headlines_only`; its five rows can share one `auto_now_add` clock tick and have no deterministic insertion-order tie-breaker. The isolated test reproduces the same unrelated failure.
- Frontend build: PASS — `npm run build`.
- Frontend typecheck: PASS — `npx tsc --noEmit`.
- Frontend lint: PASS — targeted ESLint on the two changed frontend files.
- Migration check: PASS — no changes detected.
- Django check: PASS with only the expected local placeholder `SECRET_KEY` warning.
- Diff check: PASS.

## Known gaps
- Broad media normalization is deferred by `CREATE_FROM_INSPIRATION_SCOPE_DECISION_2026-09-01.md`: video, audio, PDF and presentation inputs require bounded frame/page/transcript adapters before activation.
- Repository-wide gate has one pre-existing timestamp-tie test failure described above; this change does not alter `recent_headlines` ordering.

## Deviations
- CFI-006 was narrowed by the immutable release-scope decision. Unsupported types fail explicitly rather than generating an ungrounded “similar” poster.

## Readiness
- Requirement PASS: 8
- Requirement N/A: 0
- Requirement FAIL: 0
- Requirement NOT VERIFIED: 0
- Feature-focused gate: READY
- Repository-wide gate: NOT CLEAN because of the unrelated existing timestamp-tie test.
