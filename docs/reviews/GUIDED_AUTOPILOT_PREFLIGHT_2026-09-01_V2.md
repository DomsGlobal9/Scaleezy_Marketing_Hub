# Guided Autopilot and Research — Immutable Preflight V2

Date: 2026-09-01
Branch: `codex/guided-autopilot`
Status: AUTHORIZED by the founder's request to reduce manual work and auto-populate useful text.
Supersedes: `GUIDED_AUTOPILOT_PREFLIGHT_2026-09-01.md` after dependency review found an existing queue-failure honesty gap on the Trigger path.

## Governing contract

- PR0–PR7 remain frozen ownership contracts.
- `docs/SCALEEZY_AUTONOMOUS_SOCIAL_OS_CLOSURE.md` governs the additive Growth Engine and Autopilot surfaces.
- `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` are not present in this checkout; no substitute contract is invented.
- Existing Context Gateway, AIRouter, durable jobs, review and publishing owners remain unchanged.

## Scope

- Derive editable Autopilot policy suggestions from the selected client's existing Brand Master fields.
- Derive an editable research mission and focus areas from the same brand profile.
- Replace the separate create-then-run happy path with one explicit `Create & run` action composed from the existing API operations.
- Preserve the existing policy control centre, execution ledger and manual re-run action.
- Keep advanced mode, format, account and limit controls available without making them prerequisites to starting.
- If durable-task enqueue fails, persist the run as `FAILED` with a safe retryable reason and return `503`; never leave an unqueued run looking `QUEUED`.
- Report a saved-policy/failed-run partial outcome honestly if the trigger request fails after policy creation.

## Explicit exclusions

- No scheduled generation, automatic publishing, automatic replies or hidden consequential action.
- No tenancy, RBAC, Brand Brain, Context Gateway, AIRouter, billing, publishing or credential changes.
- No provider-specific prompt or model choice.
- No schema or migration change and no new endpoint.

## Dependency graph

`member → selected workspace → current brand DTO → deterministic editable suggestion → policy create → existing trigger action → durable Autopilot run → existing generation/review owners`

`member → selected workspace → current brand DTO → deterministic editable research mission → existing research-run API → verified cited findings`

## Entry paths and invariants

| Entry path | Required invariant |
| --- | --- |
| Initial Autopilot load | Fill only blank fields; never overwrite user edits during reload. |
| Refill action | Explicitly replace the three suggestion fields from the current Brand Master. |
| Create & run | Create through the existing admin-scoped endpoint, then trigger only the returned policy ID. |
| Trigger enqueue failure | Persist a failed run with `QUEUE_ENQUEUE_FAILED`, return `503`, and leave the policy retryable. |
| Trigger failure after create | State that the policy was saved and the run did not start; keep the policy visible and retryable. |
| Research load | Fill from the selected brand while keeping every field editable and public-web sources unrestricted. |
| Workspace switch | Existing current-brand and `X-Workspace-Id` resolution remain authoritative. |

## Requirement-to-proof map

- Brand-aware defaults: pure suggestion builders plus TypeScript compilation.
- No overwritten edits: Autopilot reload fills blank fields only; Growth remounts its draft only when the selected brand ID changes.
- One-click run: frontend calls existing policy-create then returned-policy trigger endpoints in order.
- Honest partial failure: distinct success and error messages for create failure versus trigger failure.
- Honest queue state: backend test patches enqueue failure and proves `503`, durable `FAILED`, error code, completion time and no task ID.
- No publishing bypass: existing `AUTO_PUBLISH` rejection and review-state tests remain in the focused backend gate.
- Regression gate: Autopilot focused tests, targeted ESLint, TypeScript, production frontend build, Django check and migration drift check.

## Risk classification

- GREEN: deterministic copy helpers, state initialization, progressive disclosure and button copy.
- AMBER: harden the existing Trigger action's task-enqueue failure state without changing its success contract.
- RED avoided: no architecture, provider, tenancy, billing, review or publishing change.
