# PR02_SELF_REVIEW.md — Evidence Gate

## Build identity
- PR: PR2 — Inspiration Intelligence Foundation
- Base commit: `50c1f2b` on `marketinghub/merge`
- Head commit: see the PR2 commit on `marketinghub/merge` (`feat(pr2): inspiration intelligence foundation`)
- Reviewer mode run after implementation: YES — see `docs/reviews/PR02_SECURITY_ATTACK_MATRIX.md`

All test names below are in `Marketing_backend/apps/inspirations/tests.py` unless stated otherwise.

## Requirement traceability
| Req ID | Status | Evidence | Notes |
|---|---|---|---|
| R1 — inspiration belongs to the authenticated workspace and brand | PASS | `test_create_inspiration_with_source_provenance` (workspace is server-set from the request), `test_cross_tenant_brand_injection_blocked` (400, asserts no row created for the foreign brand) | `workspace` is serializer read-only and set in `perform_create`. |
| R2 — referenced source is same workspace AND same brand | PASS | `test_cross_tenant_source_injection_blocked`, `test_cross_brand_source_injection_blocked_inside_one_workspace`, `test_upload_cross_tenant_source_injection_blocked`, `test_upload_cross_brand_source_injection_blocked` | One shared validator, `serializers.validate_reference_graph`, used by both entry paths. |
| R3 — brand not silently movable after creation | PASS | `test_patch_cannot_move_inspiration_to_another_brand`, `test_patch_cannot_move_inspiration_to_another_tenant_brand`, `test_put_cannot_move_inspiration_to_another_brand` (each re-reads the row and asserts the brand is unchanged) | No transfer workflow exists, so any change is rejected (PR1-009). |
| R4 — signals transitively tied to the inspiration workspace/brand | PASS | `test_signal_mirrors_parent_workspace_and_brand`, `test_signal_cannot_attach_to_other_tenant_inspiration`, `test_signal_inspiration_is_immutable`, `test_signal_detail_is_404_cross_tenant` | `InspirationSignal` has no workspace/brand column; the viewset scopes on `inspiration__workspace`. |
| R5 — user-stated and AI-inferred are never indistinguishable | PASS | `test_payload_cannot_mint_an_ai_signal`, `test_patch_cannot_convert_ai_signal_to_user_origin`, `test_confirming_an_ai_signal_keeps_it_ai_derived` | `origin` is read-only and server-assigned; confirmation is a separate axis. |
| R6 — AI inference never silently overrides an explicit preference | PASS | `test_ai_signal_does_not_overwrite_user_signal` (user row unchanged; AI row flagged and ineligible), `test_agreeing_ai_signal_is_not_flagged_as_conflict`, `test_reanalysis_does_not_reset_a_user_verdict` | Enforced in `services.record_ai_signal`, the only writer of `origin=AI`. |
| R7 — liked/disliked/neutral explicit, not inferred from weight | PASS | `test_sentiment_is_required` (400), `test_weight_does_not_imply_sentiment` (weight 0.95 with DISLIKED stored as DISLIKED), `test_weight_out_of_range_is_rejected` | `sentiment` is a required API field even though the model has a default. |
| R8 — revoked/archived references become ineligible | PASS | `test_archive_makes_inspiration_ineligible`, `test_archived_source_makes_inspiration_ineligible`, `test_inspiration_without_a_source_stays_eligible`, `test_eligible_only_filter_matches_the_retrieval_rule`, `test_rejected_signal_is_ineligible`, `test_signals_of_archived_inspiration_are_ineligible`, `test_archived_source_cannot_start_a_new_inspiration`, `test_archived_inspiration_cannot_receive_new_signals` | Eligibility is a queryset (`eligible_for_retrieval()`) plus a per-row `retrieval_eligibility` verdict in the API, so the future gateway and the UI read the same rule. |
| R9 — original reference and derived signals separately addressable | PASS | `test_inspiration_and_signals_are_separately_addressable` (both detail routes 200; `?inspiration_id=` filter returns exactly the child) | Two models, two routers, two URL families. |
| R10 — no cross-tenant sharing of raw inspiration data | PASS | `test_inspiration_detail_is_404_cross_tenant`, `test_list_excludes_other_tenant_inspirations`, `test_staff_without_membership_cannot_read`, `test_every_mutation_path_is_404_for_another_tenant` | `WorkspaceScopedMixin` on both viewsets. |
| R11 — media-neutral reference types and metadata | PASS | `test_supported_inspiration_types_are_provider_neutral` (reel/pin/competitor/video/screenshot with `external_platform` values including empty) | `external_platform` is free text; no provider is hard-coded. |
| R12 — "use only the typography" vs "use the whole reference" | PASS | `test_partial_usage_scope_expresses_use_only_typography`, `test_specific_elements_requires_focus_areas`, `test_full_reference_rejects_focus_areas`, `test_unknown_focus_area_is_rejected`, `test_usage_scope_can_be_widened_back_to_the_whole_reference`, `test_patch_to_specific_elements_without_focus_areas_is_rejected` | `usage_scope` + `focus_areas` drawn from the same `SignalCategory` vocabulary the signals use. |
| R13 — no fake success for analysis | PASS | `test_analyze_is_not_implemented` (501, `success=false`, `analysis_status` still `NOT_ANALYSED`), `test_analyze_archived_inspiration_is_rejected` | `grep -n "AnalysisStatus" apps/inspirations/*.py` shows the field is never assigned outside its model default. |
| R14 — RBAC: viewer is read-only | PASS | `test_viewer_can_read` plus six denial tests (`create`, `upload`, `patch`, `archive`, `create signal`, `confirm/reject`) | Reuses `HasWorkspaceRole` with `required_role=EDITOR`, `required_read_role=VIEWER`. |
| R15 — multipart path enforces the same rules (PR1-007) | PASS | `test_upload_cross_tenant_brand_injection_blocked`, `test_upload_cross_tenant_source_injection_blocked`, `test_upload_cross_brand_source_injection_blocked` (each asserts no row was created), `test_viewer_cannot_upload_inspiration`, `test_upload_stores_reference_and_server_assigns_storage` | Shared `validate_reference_graph`, and validation runs before storage is touched. |
| R16 — provenance is not destroyed | PASS | `test_delete_inspiration_is_disabled`, `test_delete_signal_is_disabled` (405; rows still present), `test_patch_cannot_change_source_provenance`, `test_client_cannot_set_storage_coordinates` | Archive and reject replace deletion. |

