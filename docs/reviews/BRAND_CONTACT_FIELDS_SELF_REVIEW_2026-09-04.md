# Brand contact fields — immutable integration self-review

## Build identity and attribution

- Date: 2026-09-04. Branch/base: `codex/tab-by-tab-product-closure`, `5a3a1ab3`; new integration remains local and uncommitted.
- Approved scope/preflight: `BRAND_CONTACT_FIELDS_PREFLIGHT_2026-09-04.md`.
- Original author: commit `e2daa9fbfb8f985756b926d97669e3d77584707c`, co-authored by Claude, on the separate onboarding branch. It was not contained in the checked current branch. The initial current-branch-only assessment missed that existing implementation; the subsequent all-ref history check corrected the attribution.
- Codex work here: integrate the two existing fields with current code, preserve the original migration identity, join the migration graph, add input accessibility/length bounds, and verify persistence, permissions, privacy and failure recovery. No unrelated signup/approval changes imported.
- Adversarial self-review performed after implementation: YES.

## Implementation and dependency evidence

| Boundary / requirement | Status | Evidence |
| --- | --- | --- |
| UI → shared save queue | PASS | `ClientBasicsSection` renders optional Legal business name / Contact person inputs with accessible names and limits 255/150. Existing `useBrandSettings` owns both, including defaults, DTO, read mapping, PATCH mapping and save recovery. No additional save queue. |
| API → persistence → reload | PASS | `test_json_and_multipart_post_put_patch_round_trip_through_all_reads` covers six mutation combinations, actual database values, detail/list/current reads and Unicode. Local browser independently saved both values and reloaded the page. |
| Optional and independent values | PASS | `test_internal_create_and_legacy_api_create_default_to_empty_strings`, `test_optional_fields_may_be_blank_on_every_mutation_path`, `test_partial_edits_and_explicit_clears_preserve_the_other_values`, `test_omitted_contact_fields_in_put_leave_existing_values_unchanged`. Browser also verified partial edit and clearing. |
| Input validation / atomic failures | PASS | `test_maximum_length_is_accepted_on_all_mutation_paths`, `test_over_limit_rejected_atomically_on_all_mutation_paths`, `test_null_and_structured_values_are_rejected_without_changing_contacts`. No partial invalid updates or silent truncation. |
| Authentication and roles | PASS | `test_anonymous_requests_cannot_read_or_write_contact_fields`, `test_viewer_can_read_but_cannot_mutate_contact_fields_on_any_path`; existing EDITOR write and VIEWER read policy retained. |
| Tenant ownership | PASS | `test_foreign_workspace_cannot_read_mutate_or_receive_contact_values`, `test_workspace_injection_does_not_move_contact_values_between_tenants`; no new owner or FK paths. |
| Intelligence / lineage boundary | PASS | `test_contact_only_changes_do_not_change_compiled_identity_or_learning`, `test_mixed_identity_edit_records_only_identity_fields_not_contact_values`. Administrative values are not inserted into compiled Brain or identity learning events. Existing compiler/provider/publishing contracts unchanged. |
| Failure → retained draft → retry | PASS | Browser intercepted one contact PATCH with a synthetic 500, observed the visible failure and retained input, retried Save successfully and confirmed the value after reload. No paid or production calls. |
| Migration compatibility | PASS | Original `0006_brand_intake_contact` blob matches Claude's commit exactly (`3963de1dbc9488549b2ad3cdae50af0f298b320a`). Empty `0007_merge_contact_guardrails` joins the two existing 0006 histories. Three migration tests assert one leaf, complete state, and only the missing migration planned for either prior branch. Disposable local database migrated successfully. |
| Mobile and browser runtime | PASS | At 390px both input bounds remained inside the viewport. Screenshot `BRAND_CONTACT_FIELDS_MOBILE_2026-09-04.png` was captured and visually inspected. No browser page errors occurred during the flow. |
| New async/provider/storage behavior | N/A | This is synchronous Brand persistence through existing services, with no new task, asset, URL fetch or provider operation. |
| Production migration / deployment | N/A | User approved implementation, not a new production release in this turn. No production changes, commit, push, merge or deploy performed. |

All named backend tests above are in `apps.brands.test_contact_fields`.

## Verification results

| Gate | Status | Result |
| --- | --- | --- |
| Focused backend | PASS | 90 tests in 4.994s, including 17 new contact/migration tests and existing brand, read-boundary, admin and compiler coverage. |
| Full backend | PASS | `manage.py test --noinput --verbosity 1`: 1,372 tests in 52.854s, exit 0; zero Django system-check issues. Isolated in-memory SQLite with test-only process configuration. |
| Migration drift | PASS | `makemigrations --check --dry-run`: no changes detected. |
| Frontend logic | PASS | Existing Node logic tests: 11/11. These are baseline regressions; new-field behavior was verified through the actual local browser/API. |
| Frontend typecheck | PASS | `tsc --noEmit`, exit 0. |
| Frontend lint | PASS | Full ESLint: zero errors, 14 existing warnings. Only the three edited frontend files were formatted. |
| Production frontend build | PASS | Client, SSR and Nitro builds completed, exit 0. |
| Browser/API integration | PASS | Synthetic local user and independent SQLite; real form → PATCH → persistence → reload. Unicode, failed-save retry, clearing and phone layout checked. Browser and both preview servers stopped afterwards. |
| Whitespace | PASS | Scoped and integrated `git -c core.safecrlf=false diff --check`, exit 0. |

## Verification environment notes

The first full backend attempt used an invalid throwaway encryption-key length in the test process. That test configuration was corrected; the complete rerun above passed. No credential/settings files or application credentials changed. An initial focused test assertion attempted to JSON-encode a UUID response object; it was corrected to inspect serialized response bytes, and all focused/full tests subsequently passed.

The production build required an approved retry to write its dependency cache outside the sandbox. The optional agent-browser CLI and bundled Chromium were unavailable, so the installed Playwright runtime drove installed Edge headlessly against loopback-only services. No dependency install was needed. The normal image viewer helper was unavailable; the same local screenshot was read through the shell for visual inspection without altering it.

## Acceptance

READY for the approved two-field integration: mandatory FAIL=0, NOT VERIFIED=0. No architecture deviations. The React/verification checklists influenced accessible input names, preservation of the shared save queue, actual save/reload/failure proof and isolation from generated content. Broader signup/approval work from Claude's original branch is explicitly outside this integration. Deployment still requires applying the included migrations through the existing release process; this report is not a claim that the feature is live.
