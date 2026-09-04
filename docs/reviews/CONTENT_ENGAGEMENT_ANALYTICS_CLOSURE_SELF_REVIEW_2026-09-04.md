# Content, Engagement and Analytics closure evidence

Immutable scoped evidence for `TAB_CLOSURE_ALL_GAPS_PREFLIGHT_2026-09-04.md`.
Scope: CON-01..03, ENG-01, SYNC-01, ANA-01. No commits, deployments,
live provider syncs, or paid writes were performed.

## Implemented dependency paths

- Content list -> strict bare/paginated parsing -> retained last successful state,
  live error/retry -> actual empty state only after successful load. Content naming,
  pressed status buttons, selected-button scrolling, item-specific image previews,
  visible loading/error/retry and labeled review inputs remain in the existing layout.
- Engagement list/accounts/replies/leads/syncs -> strict validation -> retained state
  and recoverable errors. Header scope accurately states X mentions / YouTube comments.
- Engagement and Analytics sync -> scoped domain run API -> existing TaskRun ownership
  -> queued/running/retry-pending/nonterminal versus terminal outcome -> polling and
  owned-data refresh. Dispatch failures persist FAILED and return HTTP 503. Manual
  engagement retry serializes ownership checks and cannot overwrite fast completion.
- Analytics intake -> explicit measured-field provenance -> unavailable values and
  coverage-aware totals. Explicit zeros and legacy positive evidence remain measured.
  Currency summaries and campaign returns stay in source currency; no implicit FX.
  New intake rejects fractional counts, non-finite money and malformed currency codes.

## Verification

- PASS: `manage.py test apps.analytics apps.engagement --verbosity 0`: 39 tests passed;
  Django system check reported zero issues. Includes 16 new focused tests in
  `apps/analytics/test_tab_closure.py` and `apps/engagement/test_sync_truth.py`.
- PASS: explicit zero versus omitted/null/blank intake, server-owned availability
  provenance, legacy positive evidence, platform-reported zero, partial total coverage,
  mixed currencies and same-currency ROI tested.
- PASS: cross-workspace sync-detail isolation, brand-scoped sync list, active background
  retry refusal, terminal owner completion, dispatch exceptions, and fast-worker
  completion preservation tested.
- PASS: `node --experimental-strip-types --test tests/list-response.test.mjs`: 3/3.
  Malformed/missing/partially malformed responses cannot become empty lists.
- PASS: `npx tsc --noEmit` after final frontend edits.
- PASS: targeted ESLint for the three routes, list-response.ts, sync-run.ts and the
  new frontend test file, after targeted formatting.
- PASS: scoped `git diff --check` (only informational line-ending warnings).
- N/A: schema migrations; no model/schema changes.
- NOT VERIFIED by this slice: full shared backend regression, production frontend
  build, and browser interaction replay. Root owns these integration gates; this
  scoped evidence does not claim final whole-product readiness.

## Independent neighboring review

Read-only review of the generation/publishing changes kept the explicit-template
gate, stable request-ID replay, task-owner polling and failed-publish selections.
Two findings were sent directly to that owner: an image-only retry must not announce
success when its returned media remains FAILED; replay HTTP 401/403 must not discard
an already accepted generation ID whose background ownership remains uncertain.

The React quality checklist guided keyed item media state, stable polling callbacks,
non-overlapping timers and truthful asynchronous status handling.
