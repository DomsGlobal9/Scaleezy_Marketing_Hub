# AGENTS.md — Scaleezy Coding Agent Operating System

## Mission
Implement Scaleezy Marketing Hub safely, incrementally, and in strict alignment with the approved M1 architecture.

## Mandatory read order before every PR
1. `AGENTS.md`
2. `SCALEEZY_M1_MASTER_BLUEPRINT.md`
3. `PR_EXECUTION_TASKS.md`
4. `API_AND_DATA_CONTRACTS.md`
5. `docs/CTO_REVIEW_LOG.md`
6. `docs/PR_PREFLIGHT.md`
7. Relevant existing repository code/tests

## Core engineering rules
- Inspect before coding.
- Reuse existing architecture before creating a new abstraction.
- No orphan models, APIs, jobs, UI actions, or state transitions.
- Every tenant-owned object must resolve safely to workspace and brand.
- Validate every foreign-key relationship server-side.
- Never trust client-supplied workspace/brand relationships.
- Never let `is_staff` bypass tenant isolation.
- Lifecycle state changes must use controlled actions when state semantics matter.
- Never expose placeholder behavior as READY/SUCCESS/COMPLETE.
- Preserve existing AIRouter/provider abstraction.
- AI providers generate; Scaleezy owns memory, rules, context, lineage, and learning.
- Brand `creative_brain` is compiled state, not source-of-truth storage.
- Universal learning must never contain raw tenant data.
- Do not rewrite working publishing, billing, auth, analytics, or jobs unless the current PR explicitly requires it.
- No new infrastructure unless explicitly approved.
- Stop at the current PR boundary.

## Dependency-chain thinking
For every feature reason through:
User → Auth → Workspace → Role → Brand → Serializer/Input → Validation → Model → Storage → Job → State → Downstream Service → UI → Failure → Audit → Tests.

If any link is missing, the feature is incomplete.

## Autonomy boundaries
### GREEN — decide autonomously
- helper names
- test fixtures
- small internal refactors
- indexes that are clearly safe
- implementation details matching existing patterns

### AMBER — implement and document
- new helper abstractions
- additional non-breaking indexes
- minor schema additions necessary for the agreed contract
- improved error typing

### RED — stop and report
- replacing existing architecture
- weakening tenant isolation/RBAC
- destructive migrations
- changing Brand Brain contract
- bypassing Context Gateway/AIRouter
- adding Celery/Redis/vector DB/new infra
- changing billing/security semantics
- changing agreed product flow
- deleting working capabilities

## Before coding
Complete `docs/PR_PREFLIGHT.md`.

## Before pushing
Complete `docs/PR_SELF_REVIEW.md` and `docs/SECURITY_ATTACK_CHECKLIST.md`.

If any mandatory gate fails, do not declare the PR ready.

## Definition of Done
A feature is done only when:
- data model is correct;
- tenant/brand isolation is enforced;
- permissions are correct;
- UI/API/service/job dependencies are connected;
- failure and retry states are honest;
- lineage/provenance is preserved;
- tests cover happy path and adversarial path;
- existing flows are regression-safe;
- no placeholder is shown as finished behavior.