## Dependency verification
| Dependency | Status | Evidence |
|---|---|---|
| Auth → workspace | PASS | `IsWorkspaceMember` + `get_request_workspace` reused unchanged; `test_staff_without_membership_cannot_read`, `test_list_excludes_other_tenant_inspirations` |
| Workspace → brand | PASS | `validate_reference_graph` brand check; `test_cross_tenant_brand_injection_blocked`, `test_upload_cross_tenant_brand_injection_blocked` |
| Input → validation | PASS | Same validator on JSON and multipart; `test_inspiration_requires_a_reference`, `test_specific_elements_requires_focus_areas` |
| Validation → persistence | PASS | Every negative test asserts absence of a row or an unchanged row, not just the status code (e.g. `test_upload_cross_tenant_brand_injection_blocked` asserts `BrandInspiration.objects.exists()` is False) |
| Persistence → service/job | PASS | `services.record_ai_signal` is the only writer of `origin=AI`; `test_record_ai_signal_is_idempotent`, `test_duplicate_ai_signal_rows_are_rejected_by_the_database` |
| Job → honest state | PASS | No job exists; `analyze` returns 501 and writes nothing — `test_analyze_is_not_implemented` |
| State → downstream consumer | PASS | `eligible_for_retrieval()` on both managers is the contract PR5 will call, and the API exposes the identical rule — `test_eligible_only_filter_matches_the_retrieval_rule` |
| API → UI (if applicable) | N/A | PR2 is backend only. The Brand Master UI is PR7; no frontend file is touched in this PR (`git diff --stat` shows no path under `Marketing_Frontend/`). |
| Failure → user-visible/error state | PASS | 400 validation, 403 role, 404 out-of-tenant, 405 delete-disabled, 501 not-implemented, 502 storage — each with a message; the 502 branch is code-path evidence only (see STORE-01 in the attack matrix). |
| Provenance/lineage | PASS | `source`, `created_by`, `archived_by`/`archived_at`, `origin`, `extracted_by_provider`, `confirmed_by`/`confirmed_at`, `conflicts_with`; `test_ai_signal_does_not_overwrite_user_signal` proves the conflict is recorded rather than resolved by overwrite |

