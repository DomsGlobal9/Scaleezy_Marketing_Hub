# Inspiration PostgreSQL Lock Hotfix — Immutable Self-Review

Date: 2026-09-02
Result: READY

- PASS — PostgreSQL no longer receives `FOR UPDATE` on the nullable provenance-source outer join. Evidence: `_lock_generation_references()` locks `BrandInspiration` directly; `test_final_reference_lock_has_no_nullable_outer_join` asserts the lock query has no join.
- PASS — source revocation remains race-safe. Evidence: non-null `BrandSource` rows are locked and checked in the same transaction; `test_final_reference_lock_rejects_archived_source` passes.
- PASS — inspiration lifecycle revocation still blocks persistence. Evidence: `test_inspiration_revoked_during_provider_call_is_not_persisted` passes.
- PASS — tenant and brand boundaries are unchanged and enforced in the direct lock filters. Evidence: focused `CreateFromInspirationTests` passed (27 tests).
- PASS — full affected inspiration/generation gate passed (132 tests).
- PASS — full backend regression passed (1,170 tests).
- PASS — migration state is clean (`makemigrations --check --dry-run`: no changes).
- PASS — Django system check has zero errors; the local placeholder `SECRET_KEY` warning is test-environment-only.
- N/A — no schema, API response, RBAC, Brand Brain, AIRouter, billing, publishing, or credential contract changed.

