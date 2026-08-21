# PR02_PREFLIGHT.md — Immutable Execution Preflight

## Identity
- PR: PR2 — Inspiration Intelligence Foundation
- Commit/branch at preflight: `marketinghub/merge` @ `50c1f2b` ("fix(pr1): final CTO blockers resolved, add AGENTS.md, disable process stub")
- Authorized scope: `BrandInspiration` → original source/provenance → `InspirationSignal` → explicit user annotation → AI/user origin distinction → liked/disliked/neutral semantics → tenant/brand isolation → APIs → tests.
- Explicitly out of scope: multimodal AI analysis pipeline, Brand Brain compiler, Context Gateway/retrieval, generation integration, universal learning, performance learning, onboarding/calibration UI, any frontend work.
- Latest CTO instruction reviewed: `docs/CTO_REVIEW_LOG.md` (PR0-001..004, PR1-001..011, GLOBAL-001..010) and `docs/PR2_EXECUTION_OVERRIDE.md`.

## Existing architecture to reuse
| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | `apps/common/permissions.py` (`IsWorkspaceMember`, `HasWorkspaceRole`, `get_request_workspace`, `resolve_workspace_id`), `apps/common/mixins.py` (`WorkspaceScopedMixin`) | Reuse unchanged. No new permission classes. |
| Models | `workspaces.MarketingWorkspace`, `brands.Brand`, `knowledge.BrandSource` | Reuse as FK targets. No changes to existing models. |
| API | DRF `ModelViewSet` + `DefaultRouter`, `apps/common/responses.APIResponse` envelope, mounted under `/api/marketing/` | Reuse; new app mounted at `/api/marketing/` like `brands`/`content`. |
| Jobs | `django.tasks` `@task` (used by `apps/knowledge/tasks.py`, `apps/jobs`) | Not used in PR2. Analysis is deferred to PR6 and returns 501. |
| Storage | `apps.marketing.services.storage.SupabaseStorageService.upload_and_describe` | Reuse for the multipart reference-upload path, exactly as `knowledge` upload does. |
| AI/provider | `apps/ai` router | Not called in PR2. Only the `origin=AI` provenance fields exist, written through an internal service contract. |
| Frontend | `Marketing_Frontend` central API client | Untouched — PR2 is backend only (PR7 owns UI). |
| Tests | Django `TestCase` + DRF `APIClient`, pattern in `apps/knowledge/tests.py` | Reuse the two-workspace/viewer fixture pattern. |

## Dependency graph
User → JWT auth → `X-Workspace-Id` resolved and membership-checked (`resolve_workspace_id` + `get_membership`) → role gate (`HasWorkspaceRole`: EDITOR to write, VIEWER to read) → Brand (must belong to the resolved workspace) → Entry path (JSON POST / multipart upload / PUT / PATCH / custom action / internal service) → Serializer validation (workspace equality, same-workspace **and** same-brand source, brand immutability, archived-source rejection) → Persistence (`BrandInspiration`, `InspirationSignal`) → Job/Service (none in PR2; `analyze` returns `501 NOT_IMPLEMENTED`, deferred to PR6) → State (`analysis_status` never advertises READY; `lifecycle_status` ACTIVE/ARCHIVED) → Consumer (retrieval eligibility helpers, consumed by PR5 Context Gateway) → UI (PR7) → Failure (storage 502, validation 400, RBAC 403, out-of-tenant 404) → Audit/Lineage (`source` FK, `created_by`, `confirmed_by`, `origin`, `conflicts_with`) → Tests (`apps/inspirations/tests.py`).

