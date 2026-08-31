# Brand Master Tab Visibility — Immutable Execution Preflight

## Identity
- PR: Brand Master inactive-panel visibility fix
- Commit/branch at preflight: `0cbb63bd` / `codex/fix-brand-master-tabs`
- Authorized scope: Make every Brand Master tab display only its selected panel while preserving mounted Brand Basics and Products & Audience drafts.
- Explicitly out of scope: Brand editor save semantics, tab URL contract, API/backend changes, visual redesign, or other navigation.
- Latest CTO instruction reviewed: `docs/CTO_REVIEW_LOG.md`; no current-PR review exists.
- Repository note: the `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` filenames referenced by `AGENTS.md` are not present; `docs/ARCHITECTURE.md` and the frozen Final Core Closure contract were used.

## Existing architecture to reuse
| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Frontend tab state | Radix `Tabs` controlled by the validated `?tab=` search parameter | Preserve |
| Draft persistence | Shared `useBrandSettings` editor plus `forceMount` for the two editable panels | Preserve |
| Visibility | Radix `data-state=active|inactive` | Use the inactive state to hide mounted panels |
| Tests | No frontend component-test runner is configured | Prove with typecheck, production build, and DOM state verification |

## Dependency graph
User → authenticated Brand Master route → validated tab query → controlled Radix Tabs → mounted editor panels → CSS visibility → selected panel.

## Entry-path matrix
| Capability | Click | Direct URL | Browser history | Reload |
|---|---:|---:|---:|---:|
| Select Brand Master tab | Yes | Yes | Yes | Yes |

## State machine
| Object | From | Action | To | Invalid state |
|---|---|---|---|---|
| Tab panel | Active | Select another tab | Mounted + hidden inactive | Mounted + visible inactive |
| Tab panel | Inactive | Select its tab | Mounted + visible active | Active + hidden |

## Requirement → implementation → verification
| Req ID | Requirement | Planned code path | Planned verification | Failure case |
|---|---|---|---|---|
| BM-TAB-001 | Inactive mounted editor panels are invisible | `_hub.brand-master.tsx` Basics/Products `TabsContent` classes | Typecheck, production build, DOM state matrix | An inactive panel computes to non-`none` display |
| BM-TAB-002 | Local editor drafts remain mounted | Keep `forceMount` on both panels | Source assertion and tab switching | Removing `forceMount` discards local catalogue drafts |
| BM-TAB-003 | All other tab behavior remains unchanged | No shared Tabs or router changes | Diff review and tab matrix | URL/selected state changes |

## Risk scan
- Tenant/RBAC, models, API, jobs, storage, AI, billing, lineage: N/A — presentation-only CSS class change.
- Draft loss: controlled by retaining `forceMount`.
- RED autonomy conditions: none.

## Stop decision
- PROCEED
- Reason: isolated reversible frontend correction with no product or architecture semantic change.
