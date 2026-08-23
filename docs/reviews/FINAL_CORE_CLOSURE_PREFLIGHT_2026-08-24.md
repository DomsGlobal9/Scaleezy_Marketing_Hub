# Final Core Closure — Immutable Execution Preflight

## Identity
- PR: Final Core Closure (replacement for obsolete PR8–PR10 sequence)
- Commit/branch at preflight: `3ba4bd5` / `codex/final-core-closure`
- Authorized scope: `docs/FINAL_CORE_CLOSURE_SPRINT.md`
- Explicitly out of scope: staff SSO, payments/wallet, provider-specific product code, tenancy redesign, PR7 redesign, broad UI redesign.
- Latest instruction reviewed: founder requested rapid planning and execution of the frozen closure scope.
- Missing repository contracts: `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` are absent; the frozen closure document is execution authority.

## Existing architecture to reuse
| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | `WorkspaceScopedMixin`, `get_request_workspace`, `authorize_workspace`, role gates | No new bypass or cross-tenant mode |
| Models | `BrandSource`, `BrandMemory`, `BrandInspiration`, `InspirationSignal` | Extend state/trace only where required |
| API | Existing `process`, `analyze`, confirm/reject and retry action conventions | Replace honest 501s with queued work |
| Jobs | Django `@task`, database `TaskRun`, `enqueue_due_work` | Durable processing and refresh |
| Storage | `SupabaseStorageService.upload_and_describe` strict path | Make every persisted upload strict |
| AI/provider | `AIRouter` and capability adapters | TEXT, IMAGE_ANALYSIS and VIDEO_ANALYSIS only; provider-neutral |
| Frontend | Brand Master Knowledge/Inspirations panels, Review and Publishing history | Connect working lifecycle; no redesign |
| Tests | Existing tenancy fixtures, knowledge/inspiration attacks, lifecycle test | Extend focused paths, then one full gate |

## Dependency graph
User → auth → selected workspace → role → brand → source/inspiration mutation → same-tenant/brand validation → queued durable task → safe input extraction → AIRouter capability/fallback → candidate memory/signal + trace → human confirmation → Brand Brain rebuild → Context Gateway → generation → saved content → review → publishing settings → worker → feedback/learning → return journey → tests.

## Entry-path matrix
| Mutation / capability | POST JSON | Multipart | PUT/PATCH | Custom action | Job/internal |
|---|---:|---:|---:|---:|---:|
| Knowledge source | yes | yes | effective-object validation | process/retry/revoke | extract candidates |
| Inspiration | yes | yes | effective-object validation | analyze/retry/archive | infer/reconcile signals |
| Human authority | no generic state write | N/A | protected | confirm/reject | Brand Brain rebuild |
| Publishing | create now/scheduled | asset source | immutable execution record | retry/item retry | settings re-check + publish |
| Storage | metadata only | strict upload | N/A | generated persistence | no mock URL |

## State machine
| Object | From | Action | To | Who may perform | Invalid transitions |
|---|---|---|---|---|---|
| BrandSource | UPLOADED/FAILED | process/retry | QUEUED | EDITOR+ | ARCHIVED cannot process |
| BrandSource | QUEUED | worker claim | PROCESSING | worker | duplicate worker no-op |
| BrandSource | PROCESSING | candidate result/failure | NEEDS_REVIEW/FAILED | worker | never READY without real processing |
| BrandInspiration | NOT_ANALYSED/FAILED | analyze/retry | QUEUED | EDITOR+ | ARCHIVED cannot analyze |
| BrandInspiration | QUEUED | worker claim | PROCESSING | worker | duplicate worker no-op |
| BrandInspiration | PROCESSING | inference/failure | NEEDS_REVIEW/FAILED | worker | no silent confirmation |
| Memory/signal | CANDIDATE/PENDING | confirm/reject | CONFIRMED/REJECTED | EDITOR+ | protected from PATCH |
| Publish job | approved content | enqueue/execute | QUEUED/SCHEDULED → terminal | MANAGER+/worker | settings violations cannot publish |

## Requirement → implementation → test plan
| Req | Requirement | Planned path | Planned test | Failure/security case |
|---|---|---|---|---|
| FC-1 | Knowledge processing | knowledge services/tasks/views | processing tests | duplicates, tenant/brand injection, provider failure |
| FC-2 | Inspiration analysis | inspiration services/tasks/views | analysis tests | user authority, retries, archives |
| FC-3 | Automatic refresh | universal enrichment + jobs sweep | cadence/hash tests | SSRF, quota, inactive client |
| FC-4 | Publishing settings | publishing validation + worker | settings tests | retry/schedule bypass |
| FC-5 | Honest storage | storage callers | outage tests | no row/mock URL |
| FC-6 | Complete product loop | lifecycle integration test | two-client core loop | cross-tenant read/write/publish |

## Risk scan
- Cross-tenant/cross-brand FK: validate in request and service/job entry paths.
- Partial PATCH: validate effective final objects; protected lifecycle fields remain read-only.
- Duplicate/retry: content hashes and existing unique/reconciliation rules; stale task replay must be harmless.
- Storage: strict before persistence; no placeholder URL.
- External URL/SSRF: reuse own-site enrichment safe fetch; never request an unvetted redirect.
- Provider failure: fallback through AIRouter; exhaustion becomes FAILED.
- Revocation: archived sources/inspirations become ineligible and cannot be reprocessed.
- Lineage: every AI candidate retains source and provider trace.
- Billing: AI dispatch continues through the existing spend/quota gate.
- RED conditions: architecture seams are reused, not changed.

## Stop decision
- PROCEED.
- The founder approved the frozen closure scope; no RED boundary change is required.