## Entry-path matrix
| Mutation / capability | POST JSON | Multipart | PUT | PATCH | Custom action | Job/internal | Other |
|---|---:|---:|---:|---:|---:|---:|---:|
| Create inspiration | yes | yes (`/inspirations/upload/`) | n/a | n/a | n/a | no | — |
| Update inspiration (title/annotation/usage scope) | n/a | n/a | yes | yes | n/a | no | — |
| Move inspiration to another brand | denied | denied | denied | denied | none exists | none | — |
| Archive inspiration | n/a | n/a | denied (read-only field) | denied (read-only field) | `/inspirations/{id}/archive/` | no | DELETE disabled (405) |
| Analyze inspiration | n/a | n/a | n/a | n/a | `/inspirations/{id}/analyze/` → 501 | deferred to PR6 | — |
| Create signal | yes | n/a | n/a | n/a | n/a | `record_ai_signal()` service | — |
| Update signal | n/a | n/a | yes | yes | n/a | `record_ai_signal()` | — |
| Change signal origin (AI→USER) | denied | n/a | denied | denied | none exists | none | — |
| Confirm/reject AI signal | n/a | n/a | denied (read-only field) | denied (read-only field) | `/signals/{id}/confirm/`, `/signals/{id}/reject/` | no | DELETE disabled (405) |

## State machine
| Object | From | Action | To | Who may perform | Invalid transitions |
|---|---|---|---|---|---|
| BrandInspiration.lifecycle_status | ACTIVE | `POST /archive/` | ARCHIVED | EDITOR+ in the owning workspace | PATCH/PUT of `lifecycle_status` (read-only); ARCHIVED → ACTIVE (no un-archive workflow in PR2) |
| BrandInspiration.analysis_status | NOT_ANALYSED | `POST /analyze/` | NOT_ANALYSED (501, unchanged) | EDITOR+ | any client write (read-only); anything → READY in PR2, because no analysis exists |
| BrandInspiration.brand | set at create | — | immutable | nobody | any reassignment (PR1-009) |
| InspirationSignal.origin | USER or AI at create | — | immutable | nobody | AI → USER |
| InspirationSignal.user_confirmation | PENDING (AI) / CONFIRMED (USER) | `POST /confirm/` | CONFIRMED | EDITOR+ | PATCH/PUT of `user_confirmation` (read-only) |
| InspirationSignal.user_confirmation | PENDING/CONFIRMED | `POST /reject/` | REJECTED | EDITOR+ | — |
| InspirationSignal (AI) colliding with a USER signal | — | `record_ai_signal()` | new row flagged `conflicts_with` | internal service | overwriting the USER row |

