# PR07_PREFLIGHT_2026-08-23 — Immutable Execution Preflight

## Identity
- PR: PR7 — Universal Learning
- Commit/branch at preflight: `6a50325` / `codex/pr7-universal-learning`
- Authorized scope: deterministic cross-client pattern compilation, rank-82 generation injection, Super Admin pattern controls and console.
- Explicitly out of scope: PR8–PR10, consent UI, client opt-out, performance benchmarking, tenant/RBAC changes, AIRouter changes.
- Latest instruction reviewed: `CODEX_UNIVERSAL_LEARNING.md` from `1CODEX_UNIVERSAL_LEARNING.zip`; founder decision is all CLIENT data, no consent filter, no cohort floor.
- Missing repository contracts: `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` are not present on `main`; the supplied PR7 contract is the execution authority.

## Existing architecture to reuse
| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | `PlatformView` + `IsPlatformAdmin`; normal workspace permissions unchanged | Platform-only API; no tenant bypass |
| Models | `LearningEvent`, `BrandPreference`, `BrandRule`, `UniversalStandard` | Patterns are derived rows in `apps.universal` |
| API | `APIResponse`, platform URL slices | New `urls_patterns.py` + `views_patterns.py` |
| Jobs | Django `@task` + database worker | Compile task; management command for explicit runs |
| AI/provider | Context Gateway owns provider-neutral context | Add pattern context only; AIRouter untouched |
| Frontend | `/platform/standards` console pattern | Add `/platform/patterns` |
| Tests | Django `TestCase` and platform API tests | Focused aggregation, gateway and console attack paths |

## Dependency graph
Client evidence → CLIENT workspace filter → deterministic aggregation → `LearnedPattern` DRAFT rows → Platform Admin publish/retire → rank-82 structural filter → Context Gateway cache key + trace → provider-neutral brief → generation; failures stay draft/unpublished and all platform actions are audited.

## Entry-path matrix
| Mutation / capability | POST JSON | PUT/PATCH | Custom action | Job/internal | Management command |
|---|---:|---:|---:|---:|---:|
| Compile patterns | platform `/compile/` enqueues | N/A | yes | `@task` | yes, `--dry-run` |
| Publish/retire | yes | N/A | yes | service | N/A |
| Read contributors | N/A | N/A | GET, platform-only | N/A | N/A |

## State machine
| Object | From | Action | To | Who may perform | Invalid transitions |
|---|---|---|---|---|---|
| LearnedPattern | DRAFT | publish | PUBLISHED | Platform Admin | none through client APIs |
| LearnedPattern | PUBLISHED/DRAFT | retire | RETIRED | Platform Admin | none through client APIs |
| LearnedPattern | derived set | compile | rebuilt DRAFT set; identical published rows retained | worker/command | request never compiles inline |

## Requirement → implementation → test plan
| Req | Requirement | Planned code path | Planned test | Failure/security case |
|---|---|---|---|---|
| P7-1 | All CLIENT data; INTERNAL excluded; one client allowed | `aggregation.py` | deterministic/internal/single-client tests | consent flag ignored |
| P7-2 | Honest counts and rebuildability | aggregation + fingerprints | delete/recompile equality | real distinct queries |
| P7-3 | Rank 82, attributed, never outranks brand | universal services + Context Gateway | rank/guard/brief tests | distinctive client literal excluded |
| P7-4 | Immediate cache invalidation | pattern set fingerprint in key/trace | retire test | same Brand Brain version |
| P7-5 | Platform-only controls and traceability | platform pattern views | permission/audit/contributor tests | staff without PlatformAdmin gets 403 |
| P7-6 | Visible console | route + API client + nav | `tsc --noEmit` | server remains authority |

## Risk scan
- Cross-tenant FK: aggregation is background platform work; request permissions are unchanged.
- Direct lifecycle mutation: no generic pattern serializer/viewset; only audited actions.
- Duplicate/retry: compile is deterministic and transactionally reconciled.
- Data lineage: contributor workspace UUIDs stored only on platform-derived rows and never in client context.
- Provider failure: N/A; no provider call in compilation.
- RED conditions: Brand Brain and AIRouter ownership remain unchanged; rank-82 injection uses the existing Context Gateway seam.

## Stop decision
- PROCEED with implementation and verification.
- Production merge/deploy remains blocked until the founder approves replacement wording for the contradictory privacy-policy sentence.
