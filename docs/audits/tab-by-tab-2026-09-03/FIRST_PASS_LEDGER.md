# Scaleezy — tab-by-tab first-pass delivery ledger

Reviewed 2026-09-03–04. Branch: `codex/tab-by-tab-product-closure`. Base: `5facc0e9`. Reference: current `marketing.scaleezy.com`, authenticated selected-client and Platform Console screens, plus current code and isolated diagnostics.

## Current implementation update — 2026-09-04

The original audit below is retained as historical evidence, not the current unimplemented backlog. PUB-01–06, CON-01–03, ENG-01, SYNC-01, ANA-01, ADM-01–03, SET-01 and PLAT-01–02 are now implemented locally, along with the recorded Brand evidence/Needs-review and Social authority/recovery follow-ups. Existing Editor-or-higher lazy brand bootstrap is retained for journey compatibility; VIEWER cannot provision through reads and onboarding summary no longer writes.

Integrated backend gate after the final approved validity correction: **1,355 tests passed**. Prior frontend gate evidence: **11 frontend logic tests passed; typecheck/build passed; full lint had 0 errors and 14 existing warnings**. Those frontend gates were not rerun for this backend-only correction and do not certify subsequently changed frontend files. No schema changes. Focused local authenticated browser checks passed as enumerated in the integrated report; complete real-provider/production replay is not claimed.

**Final recorded code gap closed after explicit user approval:** Platform's preloaded missing-snapshot compiler now applies the same expired/future-fact filter as ordinary compilation/generation. Six new tests cover date boundaries, matching fingerprints, retained source records, read purity, the actual Platform readiness path and tenant/brand isolation. All recorded code fixes are implemented locally; this is not a certification of complete production replay or live deployment. No commit, push, merge or deploy was performed for this correction.

Current evidence: `docs/reviews/TAB_CLOSURE_ALL_GAPS_SELF_REVIEW_2026-09-04.md` and its focused reports, with the final approved-gap closure recorded in `docs/reviews/PRELOADED_BRAIN_VALIDITY_SELF_REVIEW_2026-09-04.md`. Earlier immutable reports retain their historical blocked status; the final addendum supersedes that one outstanding compiler finding. The following first-pass decisions and gate results predate this implementation.

## Decision in brief

Keep the existing modules and architecture owners. No core module removal or merger is justified by this pass. Remove misleading controls/copy, finish failure and return journeys, and close the concrete execution-boundary gaps before adding more features.

This ledger distinguishes implemented work from confirmed remaining defects. It is not a claim that every production action, provider, permission combination or mobile state has passed end-to-end verification.

## Tab decisions and delivery order

| Order / surface | Decision | Current checkpoint or next work |
| --- | --- | --- |
| 1. Overview | KEEP + FIX | Implemented: honest readiness/counters, direct next actions, mobile navigation clarity; checkpoint `721412f4`. See `OVERVIEW.md`. |
| 2. Brand Master — all 8 tabs | KEEP + FIX | Implemented: clearer labels/correction paths, truthful secondary loading/error states, compiler-owned field protection and retryable queue failures; checkpoint `1cab4dcd`. See `BRAND_MASTER.md`. |
| 3. Social Media Accounts | KEEP + FIX | Implemented: chooser, multiple accounts, role-gated configuration, protected history/asset URLs and truthful states. See `SOCIAL_ACCOUNTS.md`; queued worker enforcement is still open. |
| 4. Publishing / Create Studio | KEEP + FIX NEXT | Preserve explicit creative choice; finish generation role protection, media recovery, authoritative retries and publish-failure return path. |
| 5. Content / Review / Library | KEEP + FIX | Keep one durable history with status views. Align naming, expose load/image failures, improve selected-status accessibility. |
| 6. Engagement | KEEP + FIX | Keep governed inbox and approval-before-send. Finish sync completion and error recovery; accurately limit the live-sync claim to X/YouTube. |
| 7. Analytics — all 4 tabs | KEEP + FIX | Keep source ledger, imports and revenue provenance. Distinguish missing measurements, preserve currencies, and follow async sync to completion. |
| 8. Settings | KEEP + FIX | Keep workspace/access/usage here and brand/AI administration in their owners. Add independent load/error/retry states. |
| 9. Admin — Overview, Providers, Routing, Activity, Missions | KEEP + FIX | Multi-provider capability routing already exists. Clarify disabled routes, historical health and failed activity loads. Keep Missions under its current admin gate. |
| 10. Platform — Overview, Signups, Clients, Standards, Patterns, Library, Admins | KEEP + FIX | Keep separate platform authority and audited lifecycle actions. Add continuation for capped lists and expose the existing platform provider-availability control. |

