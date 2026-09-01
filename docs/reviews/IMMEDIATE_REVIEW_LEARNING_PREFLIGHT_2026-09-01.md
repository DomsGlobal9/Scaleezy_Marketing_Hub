# Immediate Review Learning — Immutable Execution Preflight

## Identity
- PR: PR3 policy amendment — first-event review learning
- Commit/branch at preflight: `a9ce64bc` / `feat/performance-autopilot-closure`
- Authorized scope: make the first tagged corrective human review produce an active, traceable SOFT learned rule for the same brand and rebuild its Brand Brain immediately.
- Explicitly out of scope: tenant/RBAC changes, hard-rule inference, provider/router changes, universal-learning rank or participation changes, publishing changes, untagged free-text clustering, and autonomous publication.
- Latest founder instruction reviewed: learning must start immediately; the machine must not wait for the same problem to be raised twice.
- Repository note: `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` are absent; the existing PR3 code, architecture, CTO log, and this founder-approved amendment are the governing contract.

## Existing architecture to reuse
| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | Content review actions and workspace-scoped feedback | No permission or tenancy change |
| Models | `LearningEvent`, `BrandRule`, immutable evidence ids | No schema change |
| API | Existing approve/reject/request-edits actions | No endpoint change |
| Jobs | Synchronous best-effort feedback learning | No new job stack |
| Storage | N/A | N/A |
| AI/provider | Context Gateway consumes compiled Brand Brain | No provider-specific path |
| Frontend | Review tags and training report | Replace stale two-occurrence copy only |
| Tests | Feedback, learning, Brand Brain and context suites | Add first-event end-to-end proof and preserve attack paths |

## Dependency graph
Reviewer → authenticated workspace action → selected brand content → append-only Feedback → idempotent LearningEvent → one-evidence SOFT BrandRule → Brand Brain safe rebuild → Context Gateway → next generation prompt → Review learning report → lineage/security tests.

## Entry-path matrix
| Mutation / capability | POST JSON | Multipart | PUT | PATCH | Custom action | Job/internal | Other |
|---|---:|---:|---:|---:|---:|---:|---:|
| Corrective review learning | existing feedback create | N/A | N/A | N/A | reject/request-edits | `capture()`/`TrainingEngine` | approvals remain non-corrective |

## State machine
| Object | From | Action | To | Who may perform | Invalid transitions |
|---|---|---|---|---|---|
| Feedback | absent | first tagged corrective verdict | append-only evidence | authorized reviewer | edit/delete evidence |
| BrandRule | absent | first tagged corrective evidence | active LEARNED/SOFT | training service | inferred HARD rule |
| BrandRule | active LEARNED/SOFT | repeated matching evidence | same row, stronger lineage | training service | duplicate row or reactivating a human-disabled rule |

## Requirement → implementation → test plan
| Req ID | Requirement | Planned code path | Planned test | Security/failure case |
|---|---|---|---|---|
| IRL-1 | First tagged correction learns immediately | `feedback.training` occurrence gate | first rejection creates one rule | approval creates none |
| IRL-2 | Next generation receives it immediately | safe Brand Brain rebuild + Context Gateway | one rejection changes next context/prompt | rebuild failure does not falsify review success |
| IRL-3 | Evidence stays trustworthy | `upsert_learned_rule` distinct ids | one real event is cited once | replay cannot duplicate evidence |
| IRL-4 | Scope stays isolated | existing workspace/brand checks | foreign workspace/brand each learn only themselves | no cross-tenant reinforcement |
| IRL-5 | Repeats strengthen, not duplicate | rule key + evidence union | second/third review update same rule | deactivated rule remains off |

## Risk scan
- Cross-tenant FK: unchanged checks; focused workspace/brand tests required.
- Cross-brand FK: unchanged checks; evidence must match rule brand.
- Partial PATCH: N/A; feedback is append-only.
- Direct lifecycle mutation: no new generic lifecycle endpoint.
- Duplicate/retry: one Feedback id maps to one deduped LearningEvent; rule evidence is a set.
- Storage: N/A.
- External URL / SSRF: N/A.
- Provider failure: embedding fallback remains best-effort and provider-neutral.
- Revocation/deletion: a human-disabled learned rule remains disabled.
- Data lineage: every learned rule cites the first concrete LearningEvent.
- Billing/quota: N/A.
- RED autonomy conditions: founder explicitly authorizes the PR3 policy change; Brand Brain ownership and hardness authority are preserved.

## Stop decision
- PROCEED.
- Reason: the founder explicitly replaces the two-occurrence review threshold. The amendment remains additive, brand-scoped, SOFT, reversible, and fully cited.