## Test evidence
- Changed-module tests: `python manage.py test apps.inspirations` → **Ran 65 tests, OK** (0 failures, 0 errors).
- Security/adversarial tests: 30 of the 65 are adversarial (classes `InspirationTenantIsolationTests`, `InspirationImmutabilityTests`, `InspirationRBACTests`, plus the negative cases in `InspirationProvenanceTests`, `InspirationSentimentTests`, `InspirationLifecycleTests`, `InspirationUsageScopeTests`). Mapped attack-by-attack in `docs/reviews/PR02_SECURITY_ATTACK_MATRIX.md`.
- Full backend: `python manage.py test` → **Ran 367 tests in 348.6s, OK** (0 failures, 0 errors) with the environment configured. 367 = the 302-test baseline + the 65 new tests; no existing test changed behaviour.
- Baseline comparison (the PR0-003 environment dependency, not caused by PR2):
  - Base commit `50c1f2b`, no environment set: **302 tests, FAILED (errors=7)** — all 7 raise `ValueError: FERNET_SECRET_KEY environment variable is not set` from `apps/social_accounts/utils/encryption.py`.
  - This PR, with only `FERNET_SECRET_KEY` set: **367 tests, FAILED (errors=2)** — both are `apps.social_accounts.tests.LinkedInAdapterTests` raising `LinkedInConfigurationError` from `apps/social_accounts/integrations/linkedin.py:67`, which triggers when `LINKEDIN_CLIENT_ID`/`LINKEDIN_CLIENT_SECRET` are empty.
  - This PR, with `FERNET_SECRET_KEY` and the three `LINKEDIN_*` variables set: **367 tests, OK**.
  - So the only errors reachable in this tree come from unset environment variables in `apps.social_accounts`, a module PR2 does not touch (`git diff --stat` lists no file under `apps/social_accounts/`).
- Frontend build / typecheck / lint: N/A — no frontend file is modified by this PR.
- Migration check: `python manage.py makemigrations --check --dry-run` → **No changes detected** (models and migrations are in sync). One new migration, `apps/inspirations/migrations/0001_initial.py`, purely additive: two new tables, no alteration or deletion of existing tables.
- Other: `grep -rn "requests\|urlopen\|httpx" apps/inspirations/` → no matches (nothing fetches a reference URL). `grep -rn "apps.ai" apps/inspirations/` → no matches (no provider call).

## Known gaps
Deferred scope only, each tied to a later PR:
- **Inspiration analysis** — `POST /inspirations/{id}/analyze/` returns `501`. Extraction, transcription and vision analysis belong to **PR6**; `analysis_status` already carries the states that job will need.
- **Reference-URL fetching and egress control** — PR2 stores `reference_url` and never dereferences it. Whoever fetches it in **PR6** must add SSRF controls; there is nothing to protect yet.
- **Retrieval/ranking** — `eligible_for_retrieval()` answers "may this be used", not "should it be used now". Relevance ranking and context budgeting are **PR5**.
- **Brand Brain integration** — inspiration signals are not compiled into `Brand.creative_brain`. That is **PR4**.
- **Learning fabric** — confirm/reject records a verdict on the signal itself; it does not emit a `LearningEvent`. That is **PR3**.
- **Brand Master UI** — no frontend. **PR7**.
- **Pre-existing, not introduced here:** `apps.social_accounts` tests error when the environment is bare — 7 on `FERNET_SECRET_KEY`, 2 more on the `LINKEDIN_*` credentials. This is the PR0-003 violation already recorded in `docs/CTO_REVIEW_LOG.md` ("tests must not depend on developer `.env` state"): those tests should stub the configuration rather than read the process environment. It is unrelated to inspirations, and fixing it means editing `apps.social_accounts`, outside the PR2 boundary. Flagged for the CTO to schedule.

## Deviations
- **`source` is immutable after creation, not merely brand-locked.** The PR2 contract only requires that brand cannot move. Allowing the provenance link to be re-pointed later would let a reference silently acquire a different origin, so it is frozen at creation. Reversible if a reviewer wants it looser.
- **`services.record_ai_signal` exists although PR2 ships no AI.** The integrity rule "AI inference must never silently override explicit user preference" has to be true of the first inferred row ever written. This is the minimal contract that makes it true, not an implementation of PR6: it makes no provider call and is invoked only by tests.
- **`docs/ARCHITECTURE.md` also gained a section for `apps.knowledge` (PR1).** The doc had never been updated for PR1, and PR0-002 requires it to describe the live repository. Documentation only.
- **Governance files synced from the V4 handoff:** `AGENTS.md` replaced with the V4 operating system, `CLAUDE_START_HERE.md`, `docs/FAST_EXECUTION_PROTOCOL.md`, `docs/PR2_EXECUTION_OVERRIDE.md` and `docs/templates/` added, and `docs/CTO_REVIEW_LOG.md` **appended** with PR1-007..011 and GLOBAL-006..010. No prior PR evidence was overwritten.

## Readiness
- PASS count: 16 requirement lines, 9 dependency lines, 20 attack lines
- N/A count: 4 (frontend dependency line; attack matrix INT-01, AI-01, BILL-01 — each with a stated reason)
- FAIL count: 0
- NOT VERIFIED count: 0

PR2 is READY for independent CTO review.
