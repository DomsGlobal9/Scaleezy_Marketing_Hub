# CTO_REVIEW_LOG.md

Permanent engineering lessons from CTO reviews. Read before every PR.

## PR0 lessons
### PR0-001 — Staff is not a tenant bypass
`is_staff` must not expose all tenant data. Explicit workspace membership remains required.

### PR0-002 — Baseline docs must match the live repository
Architecture documentation must reflect the current implementation, not an older package or prototype.

### PR0-003 — Environment-dependent tests are invalid
Tests for missing provider configuration must use explicit test settings/mocks rather than live `.env` state.

### PR0-004 — OAuth callbacks must be idempotent at the client edge
Frontend callbacks must guard against duplicate lifecycle execution where repeated code exchange would be harmful.

## PR1 lessons
### PR1-001 — Validate all tenant-owned foreign keys
If Workspace A submits a Brand/Source/Memory from Workspace B, reject server-side.

### PR1-002 — Validate same-brand relationships
Even inside one workspace, Brand A memory must not silently reference Brand B source unless the contract explicitly allows it.

### PR1-003 — Lifecycle fields are not normal PATCH fields
`status`, confirmation, rejection, supersession, conflict resolution, publish/review state, etc. must use controlled transitions.

### PR1-004 — Never mark stubbed processing READY
A stub may exist internally, but it cannot report completed processing when no extraction/transcription/analysis occurred.

### PR1-005 — Conflict resolution must be real or unavailable
Do not expose a fake `resolve_conflict` endpoint that merely changes status.

### PR1-006 — Negative-path tests are mandatory
Test cross-tenant FK injection, cross-brand FK injection, role failures, invalid lifecycle changes, and duplicate/retry behavior.

## Global permanent rules
### GLOBAL-001 — No fake completion
Do not represent queued, stubbed, partially processed, or failed work as successful.

### GLOBAL-002 — No orphan functionality
Every feature must be connected end-to-end.

### GLOBAL-003 — One intelligence owner
Scaleezy owns Brand Brain, Context, Learning, provenance and lineage. AI providers are replaceable executors.

### GLOBAL-004 — Preserve source-of-truth provenance
Compiled Brand Brain can always be rebuilt from underlying authoritative records.

### GLOBAL-005 — Security review is part of implementation
Tenant isolation is not a final QA step. It is a design constraint for every serializer, model relation, action and task.
