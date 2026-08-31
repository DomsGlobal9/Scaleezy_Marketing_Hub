# Mobile Hardening — Immutable Execution Preflight

## Identity
- PR: Mobile hardening (frontend-only additive recovery)
- Commit/branch at preflight: `codex/mobile-hardening` from `origin/main` at `04b5d611`
- Authorized scope: founder request on 2026-08-31 to fix the verified mobile gaps: touch targets, dense mobile tabs, horizontally scrolling operational tables, slow Admin first-use rendering, and responsive verification.
- Explicitly out of scope: Claude's `feat/pagination-and-async-generation` branch; list response shapes; async generation/polling; backend APIs; tenancy/RBAC; Brand Brain; AIRouter ownership; publishing semantics; broad visual redesign.
- Latest CTO instruction reviewed: `docs/CTO_REVIEW_LOG.md`; frozen boundaries reviewed in `docs/FINAL_CORE_CLOSURE_SPRINT.md`.
- Repository note: the mandatory files `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` are not present on this baseline. The founder's explicit request is the execution task; this PR does not change an API/data contract.

## Existing architecture to reuse
| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | Existing route guards, selected workspace and server enforcement | Unchanged |
| Models | No model work | N/A |
| API | Existing frontend API clients and response shapes | Unchanged |
| Jobs | No job work | N/A |
| Storage | No storage work | N/A |
| AI/provider | Existing provider-neutral Admin console | Preserve; change presentation/loading only |
| Frontend | TanStack Router, Radix controls, Tailwind breakpoints and existing card/table patterns | Reuse and extend |
| Tests | Frontend typecheck, lint, build plus live 320/390/768 viewport verification | Required evidence |

## Dependency graph
User → Auth → selected Workspace → role-gated route → existing API client → existing server validation/state → responsive UI presentation → honest loading/error state → focused frontend gates and live viewport verification.

## Entry-path matrix
| Mutation / capability | POST JSON | Multipart | PUT | PATCH | Custom action | Job/internal | Other |
|---|---:|---:|---:|---:|---:|---:|---:|
| Responsive presentation | N/A | N/A | N/A | N/A | N/A | N/A | Hub/Platform navigation and viewport layout only |
| Admin progressive loading | N/A | N/A | N/A | N/A | Existing refresh only | N/A | Existing GETs; response contracts unchanged |

## State machine
| Object | From | Action | To | Who may perform | Invalid transitions |
|---|---|---|---|---|---|
| Product state | Any | Responsive hardening | Same state | Same existing role | No lifecycle fields are changed |
| Admin usage panel | Loading | Usage GETs settle | Loaded or honest error | Existing OWNER/ADMIN | Never show zero/empty as fact while still loading |

## Requirement → implementation → test plan
| Req ID | Requirement | Planned code path | Planned test | Security/failure case |
|---|---|---|---|---|
| MOB-001 | Comfortable mobile controls | shared Button/Input/Select/Tab primitives; nav/filter overrides | typecheck/build + 320/390 live target inspection | Disabled/focus behavior preserved |
| MOB-002 | Usable Brand Master/Admin section navigation | Brand Master and AI Admin responsive selectors | live select/tab navigation at 320/390/768 | URL-backed selected tab remains authoritative |
| MOB-003 | Operational data readable without sideways hunting | client, team, permission, learning, signup, standards and admin card views below desktop | live 390/768 inspection; desktop table retained | Actions call unchanged handlers |
| MOB-004 | Admin becomes usable before usage history finishes | `AIProvidersPanel` essential and deferred request groups | typecheck/build + live first-load inspection | Deferred failure is visible; no fake zero |
| MOB-005 | No page-level horizontal overflow | existing responsive shells plus mobile cards | live 320/390/768 overflow checks | Console/hub drawers still close on navigation |

## Risk scan
- Cross-tenant FK: N/A — no request body or object relationship changes.
- Cross-brand FK: N/A.
- Partial PATCH: Existing handlers unchanged.
- Direct lifecycle mutation: N/A.
- Duplicate/retry: Existing refresh handlers retained.
- Storage: N/A.
- External URL / SSRF: N/A.
- Provider failure: Existing API error path retained; deferred usage failure becomes explicit.
- Revocation/deletion: Existing Admin actions retained unchanged.
- Data lineage: N/A.
- Billing/quota: Usage data remains read-only and honest while loading.
- RED autonomy conditions: None. No product, security, billing, provider-routing or infrastructure semantics change.

## Stop decision
- PROCEED
- Reason: frontend-only GREEN scope, additive responsive presentation, no architecture or API contract change, isolated from Claude's active pagination/async branch.
