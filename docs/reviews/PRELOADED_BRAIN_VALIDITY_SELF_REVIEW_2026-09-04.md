# Preloaded Brand Brain validity — immutable self-review

## Identity and outcome

- Date: 2026-09-04.
- Branch/checkpoint: `codex/tab-by-tab-product-closure`, `c42c1c52`; existing uncommitted closure work preserved.
- Authorization: the user approved the specifically described date-validity correction with “if its needed lets do it”.
- Preflight: `PRELOADED_BRAIN_VALIDITY_PREFLIGHT_2026-09-04.md`.
- Outcome: the previously blocked preloaded-compiler validity gap is CLOSED in local code. Earlier immutable reports are preserved as historical evidence.

## Implementation and dependency boundary

`Marketing_backend/apps/brands/services/brand_brain.py::compile_brand_brain_from_records` now filters preloaded memories before calculating claims, conflicts, narrative and lineage. Null bounds remain eligible; start is inclusive and expiry is exclusive: `valid_from <= now < valid_until` where each bound exists. Original memory/source records remain intact.

The actual Platform consumer is `PortfolioStats` and `client_row`; the preflight's “ClientProjection” wording referred to this projection path, not a class name. The missing-snapshot path now matches ordinary compilation's existing validity policy. No new queries are introduced for preloaded records. Tenant scope, permissions, compiler ownership, precedence, persisted Brain shape and response schema remain unchanged.

## Requirement-to-evidence map

All six tests are in `apps.brands.test_preloaded_validity.PreloadedMemoryValidityTests` and passed both the focused run and the full backend run.

| Requirement | Status | Concrete evidence |
| --- | --- | --- |
| Null/current facts remain; expired/future facts are excluded; exact start/end semantics hold | PASS | `test_preloaded_null_current_and_exact_time_boundaries` exercises eight boundary cases and compiled truth/source IDs. |
| Ordinary and preloaded compilers agree | PASS | `test_ordinary_and_preloaded_fingerprints_match_at_frozen_time` compares the entire snapshot and fingerprint. |
| Iterable shape and order do not alter eligible output | PASS | `test_generator_input_and_order_preserve_the_same_eligible_fingerprint` passes a reversed generator. |
| Audit evidence is retained; compilation performs no reads or writes | PASS | `test_compilation_is_read_only_and_retains_all_source_records` asserts zero queries for preloaded compilation and unchanged memory/source rows and persisted snapshot. |
| Actual Platform readiness uses the filtered missing-snapshot preload | PASS | `test_platform_missing_snapshot_and_readiness_use_the_filtered_preload` exercises `PortfolioStats`/`client_row`, compares ordinary compilation and readiness, excludes expired positioning/future pain, and rejects projection writes. |
| Sibling/foreign brand facts do not enter the selected snapshot | PASS | `test_platform_preload_does_not_mix_sibling_or_foreign_brand_sources`. |

## Verification gates

| Gate | Status | Evidence |
| --- | --- | --- |
| Focused tests | PASS | Six preloaded-validity tests passed in 0.080 seconds. |
| Full backend regression | PASS | `manage.py test --verbosity 0`: 1,355 tests passed in 25.865 seconds, exit 0. Isolated in-memory SQLite and test-only signing/encryption values; no production database access. |
| Django system checks | PASS | Full regression reported zero issues. |
| Whitespace validation | PASS | `git -c core.safecrlf=false diff --check` exited 0. |
| Frontend build/type/lint | N/A | This incremental correction changes no frontend files or API shape. Prior integrated frontend evidence remains in the earlier report and is not re-certified for unrelated concurrent edits. |
| Schema/migration checks | N/A | No model, schema or migration changes. |
| Browser replay | N/A | No UI/route/response-shape changes in this correction. The actual server-side Platform consumer is covered by integration tests. Complete real-provider/production replay remains outside this incremental acceptance. |
| External actions | N/A | No provider calls, credential changes, commit, push, merge, deploy or live-data mutations. |

Test runtime: existing Python 3.13.7 / Django 6.1 at `C:/Users/debas/AppData/Local/Programs/Python/Python313/python.exe`. The refreshed bundled runtime lacked Django; no package installation or infrastructure change was needed.

## Acceptance and limits

No FAIL or unverified mandatory gate remains for this approved incremental correction. The verification skill guided coverage through Platform's real consumer and the source-retention/read-purity boundaries, rather than helper-only tests. This report closes the outstanding compiler finding, not every possible production/provider/mobile scenario. Changes remain local and uncommitted; previously existing working-tree changes are preserved.
