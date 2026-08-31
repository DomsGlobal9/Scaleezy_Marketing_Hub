# Platform Health Signal Activation — Immutable Execution Preflight

## Identity
- PR: Post-closure state-honesty correction
- Commit/branch at preflight: `dcd278fe` / `codex/p0-performance-recovery`
- Authorized scope: make the existing knowledge and inspiration health signals report their now-live durable states.
- Explicitly out of scope: new health tiles, processor changes, model changes, UI redesign, tenancy/RBAC changes, PR7 changes.
- Latest instruction reviewed: knowledge and inspiration processing landed, but `apps/common/platform_health.py` still reports their sensors as unmonitored.
- Missing repository contracts: `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` remain absent; `docs/reviews/FINAL_CORE_CLOSURE_PREFLIGHT_2026-08-24.md` and its self-review are the current implementation contract.

## Existing architecture to reuse
| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | Platform health endpoint and explicit platform-admin permission | No boundary change |
| Durable state | `BrandSource.status`, `BrandInspiration.analysis_status` | Count authoritative terminal/review states |
| Lifecycle eligibility | Active workspaces; inspiration retrieval eligibility | Exclude inactive and revoked work |
| API/UI contract | Existing signal keys, labels, `Signal.as_dict()` | Preserve payload shape |
| Tests | `apps.common.test_platform_health`, `apps.platform.tests` | Replace stale dead-sensor expectations and prove counts |

## Dependency graph
Processor/task → durable source or inspiration state → `platform_signals()` → platform health API → operator health tiles → focused and regression tests.

## Entry-path matrix
| Capability | Request action | Job/internal writer | Health reader |
|---|---:|---:|---:|
| Knowledge processing | existing `process` action | `process_source()` writes `FAILED` / `NEEDS_REVIEW` | count authoritative source status |
| Inspiration analysis | existing `analyze` action | `analyze_inspiration()` writes `FAILED` | count eligible inspiration status |

## Requirement → implementation → test plan
| Req | Requirement | Planned code path | Planned test | Failure/security case |
|---|---|---|---|---|
| PH-1 | Knowledge failure is live | `platform_signals()` | failed source count | inactive clients excluded |
| PH-2 | Knowledge review is live | `platform_signals()` | review source count | count sources, not memories |
| PH-3 | Inspiration failure is live | `platform_signals()` | failed inspiration count | archived/revoked references excluded |
| PH-4 | Health payload is honest | existing API serializer | numeric display and unmonitored absence | nonzero live rows affect attention |

## Risk scan
- Cross-tenant/cross-brand FK: N/A; read-only aggregate over authoritative rows.
- Lifecycle integrity: preserve existing writers; filter non-actionable inspirations through eligibility.
- State honesty: the purpose of this correction; no dead signal may remain labelled live or vice versa.
- Migration/provider/storage/billing: N/A.
- RED autonomy conditions: none.

## Stop decision
- PROCEED.
- This is a read-only health aggregation correction using existing contracts and durable state.
