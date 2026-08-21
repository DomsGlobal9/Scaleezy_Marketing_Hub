# CLAUDE_START_HERE.md — Scaleezy Marketing Hub Handoff

## Role
You are taking over active development of **Scaleezy Marketing Hub** as the primary coding executor.

You are **not** the product owner or CTO reviewer. Your job is to execute the approved architecture faithfully, efficiently, and with strong engineering discipline.

## Repository
`https://github.com/DomsGlobal9/Scaleezy_Marketing_Hub.git`

## Active branch
`marketinghub/merge`

## Current approved state
- PR0: approved
- PR1: approved
- Current authorized work: **PR2 — Inspiration Intelligence Foundation**
- Do not restart, rewrite, or reinterpret PR0/PR1 unless a regression caused by PR2 requires a targeted fix.
- Do not begin PR3 until PR2 has been independently reviewed and approved.

## Mandatory read order BEFORE coding
1. `AGENTS.md`
2. `SCALEEZY_M1_MASTER_BLUEPRINT.md`
3. `PR_EXECUTION_TASKS.md`
4. `API_AND_DATA_CONTRACTS.md`
5. `INTEGRATION_CHECKLIST.md`
6. `docs/CTO_REVIEW_LOG.md`
7. `docs/FAST_EXECUTION_PROTOCOL.md`
8. `docs/PR2_EXECUTION_OVERRIDE.md`
9. Current repository implementation and tests relevant to PR2

Treat `AGENTS.md` as the governing engineering operating system for this build.

## PR2 authorized scope
Build ONLY:

`BrandInspiration → original source/provenance → InspirationSignal → explicit user annotation → AI/user origin distinction → liked/disliked/neutral semantics → tenant/brand isolation → APIs → tests.`

## Explicitly out of scope for PR2
Do NOT build:
- multimodal AI analysis pipeline
- Brand Brain compiler
- Context Gateway / retrieval
- generation integration
- universal learning
- performance learning
- full onboarding/calibration UI
- speculative future infrastructure

If a future dependency is needed only for type/contract continuity, create the smallest safe interface necessary. Do not implement the future feature.

## Required execution artifacts
Before coding create:
- `docs/reviews/PR02_PREFLIGHT.md`
- `docs/reviews/PR02_FLOW_MATRIX.md`
- `docs/reviews/PR02_SECURITY_ATTACK_MATRIX.md`

Use the immutable templates under `docs/templates/`.

After implementation create:
- `docs/reviews/PR02_SELF_REVIEW.md`

Do not overwrite the templates or prior PR evidence.

## Evidence gate
Every review line must be exactly one of:
- **PASS** — include concrete evidence
- **FAIL** — fix before readiness
- **N/A** — include a precise reason
- **NOT VERIFIED** — PR is not ready

A PASS without test/code evidence is invalid.
N/A is not PASS.
Any mandatory FAIL or NOT VERIFIED means do not declare PR2 ready.

## Required PR2 integrity rules
- Inspiration must belong to the authenticated workspace and brand.
- If an inspiration references `BrandSource`, that source must belong to the same workspace AND same brand.
- Brand assignment must not be silently movable after creation.
- Inspiration signals must remain transitively tied to their inspiration's workspace/brand.
- Explicit user preference and AI-derived inference must never be indistinguishable.
- AI-inferred signals must never silently override explicit user-confirmed preference.
- `liked / disliked / neutral` semantics must be explicit, not inferred merely from weight.
- Revoked/archived references must become ineligible for future retrieval.
- Original inspiration and derived signals must be separately addressable.
- No cross-tenant sharing of raw inspiration data.

## Required adversarial tests
At minimum test:
1. Tenant A creates inspiration for Tenant B brand.
2. Tenant A references Tenant B source.
3. Same workspace: Brand A inspiration references Brand B source.
4. PATCH attempts to move inspiration to another brand.
5. Viewer mutation is denied.
6. Signal is attached to another tenant/brand inspiration.
7. Direct mutation attempts to convert AI-derived signal into user-confirmed origin.
8. Archived/revoked source/reference eligibility is represented honestly.
9. Any alternate mutation path (POST, multipart, PUT, PATCH, custom action) enforces the same isolation rules where applicable.

## Working style
Optimize for first-pass acceptance.

Use:
- inspect before coding
- existing architecture before new abstraction
- targeted tests during implementation
- adversarial tests before readiness
- one full backend regression at the end
- frontend checks only if frontend is affected

Avoid:
- broad unrelated refactors
- duplicate services/models
- speculative future work
- fake success states
- stale checklists
- claims of PASS without evidence

## Stop conditions
Stop and report rather than improvising if PR2 appears to require:
- changing tenancy/RBAC architecture
- destructive migrations
- changing Brand Brain contract
- bypassing existing AI architecture
- adding infrastructure
- changing billing/security semantics
- weakening provenance
- altering approved product scope

## Handoff completion
When PR2 is complete:
1. Push changes to `marketinghub/merge`.
2. Provide a concise summary:
   - files changed
   - migrations
   - API additions
   - tests added
   - total tests/result
   - security attacks verified
   - known deferred items
3. Stop.
4. Do NOT start PR3.

PR2 will be independently reviewed after push.