## Next vertical slice: Publishing / generation reliability

All findings below were already present before this audit. Preserve existing approval, Context Gateway, AIRouter, task and content ownership.

| ID | Priority / confirmed defect | Evidence | Smallest completion |
| --- | --- | --- | --- |
| PUB-01 | P1: VIEWER can start ordinary generation and delete its tracking row | `Marketing_backend/apps/gemini/views.py:36,183`; isolated VIEWER request returned 202 and created a TaskRun; DELETE returned 204 | Existing Editor role on all generation mutation entry paths; remove generic model mutations; test creative modes and route aliases. |
| PUB-02 | P1: disabling an account does not stop queued publishing | `Marketing_backend/apps/publishing/services.py:66,82`; disabled account still invoked mocked adapter | Re-check account readiness, publishing enablement and workspace execution authority immediately before dispatch, with honest terminal/blocked state. |
| PUB-03 | P1: copy-only output can be labelled a completed poster with no asset | `apps/context/services/generation.py:523`; `apps/gemini/tasks.py:417,507`; isolated image failure produced COMPLETED plus null asset ID | Preserve copy and expose capability failure; reuse existing image retry rather than recreating everything or accepting arbitrary asset URLs. |
| PUB-04 | P1: frontend failure is not authoritative about pending task retry | `Marketing_Frontend/src/routes/_hub.publishing.tsx:923,1152`; `apps/jobs/backend.py:144` | Expose retry-pending versus exhausted/terminal state; keep polling owned retries; allow a new attempt only after definitive failure. |
| PUB-05 | P1: a rejected publish leaves the approved-content lock in the new-content form | `_hub.publishing.tsx:870,880` | Stay in publish setup with selections/content intact on failure; reset only after success or explicit new content. |
| PUB-06 | P2: history serialization grows with every job | `apps/publishing/views.py:32`; `serializers.py:6`; isolated read measured 6 queries for 1 job versus 54 for 25 | Select related content and prefetch item connections; constant query-budget test. |

Live Studio check: templates are NOT selected automatically. Its explicit template choice remains per-content, and missing selection is rejected before generation. The Create button does enable prematurely after the catalogue loads; that is an affordance fix, not evidence that the old automatic-template rule returned.

## Content, Engagement and Analytics backlog

| ID | Priority / defect | Evidence / completion |
| --- | --- | --- |
| CON-01 | P1: failed Content load appears as an empty library | `_hub.review.tsx:133,172,465`; keep unknown/stale rows, explicit error and retry; reject malformed lists. |
| CON-02 | P2: blank/lazy/failed preview gives no recovery clue | `_hub.review.tsx:489`; live blank media area confirmed, permanent asset failure NOT established; add visible loading/failure state and item-specific preview name. |
| CON-03 | P2: Content sidebar / Review heading / invisible Library vocabulary; status selection is visual-only | `_hub.tsx:80`, `_hub.review.tsx:389,441`; mobile selected Rejected remains off-right; align names and expose/scroll active status. |
| ENG-01 | P2: failed inbox load becomes zero conversations and stale errors persist | `_hub.growth.tsx:146,329,359`; use unknown/stale/error states and clear errors on a successful retry. |
| SYNC-01 | P2: queued analytics/inbox sync reloads only once, before completion | `_hub.analytics.tsx:201`, `_hub.growth.tsx:156,190`; track sync run to terminal and refresh without user guessing. |
| ANA-01 | P1: unmeasured metrics are called zero; mixed-currency revenue is labelled USD | `_hub.analytics.tsx:129,329,453`; `apps/analytics/views.py:65,430`; represent missing data explicitly and display/group money by source currency, with no implied conversion. |

