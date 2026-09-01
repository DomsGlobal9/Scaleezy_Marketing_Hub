# Create From Inspiration — Immutable Execution Preflight

## Identity
- PR: additive Content → Create from inspiration vertical slice
- Commit/branch at preflight: `9faddcb1` / `codex/create-from-inspiration`
- Authorized scope: let an editor save one uploaded or public-link inspiration from Content, request an original similar poster with one instruction, preprocess the reference in the durable worker, apply the selected client's compiled Brand Brain through Context Gateway, route generation through AIRouter, and save a draft with provenance.
- Explicitly out of scope: PR0–PR7 ownership rewrites; a second router/context/learning/job/publishing stack; automatic signal confirmation; Brand Brain mutation; automatic approval or publishing; bypassing provider capabilities; fetching private or login-walled links; exact cloning of third-party work.
- Latest CTO instruction reviewed: user request on 2026-09-01. `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` are not present in this checkout; frozen architecture, closure contracts, CTO review log, Creative Command evidence, and current code/tests were reviewed instead.

## Existing architecture to reuse
| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | `WorkspaceResolvedViewSet`, `HasWorkspaceRole`, `X-Workspace-Id`, brand/workspace invariants | Inspiration writes remain editor-only and workspace-derived; generation re-resolves the inspiration at worker time. |
| Models | `BrandInspiration`, `InspirationSignal`, `GeminiGenerationRequest`, `ContentItem`, `MarketingAsset` | Reuse; no schema migration. |
| API | inspiration JSON/upload/analyze APIs and async generation/poll/results APIs | Compose the existing APIs in one UI action; add only bounded preprocessing fields to generation. |
| Jobs | durable Django task backend and `generate_content` | Preprocess explicitly named inspiration IDs inside the existing generation task, then continue the same task. |
| Storage | `SupabaseStorageService` | Reuse after server-side size/type validation; never place browser base64 in generation state. |
| AI/provider | inspiration analysis → `AIRouter`; Context Gateway → TEXT/IMAGE → layout composition | Reuse unchanged ownership. Reference analysis becomes provider-neutral creative observations; Brand Brain remains governing context. |
| Frontend | Publishing workflow, Creative Command, async polling, preview/editor/review | Add one focused upload-or-link step and reuse existing polling/preview. |
| Tests | inspiration, Creative Command, async generation, production closure, frontend type/build gates | Extend focused attack and lifecycle cases; run the full gate before ready. |

## Dependency graph
User → authenticated session → `X-Workspace-Id` → editor role → current workspace brand → Content upload/public-link form → file/URL validation → `BrandInspiration` persistence → async generation request containing IDs only → durable worker → execution-time workspace/brand/lifecycle revalidation → provider-neutral inspiration analysis → campaign-only Creative Command resolution → Context Gateway/compiled Brand Brain → AIRouter TEXT + IMAGE → durable MarketingAsset → ContentItem DRAFT → existing preview/editor → review → publishing gate → immutable creative direction + brain/provider trace → tests.

## Entry-path matrix
| Mutation / capability | POST JSON | Multipart | PUT | PATCH | Custom action | Job/internal | Other |
|---|---:|---:|---:|---:|---:|---:|---:|
| Save public-link inspiration | Yes | No | N/A | Existing only | N/A | N/A | HTTPS safe-fetch during analysis |
| Save uploaded inspiration | No | Yes | N/A | Existing only | `/inspirations/upload/` | N/A | Strict storage |
| Queue poster from saved inspiration | Yes | N/A | N/A | N/A | `/ai-generation/generate-async/` | durable worker | Existing polling/results |
| Analyze before generation | N/A | N/A | N/A | N/A | N/A | Explicit bounded IDs only | Re-resolve tenant, brand and lifecycle |

## State machine
| Object | From | Action | To | Who may perform | Invalid transitions |
|---|---|---|---|---|---|
| BrandInspiration | absent | valid upload/link | ACTIVE + NOT_ANALYSED | Editor+ | invalid brand/workspace, unsupported/oversize file, unsafe URL |
| BrandInspiration | ACTIVE + NOT_ANALYSED/FAILED | worker preprocessing | PROCESSING → NEEDS_REVIEW/READY | durable task | archived, unavailable provider, unreadable input |
| GeminiGenerationRequest | absent | queue succeeds | PENDING | Editor+ and approved client | quota/approval failure; enqueue failure must not remain PENDING |
| GeminiGenerationRequest | PENDING | worker validates/analyzes/generates | GENERATING → COMPLETED or FAILED | durable task | archived/cross-tenant inspiration; inactive client; provider/storage failure |
| ContentItem | absent | successful persistence | DRAFT | worker | no implicit review, approval, schedule or publish |

## Requirement → implementation → test plan
| Req ID | Requirement | Planned code path | Planned test | Security/failure case |
|---|---|---|---|---|
| CFI-001 | One-step upload or public link from Content | Publishing inspiration step + existing inspiration helpers | frontend state/type/build checks | exactly one source; client switch clears state |
| CFI-002 | User can simply say “Create a similar poster” | editable default instruction passed to async brief | async payload/task test | instruction bounded; treated as data |
| CFI-003 | Use current client's Brand Brain | unchanged Context Gateway generation path | brain version/trace assertion | explicit current brand/workspace only |
| CFI-004 | Original work, not copying | hardened Creative Command policy + campaign-only reference observations | instruction reaches AIRouter | no logos, protected art, exact copy/layout or unverified claims |
| CFI-005 | Durable provenance without base64 | BrandInspiration + ID-only generation state + ContentItem creative direction | prompt_data/trace assertions | wrong-tenant/archived ID rejected |
| CFI-006 | Honest broad inputs | validated image/video/document types and public HTTPS links; explicit unsupported errors | MIME/size/URL tests | no arbitrary binary, private URL, silent fallback or fake success |
| CFI-007 | Draft/review safety | unchanged persistence and publishing gates | status/publish job assertions | never auto-publish |
| CFI-008 | Queue truth | catch enqueue failure and mark request FAILED; preserve saved inspiration | failure test | no false PENDING/QUEUED work |

## Risk scan
- Cross-tenant FK: worker filters inspiration by request workspace and current brand; generic unavailable error.
- Cross-brand FK: selection is validated against the exact default/current brand used by generation.
- Partial PATCH: no new PATCH semantics; provenance identifiers remain immutable.
- Direct lifecycle mutation: existing named archive/analyze paths only.
- Duplicate/retry: existing completed-generation idempotency remains; analysis signal writer is idempotent; execution re-resolves references.
- Storage: validate size and supported MIME before the strict upload; storage failure creates no inspiration row.
- External URL / SSRF: only HTTPS; existing `safe_fetch` validates every redirect hop and streams within caps. Private/login-walled content fails honestly.
- Provider failure: request becomes FAILED and creates no ContentItem; no placeholder output.
- Revocation/deletion: archived reference after queue fails before provider generation.
- Data lineage: BrandInspiration ID, creative direction snapshot, brain version, providers and generation trace persist.
- Billing/quota: existing quota and approval gates run before queue and AIRouter rechecks spend approval at execution.
- RED autonomy conditions: no ownership, credential, billing, publishing or Brand Brain contract change. The new flow composes frozen PR2/PR5/PR6 contracts; PROCEED.

## Stop decision
- PROCEED
- Reason: this is an additive user journey implemented through existing frozen owners, with no migration or competing architecture. Unsupported/private inputs fail explicitly rather than weakening security or claiming fake coverage.
