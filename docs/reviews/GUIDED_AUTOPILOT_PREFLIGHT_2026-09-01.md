# Guided Autopilot and Research — Immutable Preflight

Date: 2026-09-01
Branch: `codex/guided-autopilot`
Status: AUTHORIZED by the founder's request to reduce manual work and auto-populate useful text.

## Governing contract

- PR0–PR7 remain frozen ownership contracts.
- `docs/SCALEEZY_AUTONOMOUS_SOCIAL_OS_CLOSURE.md` governs the additive Growth Engine and Autopilot surfaces.
- `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` are not present in this checkout; no substitute contract is invented.
- Existing Context Gateway, AIRouter, durable jobs, review and publishing owners remain unchanged.

## Scope

- Derive editable Autopilot policy suggestions from the selected client's existing Brand Master fields.
- Derive an editable research mission and focus areas from the same brand profile.
- Replace the separate create-then-run happy path with one explicit `Create & run` action.
- Preserve the existing policy control centre, execution ledger and manual re-run action.
- Keep advanced mode, format, account and limit controls available without making them prerequisites to starting.
- Report a saved-policy/failed-run partial outcome honestly if the second request fails.

## Explicit exclusions

- No scheduled generation, automatic publishing, automatic replies or hidden consequential action.
- No tenancy, RBAC, Brand Brain, Context Gateway, AIRouter, billing, publishing or credential changes.
- No provider-specific prompt or model choice.
- No schema, migration or backend API contract change.

## Dependency graph

`member → selected workspace → current brand DTO → deterministic editable suggestion → policy create → existing trigger action → durable Autopilot run → existing generation/review owners`

`member → selected workspace → current brand DTO → deterministic editable research mission → existing research-run API → verified cited findings`

## Entry paths and invariants

| Entry path | Required invariant |
| --- | --- |
| Initial Autopilot load | Fill only blank fields; never overwrite user edits during reload. |
| Refill action | Explicitly replace the three suggestion fields from the current Brand Master. |
| Create & run | Create through the existing admin-scoped endpoint, then trigger only the returned policy ID. |
| Trigger failure after create | State that the policy was saved and the run did not start; keep the policy visible and retryable. |
| Research load | Fill only blank fields from the selected brand; keep user freedom to edit any text. |
| Workspace switch | Existing current-brand and `X-Workspace-Id` resolution remain authoritative. |

## Requirement-to-proof map

- Brand-aware defaults: code review of the pure suggestion builders plus TypeScript compilation.
- No overwritten edits: state updates fill blank fields only; explicit refill is separately labelled.
- One-click run: frontend calls existing policy-create then returned-policy trigger endpoints in order.
- Honest partial failure: distinct success and error messages for create failure versus trigger failure.
- No publishing bypass: no publishing endpoint or Autopilot mode is added or called.
- Regression gate: focused ESLint, TypeScript and production frontend build.

## Risk classification

- GREEN: deterministic copy helpers, state initialization, progressive disclosure and button copy.
- AMBER avoided: no backend aggregation endpoint is needed because the current brand endpoint already returns the required profile fields.
- RED avoided: no architecture, provider, tenancy, billing, review or publishing change.
