# Brand contact fields — immutable integration preflight

## Identity

- Branch/base: `codex/tab-by-tab-product-closure`, `5a3a1ab3`.
- Approved scope: the user's “yes” to adding Legal business name and Contact person under Brand Master / Client basics, with working save and reload.
- Source attribution: Claude co-authored `e2daa9fb` on `claude/onboarding-form-automation-21c90b`. It already implements both fields but is not in the current branch. Reuse its field names, limits and original migration identity; do not invent competing storage or claim original authorship.
- Out of scope: merging Claude's whole signup branch, changing signup requirements/approval flows, changing Brand Brain or provider inputs, billing, credentials, production data, push/merge/deploy, unrelated local files.
- Reviewed: root and frontend AGENTS.md, current tab-closure contract, CTO_REVIEW_LOG.md, approved source commit, Brand model/serializer/view and business-profile tests, shared editor/save flow. Root PR_EXECUTION_TASKS.md and API_AND_DATA_CONTRACTS.md remain absent.

## Existing architecture and dependency graph

Member → selected workspace → existing VIEWER read / EDITOR write permissions → Brand Master ClientBasicsSection → shared useBrandSettings queue → Brand PATCH serializer → Brand columns → canonical response → same editor / reload. Add Client uses the same profile component and contract without a second persistence path.

| Concern | Reuse decision |
| --- | --- |
| Models/API | `legal_name`: optional string, max 255; `contact_person`: optional string, max 150. Existing BrandSerializer exposes model fields and validation. No alias or new endpoint. |
| Migration | Preserve Claude's `0006_brand_intake_contact` unchanged; join its branch with existing `0006_brand_guardrails` using an empty merge migration. Existing values receive empty strings; no deletion, rename or overwrite. |
| UI | Reuse `legalName` / `contactPerson` mapping and the existing save queue, error recovery and workspace targeting. Empty defaults support old response payloads. Explicit accessible names and matching input lengths. |
| Intelligence / storage / jobs | No new provider calls, files, jobs, learning authority or compiler fields. These administrative contact values are not automatically prompt content or poster text. |

## Entry-path and state matrix

JSON/multipart POST, PUT and PATCH use existing Brand validation, scoping and roles. GET/list/current return the optional fields through the existing serializer. Internal creates may omit them. Existing Django admin fieldsets do not gain new mutation controls. Existing pending/saving/saved/failed editor states remain unchanged; retries keep the newest typed values. No lifecycle transition changes.

## Requirement → test map

| Requirement | Proof plan |
| --- | --- |
| Both values persist and return after reload | Brand API POST/PATCH/PUT/multipart and GET/current round trips; UI save/reload where browser runtime is available. |
| Optional, bounded, independent values | Omitted/empty, Unicode, max length, over-limit rejection, partial edits do not erase the other field or rename the brand. |
| Same tenant / role protections | Anonymous, VIEWER and foreign workspace reads/writes rejected as before. |
| Preserve intelligence boundary | Compiled identity/version and learning events do not gain administrative contact values. |
| Safe schema integration | Migration graph has one leaf, migration check, isolated database application and full backend regression. |
| Frontend wiring / compatibility | DTO/default/read/write mappings, typecheck, lint, build and targeted UI checks. |

## Risk and stop decision

AMBER additive schema explicitly approved. No new foreign keys, URL fetching, billing or lifecycle semantics. Existing privacy/access policies apply to these user-entered administrative values; do not copy contacts into prompts or evidence. Preserve existing local files and Claude's attribution. PROCEED within this two-field integration only; report any broader conflict instead of silently merging unrelated work.
