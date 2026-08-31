# P0 Production Performance Recovery — Immutable Execution Preflight

## Identity

- PR: P0 production performance recovery
- Commit/branch at preflight: `878bb0ea` / `codex/p0-performance-recovery`
- Authorized scope: remove the measured Brand Master load waterfall, eliminate repeated readiness and workspace-authorisation queries, reuse safe production database connections, and prove the existing user journey remains tenant-safe.
- Explicitly out of scope: tenancy/RBAC redesign, Brand Brain contract changes, AIRouter/provider changes, publishing changes, PR7 changes, UI redesign, broad cache migration, new infrastructure, or product behavior changes.
- Latest CTO instruction reviewed: `docs/CTO_REVIEW_LOG.md`; latest shipped review is `BRAND_MASTER_TAB_VISIBILITY_SELF_REVIEW_2026-08-31.md`.
- Repository gap: the `AGENTS.md`-named `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` do not exist in this repository. The frozen architecture and Final Core Closure contract were read instead.

## Existing architecture to reuse

| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | `IsWorkspaceMember`, `HasWorkspaceRole`, `X-Workspace-Id`, `WorkspaceScopedMixin` | Preserve every gate; only reuse the membership already proven on the request. |
| Models | Existing Workspace and Brand models | No schema or lifecycle change. |
| API | DRF response envelope and Brand Master ViewSet | Add one read-only `current` aggregate using the same scoped services and payload. |
| Jobs | Existing durable task system | N/A; no job behavior changes. |
| Storage | Existing Supabase storage service | N/A; no storage path changes. |
| AI/provider | Brand Brain compiler, Context Gateway, AIRouter | Read existing compiled state only; do not change ownership or routing. |
| Frontend | Central `api()`, selected workspace store, Brand Master route, brand editor | Replace two serial reads with one aggregate and hydrate the editor from that response. |
| Tests | Brand, context, permission and frontend build/type gates | Add query-count, aggregate-contract and cross-tenant tests; run affected and full gates. |

## Dependency graph

User → JWT auth → selected workspace header → active membership and role → current workspace Brand → Brand Master aggregate → readiness/compiled Brain read → hydrated Brand Master/editor UI → visible failure state → tenant/adversarial tests.

## Entry-path matrix

| Mutation / capability | POST JSON | Multipart | PUT | PATCH | Custom action | Job/internal | Other |
|---|---:|---:|---:|---:|---:|---:|---:|
| Brand Master performance aggregate | N/A | N/A | N/A | N/A | GET `brand-master/current` | N/A | Existing detail GET remains supported |
| Workspace authorization reuse | N/A | N/A | N/A | N/A | All already-gated reads | Internal fallback retained | Header/payload agreement unchanged |
| Database connection reuse | N/A | N/A | N/A | N/A | N/A | Process-level configuration | Health check before reuse |

## State machine

| Object | From | Action | To | Who may perform | Invalid transitions |
|---|---|---|---|---|---|
| None | N/A | Read-only optimization | N/A | Existing VIEWER-or-above gate | No lifecycle fields are written |

## Requirement → implementation → test plan

| Req ID | Requirement | Planned code path | Planned test | Security/failure case |
|---|---|---|---|---|
| PERF-001 | Preserve selected-client isolation while avoiding repeated membership queries | `apps/common/permissions.py`, `apps/common/mixins.py` | cached-membership query and cross-tenant tests | Cached membership must match the resolved workspace id |
| PERF-002 | Count readiness evidence once | `apps/context/services/readiness.py` | deterministic score/count tests plus query-count ceiling | Archived/ineligible evidence must remain excluded |
| PERF-003 | Load current Brand Master in one post-membership request | `apps/brands/services/current_brand.py`, `apps/context/views.py` | aggregate shape, pending/rejected behavior, cross-tenant tests | No caller-supplied brand/workspace may cross the selected tenant |
| PERF-004 | Avoid the frontend current-brand → overview waterfall and duplicate editor read | Brand Master data client, route and `useBrandSettings` initial hydration | typecheck/build and live request/DOM verification | Editor must still target the exact returned brand and retain save behavior |
| PERF-005 | Reuse healthy production DB connections safely | Django database settings | settings/system tests and full regression | Health checks prevent reuse of a dead connection; override remains configurable |

## Risk scan

- Cross-tenant FK: no writes; aggregate brand is resolved only inside the authorized selected workspace.
- Cross-brand FK: no submitted brand id on the new aggregate path.
- Partial PATCH: unchanged; editor continues using the existing brand detail PATCH.
- Direct lifecycle mutation: none.
- Duplicate/retry: reads remain idempotent.
- Storage: N/A.
- External URL / SSRF: N/A.
- Provider failure: N/A; no provider call occurs on load.
- Revocation/deletion: current-brand resolver preserves existing archived/pending/rejected semantics.
- Data lineage: compiled Brain is read through the existing resolver and never replaced.
- Billing/quota: N/A.
- RED autonomy conditions: none. Tenant/RBAC semantics and infrastructure stack remain unchanged; this is an additive read contract plus safe query/connection tuning.

## Stop decision

- PROCEED
- Reason: the measured bottleneck is on an existing read path. The implementation is additive, preserves all frozen ownership boundaries, performs no migration or lifecycle mutation, and has explicit tenant and regression gates.
