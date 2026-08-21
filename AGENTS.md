# AGENTS.md — Scaleezy Coding Agent OS V4

## Purpose
Build Scaleezy quickly WITHOUT trading away correctness. Optimize for first-pass acceptance, not raw code volume.

## North-star metric
Minimize total cycle time:
UNDERSTAND → IMPLEMENT → PROVE → CTO REVIEW → MERGE

A fast implementation that returns for rework is slower than a slightly more deliberate implementation that passes first review.

## Mandatory read order — every PR, every rework
1. `AGENTS.md`
2. Current approved architecture / implementation contract
3. Current PR task in `PR_EXECUTION_TASKS.md`
4. `API_AND_DATA_CONTRACTS.md`
5. `docs/CTO_REVIEW_LOG.md`
6. Latest CTO review for the current PR, if any
7. Existing code and tests in every affected dependency path
8. Create a NEW immutable PR preflight from the template

After any CTO review: RE-READ the review, update the current PR evidence files, and re-run affected attack paths. Never rely on the original preflight after requirements change.

## Operating principles

### 1. Inspect before coding
Search for existing:
- models and relations
- serializers / validators
- permissions / workspace scoping
- service abstractions
- task/job infrastructure
- provider adapters
- storage services
- API conventions
- frontend API client/hooks
- tests and fixtures
Reuse established patterns unless the current contract explicitly changes them.

### 2. Think in complete dependency graphs
Never implement “a model” or “an endpoint” in isolation.
Trace:
User → Auth → Workspace → Role → Brand → Entry Path → Validation → Persistence → Job/Service → State → Consumer → UI → Failure → Audit/Lineage → Tests

### 3. Enumerate EVERY entry path
Security and integrity rules must hold across all applicable entry paths:
JSON POST, multipart upload, PUT, PATCH, custom actions, jobs, retries, imports, internal service calls, admin paths, callbacks/webhooks where applicable.

### 4. Evidence, not assertions
Every self-review item MUST be exactly one:
- PASS — with concrete evidence
- FAIL — must fix before ready
- N/A — with precise reason
- NOT VERIFIED — PR is NOT ready

A PASS without evidence is invalid.

Valid evidence:
- named automated test + result
- exact code path + named test
- migration check result
- build/typecheck command result
- API response verified by test

Comments like “serializer prevents it” are NOT sufficient evidence.

### 5. Adversarial self-review
After implementation, change role from developer to attacker/reviewer. Try to violate:
tenant isolation, same-workspace brand integrity, RBAC, lifecycle rules, idempotency, retries, source provenance, provider boundaries, storage boundaries, and state honesty.

### 6. No fake completion
Never return or persist READY/SUCCESS/COMPLETE/PUBLISHED/TRAINED/PROCESSED when the real work did not complete.
Not implemented means NOT_IMPLEMENTED, disabled, or unavailable — never pretend success.

### 7. PR boundary is a hard boundary
Implement only the authorized PR.
Future dependencies may be represented only by a minimal contract/interface when required for current correctness.
Do not “helpfully” implement future PRs.

### 8. Stop conditions
STOP and report before changing:
- tenant/RBAC architecture
- destructive migrations/data loss
- Brand Brain contract
- Context Gateway/AIRouter ownership
- billing/security semantics
- existing publishing architecture
- infrastructure stack
- agreed user journey
- secrets/credential handling
- any requirement conflict that changes product semantics

## Autonomy
GREEN: naming, helpers, fixtures, safe refactors, tests, non-breaking indexes.
AMBER: small abstractions/schema additions required by current contract — implement and document.
RED: architecture/product/security/infrastructure changes — stop and escalate.

## Fast execution loop
### Phase A — Reconnaissance
Time-box repo inspection. Produce:
- affected dependency graph
- entry-path matrix
- requirement-to-test map
- risks / RED flags

### Phase B — Vertical implementation
Implement one complete vertical slice at a time. Avoid broad half-finished scaffolding.

### Phase C — Focused verification
During coding run only changed-module + security tests.

### Phase D — Adversarial verification
Run mutation/attack matrix.

### Phase E — Full gate
Before ready:
- full backend regression
- frontend build/type/lint if affected
- migrations check if affected
- immutable self-review report
- zero FAIL / zero NOT VERIFIED on mandatory gates

## Definition of Done
Done means integrated, tenant-safe, permission-safe, state-honest, provenance-preserving, failure-aware, retry-aware where relevant, regression-safe, and proven by evidence.
