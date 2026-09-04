# Tab closure — integrated self-review

Date: 2026-09-04. Branch: `codex/tab-by-tab-product-closure`; starting checkpoint `c42c1c52`. Immutable evidence for `TAB_CLOSURE_ALL_GAPS_PREFLIGHT_2026-09-04.md` and the Context snapshot addendum.

## Disposition

The implemented changes pass the integrated code gates. **The complete all-gaps request is NOT COMPLETE:** one additional compiler-entry correction requires explicit user approval. Nothing from this turn was committed, pushed, merged or deployed. Existing unrelated `.claude/` files were preserved.

## Delivery matrix

| Scope | Verdict | Implementation / evidence |
| --- | --- | --- |
| PUB-01–06 and explicit template choice | PASS | Editor-only generation mutations, immutable tracking rows, dispatch-time account/workspace recheck, saved-copy/image-only recovery, durable retry ownership, preserved failed-publish selections and bounded history queries. `TAB_PUBLISHING_CLOSURE_SELF_REVIEW_2026-09-04.md`: 225 affected tests; 8 frontend state tests. |
| CON-01–03, ENG-01, SYNC-01, ANA-01 | PASS | Strict list parsing, preserved stale data with error/retry, preview recovery, accessible selected Content status, authoritative sync polling, measured-versus-unknown metrics and original-currency revenue. `CONTENT_ENGAGEMENT_ANALYTICS_CLOSURE_SELF_REVIEW_2026-09-04.md`: 39 affected tests and 3 list-parser tests. |
| ADM-01–03, SET-01, PLAT-01–02 | PASS | Explicit route reactivation, health invalidation, bounded/retryable activity, independent Settings reads, paginated platform lists and audited platform-only availability UI. `TAB_ADMIN_SETTINGS_PLATFORM_SELF_REVIEW_2026-09-04.md`: 206 affected tests. No attempts now means unavailable latency, not a measured 0 ms. |
| Brand evidence and provenance | PASS | `apps/knowledge/test_evidence_boundaries.py`: 10 tests cover immutable source identity/storage, memory provenance, machine-evidence forgery, archived/expired confirmation, edited facts needing a new verdict, preserved event history, inspiration lineage, refused raw LearningEvent creation and constant-query preference evidence. Existing PR2 manual signal weight/confidence editing remains available and triggers rebuild. |
| Brand read paths and Needs review | PASS | `apps/brands/test_read_boundaries.py`: 4 tests cover both VIEWER read aliases, write-free onboarding summaries, stale-compile warning and memory validity at ordinary compilation. Needs review independently loads sources, facts, references and signals; malformed responses throw rather than become empty. Candidate facts, failed processing/analysis and correction links were observed in the local authenticated browser. |
| Social OAuth / health / audit | PASS | `apps/social_accounts/test_authority_recovery.py`: 13 tests cover actor-bound one-use state, revoked/downgraded authority, post-provider recheck, platform/workspace binding, shared Instagram/Meta callback, empty/tokenless responses, real X HTTP classification, transient failures, truthful disconnect and audited publishing changes. Credentials are never exposed by the new UI. |
| Generation snapshot validity | PASS | `apps/context/test_snapshot_validity.py`: 11 tests cover expiry/future boundaries, failed revoke/edit rebuilds, warm caches, fail-closed compilation, tenant isolation, universal precedence/attribution, fixed-query checks and read purity. Existing compiler and Context Gateway ownership and persisted Brain shape remain unchanged. |
| Platform preloaded compilation validity | FAIL — approval required | `apps/platform/views_clients.py:301` gathers confirmed facts without validity dates for missing snapshots, then calls `compile_brand_brain_from_records` at line 359. Its preloaded path can still include expired/not-yet-valid facts in the platform readiness calculation. Applying the same date predicate centrally was rejected by the approval gate as a Brand Brain semantics change. That patch was not applied or retried. |

## Integrated verification

| Gate | Verdict | Result |
| --- | --- | --- |
| Full backend regression after all applied backend edits | PASS | **1,349 tests, zero failures**, zero Django system-check issues. Isolated in-memory SQLite; no production database. |
| Frontend logic regression | PASS | **11/11** using `node --experimental-strip-types --test tests/*.test.mjs`. |
| Frontend typecheck | PASS | Final `tsc --noEmit`, no diagnostics. |
| Full frontend lint | PASS | Final `eslint .`: **0 errors, 14 existing warnings** (hook dependencies / development fast-refresh exports). No semantic lint rule disabled. |
| Production frontend build | PASS | Final `npm run build`: client, SSR and Nitro output completed, exit 0. |
| Django standalone system / migration consistency | PASS | `manage.py check`: zero issues. `makemigrations --check --dry-run`: no changes detected. No model/schema changes in this delivery. |
| Whitespace integrity | PASS | `git diff --check`, no whitespace errors. |
| Local authenticated browser checks listed below | PASS | Real local API, disposable SQLite database and synthetic client/user. |
| Complete post-change browser replay / real external actions | NOT VERIFIED | Not every data-filled failure path was driven in the browser; external OAuth, paid generation, real sync/publishing and production load remain outside this execution. Unit/integration tests exercise those boundaries with mocks. This is not 100% live-product certification. |

Formatting cleanup accepts the checkout's native LF/CRLF, excludes generated framework output and mechanically fixes existing Prettier errors. Source lint and all semantic rules remain active. No unrelated feature rewrite, migration, provider default selection or automatic template selection was introduced.

## Browser evidence and limits

- Synthetic user signed in; Overview loaded. Needs review displayed a candidate fact, failed source and failed inspiration; its inspiration link opened the correct tab and retry control.
- Content showed the saved draft, editable fields and an explicit failed-preview alert with Retry preview. Phone-width Rejected selection was pressed and fully visible (left 278, right 359, page width 375); no page overflow.
- All four Analytics tabs opened. Unmeasured metrics showed unavailable, and INR 100 / USD 10 remained separate in summary and revenue lineage.
- All five Admin tabs opened. Add provider, all nine independent routing capabilities, round-robin choices, activity and Missions remained available under the existing role gate. No provider was enabled or called.
- Settings workspace/access/usage loaded independently. All seven Platform pages opened; list filters/counts, continuation controls, global provider availability and mobile navigation were inspected without mutations. Platform mobile page width equaled content width.
- Local evidence: `docs/audits/tab-by-tab-2026-09-03/45-local-content-recovery.jpg` through `48-local-content-mobile.jpg`. Earlier `01`–`44` are deployed-reference captures, not proof of these branch changes.
- Final Engagement/Studio browser replay was interrupted by the in-app browser's `ERR_NETWORK_IO_SUSPENDED`; no pass is claimed for that replay. Their focused/backend/logic gates passed. Temporary viewport override was reset.

The React best-practices and full-story verification checklists drove independent loading states, bounded reads, stale-response protection and failure/return-path tests. They do not substitute for real provider configuration or production release checks.

## Exact remaining decision

Approve applying `valid_from <= now < valid_until` (with null bounds allowed) inside the existing preloaded Brand Brain compiler entry so Platform's missing-snapshot/readiness path follows the same fact-validity rule as generation. Preserve the public/persisted schema and precedence; add the preloaded-entry regression, then rerun affected gates before release. No approval for publishing, changing credentials or deployment is implied by that decision.
