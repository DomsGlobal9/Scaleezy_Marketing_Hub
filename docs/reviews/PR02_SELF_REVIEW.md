# PR02_SELF_REVIEW.md — Evidence Gate

## Build identity
- PR: PR2 — Inspiration Intelligence Foundation
- Base commit: `50c1f2b` on `marketinghub/merge`
- Head commits: `d63af0e` (first implementation) and the Accelerator V5 hardening pass on top of it
- Reviewer mode run after implementation: YES — see `docs/reviews/PR02_SECURITY_ATTACK_MATRIX.md`
- Execution standard: `SCALEEZY_CLAUDE_ACCELERATOR_V5_PR2`. The gap analysis against
  `docs/GOLDEN_PATTERNS.md` and `docs/TEST_HARNESS_SPEC.md`, and what changed as a
  result, is in `docs/reviews/PR02_V5_INTAKE.md`.

All test names below are in `Marketing_backend/apps/inspirations/tests.py` unless stated otherwise.
Negative assertions run through `Marketing_backend/apps/common/testing.py`, whose helpers
assert the response **and** that the database did not move — so "rejected" in this
document always means "rejected and nothing was written".

## Requirement traceability
| Req ID | Status | Evidence | Notes |
|---|---|---|---|
| R1 — inspiration belongs to the authenticated workspace and brand | PASS | `test_create_inspiration_with_source_provenance` (workspace is server-set from the request), `test_cross_tenant_brand_injection_blocked` (400, asserts no row created for the foreign brand), `test_model_refuses_a_brand_from_another_workspace` (ORM writers too) | `workspace` is serializer read-only and set in `perform_create`; the `brand` queryset is workspace-scoped, `validate()` re-checks, and `BrandInspiration.save()` enforces the invariant for non-request writers. |
| R2 — referenced source is same workspace AND same brand | PASS | `test_cross_tenant_source_injection_blocked`, `test_cross_brand_source_injection_blocked_inside_one_workspace`, `test_upload_cross_tenant_source_injection_blocked`, `test_upload_cross_brand_source_injection_blocked`, `test_model_refuses_a_source_from_another_brand`, `test_model_refuses_a_source_from_another_workspace` | One shared validator, `serializers.validate_reference_graph`, used by both request paths, plus the `save()` invariant for ORM writers. |
| R3 — brand not silently movable after creation | PASS | `test_patch_cannot_move_inspiration_to_another_brand`, `test_patch_cannot_move_inspiration_to_another_tenant_brand`, `test_put_cannot_move_inspiration_to_another_brand` (each re-reads the row and asserts the brand is unchanged) | No transfer workflow exists, so any change is rejected (PR1-009). |
| R4 — signals transitively tied to the inspiration workspace/brand | PASS | `test_signal_mirrors_parent_workspace_and_brand`, `test_signal_cannot_attach_to_other_tenant_inspiration`, `test_signal_inspiration_is_immutable`, `test_signal_is_hidden_from_the_other_tenant` | `InspirationSignal` has no workspace/brand column; the viewset scopes on `inspiration__workspace`. |
| R5 — user-stated and AI-inferred are never indistinguishable | PASS | `test_payload_cannot_mint_an_ai_signal`, `test_patch_cannot_convert_ai_signal_to_user_origin`, `test_confirming_an_ai_signal_keeps_it_ai_derived` | `origin` is read-only and server-assigned; confirmation is a separate axis. |
| R6 — AI inference never silently overrides an explicit preference | PASS | `test_ai_signal_does_not_overwrite_user_signal` (user row unchanged; AI row flagged and ineligible), `test_agreeing_ai_signal_is_not_flagged_as_conflict`, `test_reanalysis_does_not_reset_a_user_verdict` | Enforced in `services.record_ai_signal`, the only writer of `origin=AI`. |
| R7 — liked/disliked/neutral explicit, not inferred from weight | PASS | `test_sentiment_is_required` (400), `test_weight_does_not_imply_sentiment` (weight 0.95 with DISLIKED stored as DISLIKED), `test_weight_out_of_range_is_rejected` | `sentiment` is a required API field even though the model has a default. |
| R8 — revoked/archived references become ineligible | PASS | `test_archive_makes_inspiration_ineligible`, `test_archived_source_makes_inspiration_ineligible`, `test_inspiration_without_a_source_stays_eligible`, `test_eligible_only_filter_matches_the_retrieval_rule`, `test_rejected_signal_is_ineligible`, `test_signals_of_archived_inspiration_are_ineligible`, `test_archived_source_cannot_start_a_new_inspiration`, `test_archived_inspiration_cannot_receive_new_signals` | Eligibility is a queryset (`eligible_for_retrieval()`) plus a per-row `retrieval_eligibility` verdict in the API, so the future gateway and the UI read the same rule. |
| R9 — original reference and derived signals separately addressable | PASS | `test_inspiration_and_signals_are_separately_addressable` (both detail routes 200; `?inspiration_id=` filter returns exactly the child) | Two models, two routers, two URL families. |
| R10 — no cross-tenant sharing of raw inspiration data | PASS | `test_inspiration_is_hidden_from_the_other_tenant`, `test_staff_without_membership_cannot_read`, `test_every_mutation_path_is_404_for_another_tenant` | `WorkspaceScopedMixin` on both viewsets. |
| R11 — media-neutral reference types and metadata | PASS | `test_supported_inspiration_types_are_provider_neutral` (reel/pin/competitor/video/screenshot with `external_platform` values including empty) | `external_platform` is free text; no provider is hard-coded. |
| R12 — "use only the typography" vs "use the whole reference" | PASS | `test_partial_usage_scope_expresses_use_only_typography`, `test_specific_elements_requires_focus_areas`, `test_full_reference_rejects_focus_areas`, `test_unknown_focus_area_is_rejected`, `test_usage_scope_can_be_widened_back_to_the_whole_reference`, `test_patch_to_specific_elements_without_focus_areas_is_rejected` | `usage_scope` + `focus_areas` drawn from the same `SignalCategory` vocabulary the signals use. |
| R13 — no fake success for analysis | PASS | `test_analyze_is_not_implemented` (501, `success=false`, `analysis_status` still `NOT_ANALYSED`), `test_analyze_archived_inspiration_is_rejected` | `grep -n "AnalysisStatus" apps/inspirations/*.py` shows the field is never assigned outside its model default. |
| R14 — RBAC: viewer is read-only | PASS | `test_viewer_can_read` (positive control), `test_viewer_cannot_create_inspiration`, `test_viewer_cannot_upload_inspiration`, `test_viewer_cannot_create_signal`, `test_viewer_cannot_archive_inspiration`, and `test_viewer_is_denied_on_every_mutation_path` covering the other eight paths | Reuses `HasWorkspaceRole` with `required_role=EDITOR`, `required_read_role=VIEWER`. Each denial also asserts the table did not change. |
| R15 — multipart path enforces the same rules (PR1-007) | PASS | `test_upload_cross_tenant_brand_injection_blocked`, `test_upload_cross_tenant_source_injection_blocked`, `test_upload_cross_brand_source_injection_blocked` (each asserts no row was created), `test_viewer_cannot_upload_inspiration`, `test_upload_stores_reference_and_server_assigns_storage` | Shared `validate_reference_graph`, and validation runs before storage is touched. |
| R16 — provenance is not destroyed | PASS | `test_delete_inspiration_is_disabled`, `test_delete_signal_is_disabled` (405; rows still present), `test_patch_cannot_change_source_provenance`, `test_client_cannot_set_storage_coordinates` | Archive and reject replace deletion. |

