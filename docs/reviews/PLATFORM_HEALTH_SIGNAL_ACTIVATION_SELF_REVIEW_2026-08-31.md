# Platform Health Signal Activation — Immutable Self-Review

Date: 2026-08-31

## Evidence

- PASS — `knowledge_failed` counts active-client `BrandSource` rows in durable `FAILED` state; `ProcessingHealthTests.test_processing_states_are_live_numeric_signals` proves the numeric signal and attention contribution.
- PASS — `knowledge_needs_review` counts sources, not candidate memories, in durable `NEEDS_REVIEW` state; the same focused test proves its exact value and display.
- PASS — `inspiration_analysis_failed` counts only retrieval-eligible active-client inspirations in durable `FAILED` state; `ProcessingHealthTests.test_inactive_and_revoked_work_is_not_actionable` proves inactive workspaces, archived inspirations, and inspirations backed by archived sources are excluded.
- PASS — The platform API preserves all existing keys and labels while returning numeric live values; `PlatformBoundaryTests.test_health_returns_live_signals_and_audits_the_read` passed.
- PASS — Future dead sensors still render `Not monitored` and cannot affect `needs_attention`; `UnmonitoredSignalTests.test_a_dead_sensor_never_counts_towards_needs_attention` passed.
- PASS — Focused health gate: 13/13 tests passed.
- PASS — Full backend regression: 974/974 tests passed across eight isolated application groups.
- PASS — Django system check reported no issues and migration drift check reported no changes.
- PASS — `git diff --check` passed.
- N/A — Frontend build/typecheck: no frontend file or API shape changed.
- N/A — Migration: no model change.

## Adversarial conclusion

Zero FAIL and zero NOT VERIFIED items. The correction changes only read-only platform health aggregation and its evidence; processor, tenant, RBAC, Brand Brain, provider, and PR7 contracts are unchanged.
