# Admin, Settings and Platform closure evidence — 2026-09-04

Immutable focused evidence for ADM-01..03, SET-01 and PLAT-01..02 under `TAB_CLOSURE_ALL_GAPS_PREFLIGHT_2026-09-04.md`. This report does not replace the root-owned integrated gate or main tab ledger. No commit, deployment, live settings change, provider call or credential inspection was performed.

## Implemented vertical paths

- ADM-01: inactive persisted AI routes remain inactive after provider re-enable; the UI identifies them and requires an explicit route save. Disabled selected providers block activation. Existing route selection, round-robin and failure ownership are unchanged.
- ADM-02: provider credentials or effective connection/model/capability configuration changes clear historical health. Identical configuration and spend-limit-only updates retain that history. The UI labels results as historical checks, not current readiness.
- ADM-03: usage summary and recent usage load independently, expose independent failures, and preserve a successful counterpart. Recent usage requests are bounded to 25 rows. Unknown/failed results are not displayed as zero or empty success.
- SET-01: Settings workspace and identity reads have independent loading/error/retry states and shape validation. Usage has explicit loading/error/retry. An identity failure cannot masquerade as a confirmed permission denial.
- PLAT-01: Signups, Standards, Patterns and Library support opt-in server pagination, search/filtering, authoritative totals/facets, stable ordering and continuation UI. Legacy non-paged consumers retain their response shapes and caps. Page requests are bounded and stale frontend responses cannot overwrite the active filter/page.
- PLAT-02: the Platform Overview exposes the existing audited provider-availability mutation using a paged global catalogue. Only live PlatformAdmin authority can read/control it; tenant-owned providers and credentials/configuration are excluded. Changes require confirmation and do not enable workspace providers or routes.

## Evidence matrix

| Check | Result and evidence |
| --- | --- |
| Historical health invalidation | PASS — `apps.ai.test_admin_closure.AdminClosureTests.test_changed_connection_configuration_invalidates_historical_health` and `test_identical_configuration_and_spend_limit_do_not_reset_health`; implementation `apps/ai/serializers.py`. |
| Explicit route reactivation | PASS — `test_reenable_preserves_inactive_routes_until_explicit_route_save`; UI in `src/components/marketing/ai-providers-panel.tsx`. |
| Workspace role and usage isolation | PASS — `test_viewer_cannot_change_or_read_provider_configuration`, `test_recent_usage_is_bounded_and_workspace_scoped`. |
| Pagination beyond old caps | PASS — four continuation tests in `apps/platform/test_list_closure.py` each traverse 501 records in three non-overlapping pages and verify out-of-range results. |
| Search/filter/count correctness and backward compatibility | PASS — `test_status_kind_search_counts_are_server_authoritative`, `test_invalid_page_values_are_bounded_and_legacy_lists_stay_unchanged`. |
| Platform roles and data boundary | PASS — `test_platform_lists_reject_workspace_staff_and_revoked_platform_admin`, `test_availability_catalogue_exposes_no_tenant_provider_or_credentials`; the latter also exercises the existing audited availability mutation and rejects workspace staff. |
| Bounded database work | PASS — `test_library_page_query_count_does_not_grow_per_row`; shared server page size defaults to 25 and is capped at 200. |
| New focused backend tests | PASS — `manage.py test apps.ai.test_admin_closure apps.platform.test_list_closure --verbosity 1`: 14 tests, 2.048 seconds; Django system check: zero issues. |
| Affected-app backend regression | PASS — `manage.py test apps.ai apps.platform --verbosity 0`: 206 tests, 14.088 seconds; Django system check: zero issues. Test-only generated Fernet/signing keys were set in the test process, with no live configuration changes. |
| Integrated frontend types | PASS — `tsc --noEmit -p Marketing_Frontend/tsconfig.json`: exit 0 after sibling Analytics changes were completed. |
| Focused frontend formatting/lint | PASS — Prettier and ESLint on all 11 changed frontend files listed below: exit 0. No global lint configuration was changed by this slice. |
| Whitespace integrity | PASS — scoped `git diff --check`: exit 0; only native checkout LF/CRLF notices. |
| Migration gate | N/A — no model/schema changes in this slice. |
| Production build, full repository regression/lint and browser gate | NOT VERIFIED by this subagent — consolidated gate belongs to the root integration task. This focused report alone does not declare the complete PR ready. |

The React best-practices checklist informed independent asynchronous reads, bounded fetches, cancellation/stale-response protection, and explicit accessible loading/error states.

## Changed frontend scope

1. `Marketing_Frontend/src/components/marketing/ai-providers-panel.tsx`
2. `Marketing_Frontend/src/components/marketing/usage-panel.tsx`
3. `Marketing_Frontend/src/routes/_hub.settings.tsx`
4. `Marketing_Frontend/src/routes/platform.signups.tsx`
5. `Marketing_Frontend/src/routes/platform.standards.tsx`
6. `Marketing_Frontend/src/routes/platform.patterns.tsx`
7. `Marketing_Frontend/src/routes/platform.library.tsx`
8. `Marketing_Frontend/src/routes/platform.index.tsx`
9. `Marketing_Frontend/src/lib/use-platform-page.ts`
10. `Marketing_Frontend/src/components/platform/list-controls.tsx`
11. `Marketing_Frontend/src/components/platform/provider-availability.tsx`

## Preserved boundaries

No AIRouter/Context Gateway ownership change, provider credential duplication, automatic route enablement, billing semantics change, tenant/RBAC redesign, destructive migration, publishing architecture change or live action. Existing list consumers may omit page parameters and retain their old contract. The shared checkout's sibling changes were preserved.