## Requirement → implementation → test plan
| Req ID | Requirement | Planned code path | Planned test | Security/failure case |
|---|---|---|---|---|
| R1 | Inspiration belongs to authenticated workspace and brand | `BrandInspirationSerializer.validate` + `perform_create(workspace=…)` | `test_cross_tenant_brand_injection_blocked` | Tenant A → Tenant B brand |
| R2 | Referenced source is same workspace AND same brand | `BrandInspirationSerializer.validate` (source checks) | `test_cross_tenant_source_injection_blocked`, `test_cross_brand_source_injection_blocked` | Same-workspace cross-brand source |
| R3 | Brand immutable after creation | serializer brand-change guard | `test_patch_cannot_move_inspiration_to_another_brand`, `test_put_cannot_move_inspiration_to_another_brand` | PATCH/PUT reassignment |
| R4 | Signal transitively tied to its inspiration workspace/brand | no denormalised FK; `workspace_field = 'inspiration__workspace'` + workspace-scoped inspiration queryset | `test_signal_cannot_attach_to_other_tenant_inspiration`, `test_signal_inspiration_is_immutable` | Signal on a foreign inspiration |
| R5 | AI vs user origin never indistinguishable | `origin` read-only and server-assigned; `user_confirmation` is a separate axis | `test_origin_is_server_assigned_on_create`, `test_patch_cannot_convert_ai_signal_to_user_origin` | Direct mutation |
| R6 | AI inference cannot silently overwrite explicit user preference | `services.record_ai_signal()` never updates USER rows; records `conflicts_with` | `test_ai_signal_does_not_overwrite_user_signal` | Conflicting AI signal |
| R7 | liked/disliked/neutral explicit, not inferred from weight | required `sentiment` field, independent of `weight` | `test_sentiment_is_required`, `test_weight_does_not_imply_sentiment` | Missing sentiment |
| R8 | Revoked/archived reference is ineligible for retrieval | `eligible_for_retrieval()` querysets + `retrieval_eligibility` read-only serializer field | `test_archived_inspiration_is_ineligible`, `test_archived_source_makes_inspiration_ineligible`, `test_rejected_signal_is_ineligible` | Honest eligibility |
| R9 | Original and derived signals separately addressable | separate models, routers, URLs | `test_inspiration_and_signals_are_separately_addressable` | — |
| R10 | No cross-tenant raw sharing | `WorkspaceScopedMixin` on both viewsets | `test_inspiration_detail_is_404_cross_tenant`, `test_signal_detail_is_404_cross_tenant` | ID guessing |
| R11 | Media-neutral reference types/metadata | `inspiration_type` choices + `external_platform` + `metadata` JSON | `test_supported_inspiration_types` | No provider hard-coding |
| R12 | "Use only typography" vs "use the entire reference" | `usage_scope` + `focus_areas` | `test_partial_usage_scope_requires_focus_areas`, `test_full_usage_scope_rejects_focus_areas` | Ambiguous intent |
| R13 | No fake success for analysis | `analyze` action → `501` | `test_analyze_is_not_implemented`, `test_analyze_archived_inspiration_rejected` | GLOBAL-001 |
| R14 | RBAC: viewer is read-only | `required_role=EDITOR`, `required_read_role=VIEWER` | `test_viewer_cannot_create_inspiration`, `test_viewer_cannot_create_signal`, `test_viewer_cannot_archive_inspiration`, `test_viewer_can_read_inspiration` | Viewer mutation |
| R15 | Multipart path has identical validation (PR1-007) | `upload` action reuses the workspace-scoped brand queryset and the same source validation | `test_upload_cross_tenant_brand_injection`, `test_upload_cross_brand_source_injection` | GLOBAL-010 |
| R16 | Provenance is not destroyed | DELETE disabled on both viewsets (405) | `test_delete_inspiration_disabled`, `test_delete_signal_disabled` | Hard delete |

## Risk scan
- Cross-tenant FK: `brand`, `source`, `inspiration`, `conflicts_with` — all validated server-side against the resolved workspace.
- Cross-brand FK: `source.brand_id` must equal `inspiration.brand_id`; signals inherit brand transitively, so there is no independent brand FK that can drift.
- Partial PATCH: validation reads `data.get(x)` falling back to the instance value, so the effective final object is checked (PR1-008).
- Direct lifecycle mutation: `lifecycle_status`, `analysis_status`, `origin`, `user_confirmation`, `workspace`, `created_by`, `confirmed_by`, `conflicts_with` are serializer read-only; transitions run through named actions.
- Duplicate/retry: no jobs in PR2. `record_ai_signal()` is idempotent on `(inspiration, category, attribute, origin=AI)` so a future retried PR6 job cannot duplicate permanent signals.
- Storage: reuses `SupabaseStorageService` workspace-prefixed upload; failure surfaces `502` and no row is created.
- External URL / SSRF: PR2 only stores the URL string; nothing fetches it. Fetching belongs to PR6 and is recorded as a deferred risk.
- Provider failure: N/A — no provider call exists in PR2.
- Revocation/deletion: hard delete disabled; archive is the only removal, and archived rows are excluded from `eligible_for_retrieval()`.
- Data lineage: `source`, `created_by`, `origin`, `confirmed_by`/`confirmed_at`, `conflicts_with`, timestamps.
- Billing/quota: N/A — no AI usage is incurred in PR2.
- RED autonomy conditions: none triggered. No tenancy/RBAC architecture change, no destructive migration, no Brand Brain contract change, no new infrastructure.

## Stop decision
- PROCEED
- Reason: PR2 is additive (one new app, one new migration, no changes to existing models or to the permission architecture) and every integrity rule maps onto an enforcement pattern already approved in PR1.
