# Performance, Monetization and Governed Autopilot — Immutable Preflight

Date: 2026-09-01
Branch: `feat/performance-autopilot-closure`
Status: AUTHORIZED

## Frozen boundaries

- PR0–PR7 remain frozen contracts.
- Context Gateway owns context assembly; AIRouter owns provider selection.
- Existing publishing services own external publishing.
- The database-backed task worker remains the only durable job executor and scheduler sweep.
- Learning Fabric owns learning events. Performance observations are neutral evidence, not human verdicts.
- No provider-specific selection enters product services.

## Dependency graph

`member → selected workspace → social connection → published job item → platform metric fetch → source observation → derived analytics → neutral performance learning event`

`admin policy → scheduler sweep → durable autopilot run → Context Gateway/AIRouter generation request → persisted draft → review/publishing owners`

## Entry paths

| Entry path | Required invariant |
| --- | --- |
| Analytics read | Selected-workspace membership and tenant-only query |
| Platform metric sync | Editor role, connected account, published item, bounded fetch, honest failure |
| Conversion/revenue intake | Editor role, idempotency key, non-negative values, same-workspace content/lead references |
| Policy create/update | Admin role, same-workspace brand/connections, explicit mode and limits |
| Manual autopilot run | Editor role, enabled and unpaused policy, active client, caps enforced |
| Scheduled autopilot run | Existing scheduler only, one run per policy/time slot, durable task |
| Emergency stop | Admin role, prevents future and in-flight uncommitted steps |

## Requirement-to-test map

- Tenant isolation: cross-workspace observation, lead, revenue, policy and run references are refused.
- Idempotency: repeated platform observation/external revenue event cannot duplicate facts.
- State honesty: failed metric fetch and failed generation are FAILED, never COMPLETE.
- Performance truth: aggregates are rebuilt from observation rows; UI shows freshness/source.
- Learning safety: performance observations emit `PERFORMANCE_OBSERVED` with `NEUTRAL` outcome only.
- Governance: caps, pause and emergency stop are checked both at scheduling and task execution.
- Ownership: autopilot queues the existing generation task and does not call a provider or publisher directly.

## RED/AMBER decisions

- AMBER: additive analytics observation/revenue schema is required to turn the existing empty aggregate tables into derived projections.
- AMBER: a small `apps.autopilot` orchestration app is required; it owns policies/runs only, not routing, context, generation or publishing.
- RED avoided: no changes to tenant/RBAC, Brand Brain, Context Gateway, AIRouter, credential storage, billing semantics or publishing architecture.

## Proof gate

Focused module/security tests during implementation, then full backend regression, migration drift check, Django check, frontend format/type/lint/build, and immutable self-review with no FAIL or NOT VERIFIED.