## Dependency verification
| Dependency | Status | Evidence |
|---|---|---|
| Auth → workspace | PASS | `IsWorkspaceMember` + `get_request_workspace` reused unchanged; `test_staff_without_membership_cannot_read`, `test_inspiration_is_hidden_from_the_other_tenant` |
| Workspace → brand | PASS | `validate_reference_graph` brand check; `test_cross_tenant_brand_injection_blocked`, `test_upload_cross_tenant_brand_injection_blocked` |
| Input → validation | PASS | Same validator on JSON and multipart; `test_inspiration_requires_a_reference`, `test_specific_elements_requires_focus_areas` |
| Validation → persistence | PASS | Every negative test asserts absence of a row or an unchanged row, not just the status code (e.g. `test_upload_cross_tenant_brand_injection_blocked` asserts `BrandInspiration.objects.exists()` is False) |
| Persistence → service/job | PASS | `services.record_ai_signal` is the only writer of `origin=AI`; `test_record_ai_signal_is_idempotent`, `test_duplicate_ai_signal_rows_are_rejected_by_the_database`. Internal writers are held to the tenancy invariant by `BrandInspiration.save()` — `test_model_refuses_a_brand_from_another_workspace` |
| Job → honest state | PASS | No job exists; `analyze` returns 501 and writes nothing — `test_analyze_is_not_implemented` |
| State → downstream consumer | PASS | `eligible_for_retrieval()` on both managers is the contract PR5 will call, and the API exposes the identical rule — `test_eligible_only_filter_matches_the_retrieval_rule` |
| API → UI (if applicable) | N/A | PR2 is backend only. The Brand Master UI is PR7; no frontend file is touched in this PR (`git diff --stat` shows no path under `Marketing_Frontend/`). |
| Failure → user-visible/error state | PASS | 400 validation, 403 role, 404 out-of-tenant, 405 delete-disabled, 501 not-implemented, 502 storage — each with a message; the 502 branch is code-path evidence only (see STORE-01 in the attack matrix). |
| Provenance/lineage | PASS | `source`, `created_by`, `archived_by`/`archived_at`, `origin`, `extracted_by_provider`, `confirmed_by`/`confirmed_at`, `conflicts_with`; `test_ai_signal_does_not_overwrite_user_signal` proves the conflict is recorded rather than resolved by overwrite |

