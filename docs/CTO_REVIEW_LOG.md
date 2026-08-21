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

## PR1 lessons (V4 additions)
### PR1-007 — Multipart/upload paths are mutation paths
Upload endpoints must receive the same tenant/brand validation as JSON CRUD.

### PR1-008 — Partial PATCH must validate the effective final object
Validation must consider unchanged instance values, not just the submitted fields.

### PR1-009 — Brand assignment is immutable for provenance-bearing records
Brand may only move through an explicit transfer workflow, which does not exist yet.

### PR1-010 — Revoked/archived sources stop influencing intelligence
Archived references must become ineligible for future retrieval.

### PR1-011 — Supersession must not self-reference or cycle
Applies when supersession is implemented.

## Global permanent rules (V4 additions)
### GLOBAL-006 — A checklist PASS requires evidence
Named test + result, or exact code path + named test. Assertions are not evidence.

### GLOBAL-007 — N/A is not PASS
N/A requires a precise reason.

### GLOBAL-008 — NOT VERIFIED blocks readiness
### GLOBAL-009 — Refresh the mental model after CTO rework
Stale preflight assumptions are invalid once requirements change.

### GLOBAL-010 — Validate every mutation path
Not only the primary endpoint: JSON, multipart, PUT, PATCH, custom actions, jobs and internal service calls.
