# Preloaded Brand Brain validity — immutable execution preflight

## Identity
- Branch/checkpoint: `codex/tab-by-tab-product-closure`, `c42c1c52`, preserving the existing uncommitted closure work.
- Authorization: the user approved the specifically described final change with “if its needed lets do it”. Exclude expired/future-dated facts from Platform's preloaded Brand Brain compilation, matching generation's existing rule.
- Reviewed: AGENTS.md; current tab-closure and Context snapshot contracts/reviews; CTO_REVIEW_LOG.md; the compiler, Platform ClientProjection loader and memory fields/tests. Root PR_EXECUTION_TASKS.md and API_AND_DATA_CONTRACTS.md remain absent.
- Out of scope: other working-tree edits, new UI, credentials, provider calls, schema migrations, persisted Brain shape, publishing, deployment and architecture ownership changes.

## Existing architecture to reuse
| Concern | Existing implementation / decision |
| --- | --- |
| Tenant/RBAC/API | PlatformAdmin gate and scoped ClientProjection preload remain unchanged. |
| Models | BrandMemory valid_from/valid_until; no new fields or lifecycle mutations. |
| Intelligence | Existing compile_brand_brain_from_records owns precedence, output and lineage. Apply dates before every downstream claim/content/source-ID calculation. |
| Frontend | Existing client readiness response; no shape or UI changes. |
| Jobs/storage/providers | No changes or external calls. |
| Tests | New preloaded-entry and Platform integration tests plus existing full backend regression. |

## Dependency / entry paths
Platform client list → live PlatformAdmin → workspace/brand-scoped source preload → pure compiled Brain → readiness projection → existing response/UI. Ordinary compile, generation and explicit rebuild also call this shared pure function and retain the same date policy.

| Entry | Treatment |
| --- | --- |
| Platform preloaded/missing snapshot | Apply inclusive start/exclusive end to already loaded memories, without additional queries. |
| Ordinary compile and jobs | Same validity policy as existing database filter; null bounds remain eligible. |
| JSON/multipart/PUT/PATCH/actions | No new mutations; existing ownership, validation and lifecycle remain unchanged. |

## State and test map
Fact records do not transition or get deleted. Their contribution is eligible only when `(valid_from is null or valid_from <= now) and (valid_until is null or valid_until > now)`.

| Requirement | Proof |
| --- | --- |
| Match date semantics on all compiler entry paths | Null/current, exact-start, exact-end, future and expired fixtures; ordinary/preloaded equality at a fixed clock. |
| Preserve provenance and authority | Excluded facts absent from narrative, claims/conflicts and source IDs; source rows unchanged. |
| Integrate Platform path | Missing-snapshot ClientProjection compiles only eligible facts; existing tenant/admin tests remain passing. |
| Keep lean/read-only | No added database query or write when records are preloaded; full regression. |

## Risk / stop decision
Time-bounded facts no longer inflate missing-snapshot readiness or influence its compiled claims. Null dates and valid facts remain unchanged. No tenant/FK, storage/SSRF, billing, provider, retry, schema or precedence-rank changes. The previously blocked date-rule change now has explicit user approval. PROCEED only within this scope; report other semantic changes rather than expanding it.
