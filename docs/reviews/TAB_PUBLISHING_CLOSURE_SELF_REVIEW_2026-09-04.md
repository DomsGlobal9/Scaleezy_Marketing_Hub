# Publishing / generation closure self-review — 2026-09-04

Immutable slice evidence for `TAB_CLOSURE_ALL_GAPS_PREFLIGHT_2026-09-04.md`.
This is focused slice acceptance, not a claim that the shared PR's full gate has passed.
No commit, push, production mutation, provider spend, migration, or production build was performed by this slice.

## Scope and dependency path

Studio / legacy generation aliases → authenticated workspace member → EDITOR mutation authority → current brand and explicit creative direction → durable generation request and TaskRun → provider output → saved ContentItem / MarketingAsset → polling / image-only recovery → review → publishing setup → current account policy at worker dispatch → publishing history.

Changed only generation views/serializers/tasks and their tests, publishing views/policy/service and their tests, the Studio route, its pure generation-state client helper/tests, and this evidence file. Existing TaskRun infrastructure, Context generation service, Brand Brain, Social OAuth adapters, review transitions, and asset API ownership were reused without edits.

## Findings closed

| Item | Verdict | Concrete implementation and verification |
| --- | --- | --- |
| PUB-01 generation authority | PASS | `apps/gemini/views.py:37`: read-only generic viewset; custom mutations require EDITOR, reads permit VIEWER. `StudioClosureTests.test_viewer_cannot_mutate_any_alias_or_creative_mode` attacks both aliases, three modes, analysis/caption/image-retry actions. `test_generic_writes_are_unavailable_even_to_editor` proves raw POST/PUT/PATCH/DELETE cannot forge/delete request rows. |
| PUB-02 delayed dispatch authority | PASS | `apps/publishing/services.py:54` refreshes job, item, connection and rechecks workspace/account eligibility before dispatch; policy failures do not automatically retry. `PublishingClosureTests.test_queued_account_and_workspace_changes_block_dispatch_without_auto_retry`, `test_cancelled_job_and_item_stay_cancelled`, and `test_manual_retry_cannot_revive_cancelled_job` prove no provider call after relevant revocation. |
| PUB-03 honest missing-image result | PASS | `apps/gemini/execution.py:48` records media FAILED; serializer exposes terminal PARTIAL. `apps/gemini/tasks.py:517` retries only IMAGE against the saved draft, preserving copy and durable asset checkpoints. `test_partial_media_is_honest_and_image_retry_preserves_copy`, `test_sync_partial_has_same_image_only_recovery_handle`, `test_image_retry_failure_keeps_copy_and_never_allows_full_retry`, and `test_image_retry_preserves_an_image_supplied_while_provider_was_busy` passed. Inspiration-specific prior copy-discard assertion was updated to require a saved DRAFT, null asset, empty preview, and explicit failed media instead of claiming a ready poster. |
| PUB-04 retry ownership / duplicate delivery | PASS | `apps/gemini/execution.py:7` derives active ownership from existing READY/RUNNING TaskRuns. `apps/gemini/views.py:658` accepts an optional UUID requestId and atomically creates/enqueues once, preserving the original brief on replay. Tests prove one request/task for repeat delivery, foreign-client UUID refusal, resume-before-new-spend-quota, RETRY_PENDING until the task is terminal, and image retry queue rollback. UI tests prove replay HTTP errors retain the prior ID and pending retries do not terminate polling. |
| PUB-05 failed publishing preserves setup | PASS | `src/routes/_hub.publishing.tsx:852` clears selection/lock and exits publish setup only in the success branch; failure keeps the approved version, selected accounts, mode and date. Independently inspected by the other frontend slice; typecheck and focused lint passed. Browser interaction after this change is part of the root integration gate, not claimed here. |
| PUB-06 bounded history / polling reads | PASS | Publishing queryset selects its content and prefetches item connections; generation list batches active task ownership and selects results. `test_history_queries_are_constant_and_selected_client_only` proves equal query counts for 1 vs 25 rows, at most 4, and excludes another client. `test_generation_list_batches_execution_state` proves equal counts for 1 vs 25 rows, at most 5. |
| Explicit template CTA | PASS | `src/lib/generation-state.ts` requires brief, mode, and a loaded explicit template choice; reference is required only in REFERENCE mode. Tests cover blank form, unselected direction, unloaded/unselected template, reference optionality, and resuming already accepted work. |

## Attack and failure evidence

- PASS — both `/api/marketing/ai-generation/` and `/api/marketing/gemini/` aliases reject VIEWER spend and generic row mutation; authorized EDITOR generation still succeeds.
- PASS — foreign-workspace delivery IDs and image-retry requests are refused without another task; image retry refuses a draft that entered review.
- PASS — image retry enqueue failure rolls back request state and leaves successful copy recoverable. A second image-retry while owned cannot enqueue more work.
- PASS — concurrent manual image attachment is preserved; neither the generated replacement nor automatic composition overwrites it.
- PASS — existing inspiration revocation, brand lifecycle, guardrail, persistence rollback, worker rescue, generation checkpoint, and publishing tests passed within the affected-module suite.
- PASS — successful image UI wording requires a durable asset ID, preview and explicit media READY. A retry conflict reads the same generation, allowing recovery after a lost response without new paid work.
- N/A — new database schema or infrastructure: no model or migration was changed.
- N/A — Social OAuth/token or Brand Brain contract changes: those modules were not edited by this slice.

## Exact focused verification

Executed against isolated Django test databases using the bundled Python runtime; all provider operations exercised by new tests were mocked.

| Gate | Verdict | Result |
| --- | --- | --- |
| `manage.py test apps.gemini apps.publishing apps.jobs apps.context --verbosity 0` | PASS | Final run: **225 tests, 17.490s, OK**, system check 0 issues. Includes 17 new closure tests (13 Studio, 4 Publishing). |
| `node --experimental-strip-types --test tests/generation-state.test.mjs` | PASS | **8 tests, 8 passed, 0 failed**, 323.2278ms. |
| `node node_modules/typescript/bin/tsc --noEmit` | PASS | No diagnostics. Earlier shared analytics diagnostic was corrected by its owning slice; no Publishing diagnostic remained. |
| Focused ESLint: Studio route, generation-state helper, generation-state tests | PASS | Exit 0, no diagnostics. |
| `manage.py check` | PASS | 0 issues. |
| `manage.py makemigrations --check --dry-run` | PASS | No changes detected. |
| `git diff --check` | PASS | No whitespace errors; repository CRLF normalization warnings only. |
| Full backend regression / production frontend build / post-change browser gate | NOT VERIFIED | Root explicitly owns shared integrated gates; no production build was started by this slice. |

## Contract limits retained

Terminal full-generation failure may permit an explicitly new generation; running or retry-pending work never does. Existing video/carousel checkpoint retries remain owned by the existing TaskRun worker. The optional requestId adds safe HTTP replay without breaking older clients that omit it. The saved-copy repair action is limited to editable POSTER drafts with missing media. Publishing setup failure does not bypass approved-content or selected-workspace validation.

No known unresolved issue remains in PUB-01 through PUB-06 or template CTA completeness within this bounded slice. Shared PR readiness still depends on root's integrated gates above.
