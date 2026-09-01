# Creative Command — Immutable Self-Review

**Date:** 2026-09-01
**Branch:** `feat/creative-command`
**Scope:** Slice A of `SCALEEZY_AUTONOMOUS_SOCIAL_OS_CLOSURE.md`
**Frozen owners preserved:** PR0 tenancy/RBAC, PR2 inspiration truth, PR4 Brand Brain, PR5 Context Gateway/AIRouter, PR6 generation journey, PR7 universal learning.

## Requirement evidence

| ID | Result | Evidence |
|---|---|---|
| CC-001 Unlimited selection | PASS | `CreativeCommandTests.test_selection_count_has_no_product_cap` resolves and routes 55 brand references. `test_platform_library_can_be_browsed_without_a_fifty_item_dead_end` proves pagination beyond the first 50. The UI exposes Load more and never imposes a selection cap. |
| CC-002 Tenant-safe resolution | PASS | `test_foreign_brand_reference_is_rejected_before_provider_spend` proves a foreign inspiration returns 400, produces no content and makes no provider call. Resolver filters brand rows by exact workspace and brand and returns the same unavailable error for foreign/missing rows. |
| CC-003 Campaign-only authority | PASS | `test_selected_platform_and_brand_references_reach_router_and_lineage` snapshots `Brand.creative_brain` before generation and proves it is unchanged after generation. |
| CC-004 Provider-neutral routing | PASS | The same test inspects the TEXT capability brief received by `AIRouter.dispatch`; the resolved creative direction and selected layout are present before provider selection. The Gemini legacy adapter renders the same direction instructions. |
| CC-005 Sync/async parity | PASS | Sync persistence is proven by `test_selected_platform_and_brand_references_reach_router_and_lineage`. `test_async_request_stores_resolved_direction_for_worker_revalidation` runs the real background task, proves execution-time revalidation, COMPLETED state and persisted direction/layout. |
| CC-006 Provenance/trace | PASS | Persisted `ContentItem.layout_config.creative_direction` contains source id/type, `SCALEEZY_LIBRARY` or `BRAND_INSPIRATION` provenance, use/avoid direction, focus areas and provider-neutral instructions. Sync and async traces retain provider and Brand Brain version. |
| CC-007 Layout contract | PASS | `test_unpublished_reference_and_unknown_layout_are_rejected` proves an unknown plugin fails before provider use. A registered layout is persisted in `layout_plugin` and sent as direction. |
| CC-008 Honest failure | PASS | Missing/foreign/unpublished/malformed references and invalid layouts return explicit 400 errors before quota/provider spend. Existing routing tests prove missing image capability preserves valid copy and missing providers report an honest unavailable response. |

## Adversarial matrix

| Attack path | Result | Evidence |
|---|---|---|
| Supply a foreign tenant inspiration UUID | PASS | Generic unavailable response; zero router calls; zero content rows. |
| Supply malformed UUID/role/direction/focus/layout | PASS | Normalizer or layout registry rejects before routing. |
| Select an unpublished platform reference | PASS | Resolver only accepts `LifecycleStatus.PUBLISHED`. |
| Disable shared inspirations for a client | PASS | Resolver checks the PR7 client setting before resolving platform rows. |
| Queue, then archive/move a selected inspiration | PASS | Async worker re-resolves stored source selections at execution time and fails honestly. |
| Select more than one page or more than 50 references | PASS | Offset pagination plus 55-reference routing test. |
| Use a reference as a prompt-injection channel | PASS | Resolver labels reference content as data, forbids policy/brand/user-brief override, and warns against copying third-party logos, artwork and unverified claims. |
| Oversized annotations/signals | PASS | Every text field is compacted deterministically; `truncated_fields` records any clipping without silently dropping selected references. |

## Gates

- PASS — focused backend: 32 generation/Creative Command tests, 0 failures.
- PASS — related platform/universal/backend: 64 tests, 0 failures.
- PASS — full backend regression: 988 tests, 0 failures, 102.768s.
- PASS — migrations: `makemigrations --check --dry-run` reports no changes.
- PASS — Django system check: no errors; local development placeholder `SECRET_KEY` warning only.
- PASS — frontend typecheck: `tsc --noEmit`.
- PASS — targeted frontend lint: Creative Command, publishing route and platform API client.
- PASS — targeted Prettier check.
- PASS — full Vite client, SSR and Nitro production build.
- N/A — full-repository Prettier cleanup: the repository carries a pre-existing CRLF formatting baseline across untouched files; mass reformatting is outside this vertical slice and would make the change unsafe to review.

## Findings closed during verification

- The background generation worker used the nonexistent `request` lookup when writing `GeminiGenerationResult`; the real field is `generation_request`. The async execution test exposed it and the worker now creates/updates the result correctly.
- The shared inspiration gallery formerly had a hard 50-item endpoint ceiling. It now has bounded offset pagination with one-extra-row `next_offset` detection and no additional count query.

## Verdict

**PASS — zero FAIL and zero NOT VERIFIED on mandatory gates.** Slice A is safe to commit. It adds a campaign-level Creative Command without changing frozen tenant, Brand Brain, Context Gateway, AI Router, publishing or universal-learning ownership.
