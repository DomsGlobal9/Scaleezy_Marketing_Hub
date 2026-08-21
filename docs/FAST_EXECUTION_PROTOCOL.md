# Fast Execution Protocol

## Goal
Improve throughput by reducing rework, not by skipping verification.

### During implementation
1. Search once, map dependencies.
2. Implement one vertical slice.
3. Run only local tests for the changed slice.
4. Repeat.
5. Run adversarial tests once the slice is complete.
6. Run full regression once before readiness.

### Avoid
- repeatedly running the full suite after tiny edits;
- broad refactors unrelated to the PR;
- speculative future architecture;
- duplicate services/models;
- generating documentation that merely restates code;
- checking boxes without evidence.

### Prefer
- existing helpers/fixtures;
- parameterized tests for many attack variants;
- factory helpers for tenant/brand isolation tests;
- service-level contracts with narrow interfaces;
- idempotent operations;
- explicit state machines;
- one source of truth for permissions and context.

## First-pass acceptance target
A PR should reach CTO review only after the agent believes an adversarial senior engineer cannot find:
1. an alternate entry path bypass,
2. tenant/brand leakage,
3. fake success,
4. lifecycle bypass,
5. disconnected dependency,
6. missing negative test,
7. accidental future-scope implementation.
