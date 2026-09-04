# Tab closure release — immutable integration preflight

- Authorization: user requested “completet this” after the completed, verified two-field integration was reported as not pushed/deployed. Finish the existing delivery through PR/release gates; no new product scope.
- Current feature base: `5a3a1ab3` on `codex/tab-by-tab-product-closure` plus the approved contact-field integration.
- Fresh remote base: `c25bb8cd127d82262d3dbfc669aa75141536a21a`, PR24 merged Claude's signup/contact work into main. Earlier branch-only attribution reports are historical snapshots, not current remote status.
- Reviewed: root/frontend AGENTS.md, CTO_REVIEW_LOG.md, contact preflight/self-review, prior integrated closure evidence, render.yaml, current upstream commit list/stat. Root PR_EXECUTION_TASKS.md and API_AND_DATA_CONTRACTS.md remain absent.

## Scope and preservation rules

Commit only the approved contact code, migrations, tests and evidence; preserve local scratch files/client screenshots and unrelated working files. Merge current main into the feature branch without rewriting published history. Preserve main's signup collection, alerting and platform notification work. Resolve overlapping contact fields once, retaining their original database column/migration identity, current input accessibility/length limits and the shared save queue.

The existing empty merge migration joins guardrails/contact schema histories; do not create a second AddField or rename an applied migration. Preserve frozen tenancy/RBAC, Brand Brain, Context Gateway, provider and publishing ownership. Do not change credentials, notification configuration, infrastructure, plan or production records as part of release.

## Entry paths and gates

User form → existing workspace/role → Brand serializer/model → save/reload remains covered by the contact tests. Upstream signup/alert/task paths are preserved and included in the fresh combined backend gate. Frontend conflicts require fresh type/lint/build verification. Validate the complete migration graph and existing full regression after integrating current main. Use PR checks/reviews and known commit IDs to gate merge; never bypass a failing required check or dismiss review findings without resolving them.

Render's existing backend build applies migrations before startup and runs production_integrity. Verify actual backend/frontend/worker revision and status through available authorized deployment access; queued or building is not live. If deployment access or release authorization is blocked, finish unaffected safe work and report the exact missing step instead of claiming completion.

## Stop decision

PROCEED with bounded integration and normal release gates. STOP for conflicting product intent, destructive migrations, missing authority or mandatory failing checks. Existing optional columns and original migration identities must survive without duplicate definitions.
