# Context snapshot validity — focused self-review (2026-09-04)

Scope: the approved generation-context guard in `apps/brands/services/brand_brain.py`, `apps/context/services/context_gateway.py`, and `apps/context/test_snapshot_validity.py`. This report does not certify the separate preloaded Platform snapshot path described below. No migration, provider call, live write, deployment or commit was performed.

## Evidence matrix

| Requirement | Result and concrete evidence |
| --- | --- |
| Compiled eligibility | PASS — existing `_memories()` enforces `valid_from <= now < valid_until`; `SnapshotValidityTests.test_legacy_snapshot_cannot_carry_already_expired_or_future_facts`. |
| Warm-cache time crossing | PASS — `test_expiry_invalidates_an_already_warm_context_at_exact_boundary` and `test_future_fact_enters_at_exact_start_without_a_write_or_manual_rebuild` prove the old brain-version cache is not reused at either exact boundary. |
| Failed source revoke/edit rebuild | PASS — `test_source_revoke_with_failed_rebuild_cannot_reuse_warm_context` and `test_confirmed_edit_with_failed_rebuild_withdraws_old_context` exercise real API actions while compilation fails; withdrawn facts do not reach subsequent context. |
| Unavailable current context | PASS — `test_failed_resolution_fails_closed_even_when_old_cut_is_cached`; only a safe `ContextError` is exposed and the old cached cut is not returned. |
| Non-memory rebuild failure | PASS — `test_persisted_failure_forces_refresh_even_when_memory_ids_are_unchanged`; active rules and `intelligence_in_force` use the freshly resolved in-memory version. |
| Universal precedence | PASS — `test_universal_precedence_uses_the_newly_resolved_snapshot`; a newly active brand fact suppresses the weaker standard using the same resolved snapshot. |
| Tenant and brand isolation | PASS — `test_foreign_temporal_changes_do_not_refresh_or_leak_into_local_context`; foreign workspace/brand facts do not enter or refresh local context, and mismatched workspace/brand resolution raises `ContextError`. |
| Read purity / API contract | PASS — `test_stale_read_is_pure_and_preserves_saved_brain_contract`; no INSERT/UPDATE/DELETE occurs, persisted JSON remains unchanged, and the returned Brain has the same keys/shape. |
| Unchanged hot path | PASS — `test_current_snapshot_check_is_fixed_query_and_never_recompiles`; two fixed queries with 51 memories and no compiler call. Existing context cache remains keyed by the effective brain version. |
| New focused suite | PASS — `manage.py test apps.context.test_snapshot_validity --verbosity 1`: 11 tests, 0.738 seconds, zero Django system-check issues. Expected failure logs are from explicit compile-outage attack tests. |
| Affected-app regression | PASS — `manage.py test apps.brands apps.context apps.knowledge apps.onboarding apps.universal apps.gemini --verbosity 0`: 446 tests, 40.103 seconds, zero Django system-check issues. |
| FINAL full backend regression | PASS — `manage.py test --verbosity 0`: 1,349 tests, all passing; zero Django system-check issues. Test-only generated encryption/signing keys and the isolated SQLite test database were used. |
| Migration gate | N/A — no model/schema change. |
| Preloaded Platform compiler validity | NOT VERIFIED / PENDING EXPLICIT USER APPROVAL — `apps/platform/views_clients.py` preloads all confirmed, non-archived memories and calls `compile_brand_brain_from_records`; it does not yet apply `valid_from`/`valid_until`. A proposed central compiler-boundary filter and one regression test were rejected by the safety review before execution. Per root direction, the change was not retried or bypassed. Overall all-gaps scope must not be called complete until this is approved and verified. |

## Implementation and preserved boundaries

`brain_snapshot_needs_refresh` compares the saved Brain's cited memory IDs with the compiler-owned, workspace-and-brand-scoped eligible IDs and reads the persisted compilation-failure flag. `resolved_brain` performs a pure compile only when the snapshot is missing or unsafe, before consulting the warm context cache; compilation failure fails closed. `build_generation_context` binds only that resolved JSON to its in-memory Brand so existing universal-precedence and attribution consumers use the same version. It does not persist on reads.

The persisted Brand Brain schema/API, Context Gateway ownership, precedence ranks, tenant/RBAC model, learning provenance, publishing architecture and provider boundaries remain unchanged. The immutable addendum is `docs/reviews/CONTEXT_SNAPSHOT_VALIDITY_PREFLIGHT_2026-09-04.md`.