## Test evidence
- Changed-module tests: `python manage.py test apps.inspirations` → **Ran 68 tests, OK** (0 failures, 0 errors).
- Security/adversarial tests: 47 of the 68 assert a rejection or a non-change; the other 21 are positive controls and behaviour tests. Mapped attack-by-attack in `docs/reviews/PR02_SECURITY_ATTACK_MATRIX.md`. `test_viewer_is_denied_on_every_mutation_path` is table-driven and covers eight mutation paths in one test via `subTest`.
- Full backend: `python manage.py test` → **Ran 370 tests in 405.6s, OK** (0 failures, 0 errors) with the environment configured. 370 = the 302-test baseline + the 68 new tests; no existing test changed behaviour.
- Baseline comparison (the PR0-003 environment dependency, not caused by PR2):
  - Base commit `50c1f2b`, no environment set: **302 tests, FAILED (errors=7)** — all 7 raise `ValueError: FERNET_SECRET_KEY environment variable is not set` from `apps/social_accounts/utils/encryption.py`.
  - This PR, with only `FERNET_SECRET_KEY` set: **FAILED (errors=2)** — both are `apps.social_accounts.tests.LinkedInAdapterTests` raising `LinkedInConfigurationError` from `apps/social_accounts/integrations/linkedin.py:67`, which triggers when `LINKEDIN_CLIENT_ID`/`LINKEDIN_CLIENT_SECRET` are empty.
  - This PR, with `FERNET_SECRET_KEY` and the three `LINKEDIN_*` variables set: **370 tests, OK**.
  - So the only errors reachable in this tree come from unset environment variables in `apps.social_accounts`, a module PR2 does not touch (`git diff --stat` lists no file under `apps/social_accounts/`).
- Frontend build / typecheck / lint: N/A — no frontend file is modified by this PR.
- Migration check: `python manage.py makemigrations --check --dry-run` → **No changes detected** (models and migrations are in sync), re-run after the V5 hardening pass — the `save()` invariant is behaviour, not schema. One new migration, `apps/inspirations/migrations/0001_initial.py`, purely additive: two new tables, no alteration or deletion of existing tables.
- Shared harness: `Marketing_backend/apps/common/testing.py`, exercised from 20 call sites across both endpoints (4 cross-tenant FK, 2 cross-brand FK, 5 viewer-denial, 3 immutable-field, 2 protected-state, 2 visibility, 2 duplicate-action). Written per `docs/TEST_HARNESS_SPEC.md` for reuse from PR3 onwards; PR1's `apps.knowledge` tests were deliberately left alone as prior-PR evidence.
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
- **Tenancy invariant enforced in `BrandInspiration.save()`.** GOLDEN_PATTERNS-1 states the invariant as a server rule rather than a serializer rule, so it is enforced where every writer passes. Costs one extra query per save on a low-volume table; raises `ValidationError`, which the API can never reach because the serializers reject first.
- **Governance files synced from the V4 handoff:** `AGENTS.md` replaced with the V4 operating system, `CLAUDE_START_HERE.md`, `docs/FAST_EXECUTION_PROTOCOL.md`, `docs/PR2_EXECUTION_OVERRIDE.md` and `docs/templates/` added, and `docs/CTO_REVIEW_LOG.md` **appended** with PR1-007..011 and GLOBAL-006..010. No prior PR evidence was overwritten.
- **V5 fast-path docs installed:** `CLAUDE_FAST_START.md`, `CURRENT_MISSION_PR02.md`, `docs/GOLDEN_PATTERNS.md`, `docs/REPO_MAP.md`, `docs/TEST_HARNESS_SPEC.md`. The larger architecture documents (`SCALEEZY_M1_MASTER_BLUEPRINT.md`, `API_AND_DATA_CONTRACTS.md`, `PR_EXECUTION_TASKS.md`, `INTEGRATION_CHECKLIST.md`, `SCALEEZY_DEV_MONITORING_PROTOCOL.md`) ship in the handoff package and were deliberately left out of the repository, as in PR0 and PR1 — say the word if they should live in-repo instead.
- **`docs/reviews/PR02_PREFLIGHT.md` was not edited.** It is the immutable preflight for the V4 package. The V5 delta is recorded separately in `docs/reviews/PR02_V5_INTAKE.md` (G-009).

## Readiness
- PASS count: 16 requirement lines, 9 dependency lines, 25 attack lines (23 unqualified; STORE-01 is code-path evidence and URL-01 is scoped to PR2, both stated as such in the matrix)
- N/A count: 4 (frontend dependency line; attack matrix INT-01, AI-01, BILL-01 — each with a stated reason)
- FAIL count: 0
- NOT VERIFIED count: 0

PR2 is READY for independent CTO review.
