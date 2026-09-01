# Platform Speed and Trust Hardening — Immutable Execution Preflight

## Identity

- PR: Platform speed and trust hardening
- Commit/branch at preflight: `04b5d611` / `codex/platform-speed-trust`
- Authorized scope: repair the measured Platform Clients and workspace AI Admin read-path bottlenecks; add honest server pagination; preserve the existing UI and every PR0–PR7 ownership boundary; prove tenant, RBAC, lifecycle, billing and routing behavior is unchanged.
- Explicitly out of scope: tenant/RBAC redesign, provider execution behavior, Brand Brain or Context Gateway ownership, billing limits, publishing, storage, schema migrations, infrastructure changes, or new product workflows.
- Latest CTO instruction reviewed: `docs/CTO_REVIEW_LOG.md`; latest related evidence is `P0_PRODUCTION_PERFORMANCE_FINAL_PASS_SELF_REVIEW_2026-08-31.md`.
- Repository gap: the `AGENTS.md`-named `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` do not exist. `docs/ARCHITECTURE.md`, the Final Core Closure review and existing endpoint/tests are the governing contracts.

## Existing architecture to reuse

| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | `PlatformView`, `IsPlatformAdmin`, workspace membership and `X-Workspace-Id` | Preserve every existing gate; optimize only after the server resolves authority. |
| Models | Existing workspace, brand, onboarding, subscription, usage, content, learning and routing models | No schema or lifecycle changes. |
| API | Standard `APIResponse`; `/api/platform/clients/`; workspace AI catalogue/providers/routes/usage | Keep envelopes and existing fields; add pagination metadata compatibly. |
| Jobs | Existing durable task system | N/A; this sprint changes read paths only. |
| Storage | Existing Supabase boundary | N/A. |
| AI/provider | `AIRouter` capability ownership and workspace provider assignments | Preserve execution routing; bulk only the read-only resolved-route projection. |
| Frontend | TanStack routes, central `api()`, selected workspace store | Render core AI controls independently from usage reporting; consume server pages without hidden client-wide assumptions. |
| Tests | Platform portfolio, controls, AI routing, permissions, frontend type/build | Add query ceilings, pagination contract/edge cases and exact resolved-route equivalence. |

## Dependency graph

Platform admin → JWT auth → `PlatformAdmin` authority → paginated workspace queryset → bulk portfolio snapshot → existing response fields → Clients UI → filters/search/page controls → honest loading/error states → tests.

Workspace admin → JWT auth → selected workspace header → active membership and ADMIN role → bulk catalogue/providers/routes projection → AI controls render → deferred usage reporting → tests.

## Entry-path matrix

| Mutation / capability | POST JSON | Multipart | PUT | PATCH | Custom action | Job/internal | Other |
|---|---:|---:|---:|---:|---:|---:|---:|
| Platform client portfolio | N/A | N/A | N/A | N/A | N/A | N/A | GET with page/filter/search/day inputs |
| Resolved AI routes | N/A | N/A | N/A | N/A | GET `routes/resolved` | AIRouter execution remains unchanged | Selected workspace header |
| AI Admin progressive loading | N/A | N/A | N/A | N/A | Existing reads only | N/A | Stale/unmounted request protection |

## State machine

| Object | From | Action | To | Who may perform | Invalid transitions |
|---|---|---|---|---|---|
| None | N/A | Read-only projection optimization | N/A | Existing platform/workspace admin gates | No lifecycle, billing, routing or credential state may be written |

## Requirement → implementation → test plan

| Req ID | Requirement | Planned code path | Planned test | Security/failure case |
|---|---|---|---|---|
| SPEED-001 | Page the client queryset before expensive work | `apps/platform/views_clients.py` | portfolio pagination contract and query ceiling | Invalid/out-of-range pages return an honest empty page; filters remain server-authoritative |
| SPEED-002 | Remove per-client onboarding writes and repeated quota/readiness queries from portfolio GET | bulk portfolio read model | exact row/flag equivalence tests | No GET may create/update onboarding; billing flags remain exact |
| SPEED-003 | Resolve all AI capabilities from one prefetched route/provider snapshot | `apps/ai/views.py` plus read helper | response equivalence and query ceiling | Disabled, unavailable, unassigned or unsupported providers remain excluded |
| SPEED-004 | Do not block AI controls on usage reporting | `ai-providers-panel.tsx` | TypeScript/build and focused component-state inspection | Core failure remains visible; usage failure is honest and isolated |
| SPEED-005 | Preserve live product behavior and authority | existing platform/AI permission suites | focused RBAC/cross-workspace tests plus full regression | Staff without platform authority and non-admin workspace members remain denied |

## Risk scan

- Cross-tenant FK: no writes; workspace AI reads remain scoped by the selected, authorized workspace.
- Cross-brand FK: no submitted brand id or relationship mutation.
- Partial PATCH: unchanged.
- Direct lifecycle mutation: explicitly removed from the portfolio GET path; no transition endpoint changes.
- Duplicate/retry: reads remain idempotent.
- Storage: N/A.
- External URL / SSRF: N/A.
- Provider failure: no provider call is made; only configured route metadata is projected.
- Revocation/deletion: every response is built from current rows; no cache crosses requests.
- Data lineage: no intelligence record changes.
- Billing/quota: response values and blocking semantics must remain exact; only aggregation changes.
- RED autonomy conditions: none. Architecture, authority, billing semantics, routing ownership and infrastructure remain frozen.

## Stop decision

- PROCEED
- Reason: the live production evidence isolates two existing read-path defects. The changes are query/projection/UI-loading optimizations with no migration, secret handling, lifecycle or architecture change.
