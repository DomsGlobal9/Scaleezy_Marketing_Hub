# Asset URL Boundary — Immutable Execution Preflight

## Identity

- Workstream: contained Social Media Accounts audit security closure.
- Branch/base: `codex/tab-by-tab-product-closure` at `721412f46d18a4d652d52f7c557297ee65a904cf`.
- Authorized scope: remove X's unused media URL download; reject generic public asset creation/update; preserve authenticated binary upload, reads and internal generation/layout persistence; add focused attack tests.
- Out of scope: LinkedIn/YouTube fetching, publishing architecture, URL-import features, storage providers, tenant/RBAC redesign, migrations, commits or deployment.
- Reviewed: root AGENTS, frozen autonomous-social closure, tab-by-tab preflight and CTO review log. Root `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` are absent; use the existing implementation and frozen closure contracts.

## Existing architecture to reuse

| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | IsAuthenticated, IsWorkspaceMember, WorkspaceScopedMixin, authorize_workspace | Preserve |
| Model/API | MarketingAsset, upload action, output serializer | Disable only generic create/PUT/PATCH; preserve reads and scoped deletion |
| Storage | SupabaseStorageService.upload_and_describe | Derive URL/path from successful binary upload |
| Internal writers | context.services.generation.create_generated_asset, layouts.services.persist_composed | Preserve ORM writes |
| Provider | XAdapter URL-text fallback | Preserve fallback, remove unused fetch and mock-byte branch |
| Frontend | Publishing ensureDraftAsset fallback | Report generic-POST dependency to parent/frontend owner |
| Tests | marketing API, X adapter, common tenant isolation, layout persistence | Focused regression and attack matrix |

## Dependency graph

Authenticated user → selected workspace/member → asset API → binary upload/storage result → MarketingAsset → publishing job → X URL-text fallback → provider response. Trusted generation/layout services continue to persist assets directly.

## Entry-path matrix

| Capability | POST JSON | Multipart | PUT | PATCH | Custom action | Internal |
|---|---|---|---|---|---|---|
| Public asset persistence | Reject | Reject generic route | Reject | Reject | Existing authenticated upload only | Preserve trusted writers |
| Supplied URL/metadata | Never persist | Ignore extra storage metadata | Never persist | Never persist | Derive from uploaded file/storage result | Existing contracts unchanged |
| X media URL | N/A | N/A | N/A | N/A | Never fetch supplied URL | Preserve URL-text fallback |

## State machine

| Object | From | Action | To | Invalid transition |
|---|---|---|---|---|
| Asset | Absent | Successful authorized upload | Persisted storage result | Raw client URL → persisted asset |
| Asset | Existing | Generic update | Unchanged/rejected | Arbitrary client storage URL replacement |
| X media | Stored URL | Prepare existing fallback | URL marker without network read | Supplied URL → server download |

## Requirement → implementation → test plan

| Requirement | Code | Planned evidence |
|---|---|---|
| Reject arbitrary/private URLs | MarketingAssetViewSet route mixins | JSON/multipart POST and PUT/PATCH rejection matrix |
| Preserve legitimate upload | Existing upload action | Successful file upload ignores forged URL/path/size/type metadata; anonymous/cross-workspace rejection; storage failure creates no asset |
| Preserve reads/internal persistence | Existing scoped reads and internal writers | List/retrieve generated asset plus existing layout-persistence regression |
| X never fetches media URL | XAdapter.upload_media | Private/public URL cases assert requests.get unused and existing tweet POST payload preserved |

## Risk scan

- Cross-tenant/cross-brand: no relations changed; exercise upload authorization and scoped reads.
- Partial PATCH/direct metadata mutation: explicitly reject generic route writes.
- Retries/provider failure: existing semantics unchanged; no new job behavior.
- Storage/SSRF: close public arbitrary-URL persistence and remove X's unused request; do not claim broader fetch-path redesign.
- Deletion/lineage/billing: preserve existing behavior; no schema change.
- RED: no architecture replacement. Existing frontend fallback was reported for coordinated repair.

## Stop decision

PROCEED with the explicitly authorized contained boundary closure and focused verification. Full release gates remain the parent workstream's responsibility.