## Settings, Admin and Platform backlog

| ID | Priority / defect | Evidence / completion |
| --- | --- | --- |
| ADM-01 | P1: re-enabled provider has disabled routes that still look selected/clean | `apps/ai/views.py:162`; `ai-providers-panel.tsx:239,1379`; show disabled membership and offer explicit re-save. Do not silently reactivate routing. |
| ADM-02 | P2: historical health survives credential/model changes as Connected/Healthy now | `apps/ai/serializers.py:170`; `ai-providers-panel.tsx:682,1021`; invalidate on config changes; show last-check time/result. |
| ADM-03 | P2: activity fetch errors become zeros/empty; recent activity fetches all history | `ai-providers-panel.tsx:254,1449`; use unavailable state and existing opt-in pagination, not client slicing of all history. |
| SET-01 | P2: Settings load failures resemble missing permissions, perpetual loading or blank usage | `_hub.settings.tsx:89,177`; `usage-panel.tsx:49`; independent retryable settings/identity/usage state. |
| PLAT-01 | P2: Signups caps at 200; Standards, Patterns and Library cap at 500 with no continuation | `apps/platform/views.py:150`, `views_universal.py:138,429`, `views_patterns.py:50`; reuse Clients pagination and server-side filters/counts. |
| PLAT-02 | P2: existing global provider availability control has no console UI | `apps/platform/views_controls.py:345`; expose the audited platform-only control, not another provider configuration system. |

Brand Master backend follow-ups remain in `BRAND_MASTER.md`: provenance-changing PATCH/confirmation semantics, raw LearningEvent creation, GET-time provisioning and complete Needs-review aggregation. Social OAuth and audit follow-ups remain in `SOCIAL_ACCOUNTS.md`. These are not erased by this ledger.

## Live configuration observations — not automatically changed

- The inspected selected client has one enabled AI provider and routes for 6 of 9 capabilities. Video, public-web research and engagement reply capabilities are reported unrouted.
- Multi-provider selection and round-robin routing are present in the live Admin interface and implemented in `apps/ai/router.py`. One enabled provider does not supply redundancy; this is separate from a missing routing implementation.
- Platform health currently reports real failed Knowledge/Inspiration work. No privileged repair, publish, approval, provider toggle, sync or paid generation was triggered during the audit.

## Evidence and release gate

- Main Hub screens captured on desktop and mobile; all eight Brand Master tabs, four Content statuses, four Analytics tabs, five Admin tabs and seven Platform pages opened read-only. Captures `01`–`44` are deployed-reference evidence, not screenshots of branch changes.
- First-pass inspection is not exhaustive mutation/accessibility/device/load testing. Platform client detail and all data-filled edge states remain deeper checks.
- Full backend regression: PASS — 1,264 tests, zero failures, 63.622 seconds. TypeScript: PASS. Production frontend build: PASS. Changed Social Accounts lint: PASS. Diff check: PASS.
- Full frontend source lint: FAIL — 18,979 formatting errors and 14 warnings, including pre-existing CRLF/Prettier failures in untouched files. No mass formatting or rule disabling was used to disguise the result.
- Post-change authenticated browser validation: NOT VERIFIED. No merge, push or deploy was performed.
- Release status: NOT READY for complete-product sign-off. Next safe execution unit is PUB-01 through PUB-06, with focused entry-path tests; keep the rest in order rather than launching another rewrite.
