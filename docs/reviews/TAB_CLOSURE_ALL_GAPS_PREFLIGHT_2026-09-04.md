# Tab closure — remaining confirmed gaps (immutable preflight)

## Identity
- Branch/base: `codex/tab-by-tab-product-closure`, `c42c1c52`.
- Authorization: user requested “fix everything” after the tab-by-tab delivery ledger. Close the ledger's confirmed defects and recorded Brand Master/Social follow-ups in the existing application.
- Out of scope: new social/provider integrations, credentials or paid production actions, infrastructure replacement, automatic deployment, architectural rewrites, removal of working modules, unrelated `.claude/` files.
- Governing context: AGENTS.md; scoped tab-closure/Create Studio preflights; API contracts as implemented in current serializers/services and consumers; docs/CTO_REVIEW_LOG.md. Root PR_EXECUTION_TASKS.md and API_AND_DATA_CONTRACTS.md are absent. The old ARCHITECTURE.md contains superseded implementation descriptions; current ownership contracts remain authoritative.
- Latest review: TAB_BY_TAB_CHECKPOINT_SELF_REVIEW_2026-09-04.md and FIRST_PASS_LEDGER.md. Prior checks do not certify new changes.

## Existing architecture to reuse
| Concern | Existing implementation | Decision |
| --- | --- | --- |
| Tenant/RBAC | Workspace middleware, membership/role permissions, PlatformAdmin | Enforce existing authority at mutations and delayed execution; no bypass |
| Models | Brand sources/memories/signals, LearningEvent, content, publish jobs/items | Preserve provenance, ownership and historical rows |
| API | Scoped viewsets, opt-in pagination, established response consumers | Add truthful state/continuation without breaking legacy consumers |
| Jobs | TaskRun, enqueue/retry backend, generation and sync workers | Reuse authoritative lifecycle rather than client guesses |
| Storage | MarketingAsset upload and scoped asset IDs | Do not restore arbitrary asset URL registration |
| AI/provider | Context Gateway, AIRouter, capability routes, image retry | Preserve explicit creative direction and paid partial work |
| Frontend | Shared client/stores, current tab routes and panels | Independent retryable states, accessible status controls |
| Tests | Existing backend regression and focused modules, frontend build/type/lint | Add failure/attack coverage; combined regression gate |

## Dependency graph
User → authentication → selected workspace → existing role → brand → API/queued entry path → validation → persistence → current task/service → authoritative state → scoped API consumer → truthful UI/recovery → audit/provenance → focused and combined tests.

## Entry-path matrix
| Capability | POST | Multipart | PUT/PATCH | Actions | Job/internal | Other |
| --- | --- | --- | --- | --- | --- | --- |
| Generation/publishing | Role and source guards | Existing scoped assets | Remove generic tracking mutations | Retry image, queue/schedule | Revalidate dispatch, expose retry/partial result | Aliases retain same guards |
| Knowledge/inspiration/learning | Preserve owned source/manual workflows | Existing source upload | Protect provenance and lifecycle | Confirm/reject/reprocess | Trusted append-only evidence writers | Read paths remain scoped |
| Social | No generic connection creation | N/A | Admin configuration only | Verify/disconnect/reconnect | Queued policy recheck | One-use OAuth callback with current actor authority |
| Analytics/engagement | Existing imports/sync | Existing import contract | Preserve source ownership | Observe sync completion | Existing workers | Currency/measurement honesty |
| Admin/platform | Current permissions | N/A | Invalidate stale health | Audited availability control | Existing provider routing | Bounded pagination and independent errors |

## State machine
| Object | From/action/to | Authority / prohibited transition |
| --- | --- | --- |
| Generation | Queued → running/retry-pending → terminal full/partial/failure | Existing Editor authority; no duplicate paid retry while owned task can continue |
| Publish job/item | Queued → dispatch only if still eligible → success/failure/cancelled | Existing publish permission; disabled accounts/cancelled jobs must not dispatch |
| Evidence | Candidate → confirmed/rejected through owned actions | Archived/expired/superseded provenance cannot be revived silently |
| Provider health | Config changed → unchecked → explicitly checked result | Historical health must not describe changed credentials as healthy |
| UI lists/sync | Loading → loaded/error; queued sync → terminal → refreshed | Failures are not empty lists, zero measurements or success |

## Requirement → implementation → test plan
| Requirements | Planned paths | Evidence plan / attacks |
| --- | --- | --- |
| PUB-01–06 | gemini, jobs, context generation, publishing, publishing route | Viewer mutation/aliases; dispatch policy changes; partial media and retry; constant history queries |
| CON-01–03, ENG-01, SYNC-01, ANA-01 | review/growth/analytics UI, analytics summaries | Failed/malformed lists; sync terminal outcomes; mixed currency and unknown metrics |
| ADM-01–03, SET-01, PLAT-01–02 | ai serializers/UI, settings, platform lists/control | Disabled route honesty, health invalidation, failed activity, bounded filtered pagination and platform permissions |
| Brand follow-ups | knowledge/inspiration serializers/actions; learning API; Needs review | PATCH provenance, expired/archived confirmation, untrusted event creation, incomplete attention results |
| Social follow-ups | OAuth state/callbacks, account health/actions/audit | Revoked actor authority, replay, transient vs credential failure, empty callback results |
| Full gate | source lint configuration, regression, build/type, browser | Preserve semantic lint; no generated-output traversal; current changes require fresh evidence |

## Risk scan
- Cross-tenant/brand FKs: never infer selected workspace from the first membership; retain scoped lookups and immutable ownership.
- PATCH/lifecycle: distinguish user-editable values from machine evidence and lifecycle actions.
- Retry/billing: partial assets/copy and potentially running work must survive; no automatic new paid operation in UI tests.
- Storage/SSRF: unchanged safe storage/URL services; no arbitrary URL fallback.
- Provider failure: report partial/failed work truthfully; preserve fallback/router ownership.
- Revocation: check current actor authority before OAuth persistence; describe local disconnect vs remote revocation honestly.
- Lineage: no rewriting prior learning evidence; no fake analytics conversion or currency conversion.
- RED boundaries: no tenancy/Brain/router/publishing/infrastructure redesign. If a follow-up requires changed product semantics, record the precise unresolved choice instead of inventing it.

## Stop decision
PROCEED with bounded parallel implementations in existing owners. Do not claim release-ready with failed or unverified mandatory gates. Production provider/account actions and deployment are not part of this execution.
