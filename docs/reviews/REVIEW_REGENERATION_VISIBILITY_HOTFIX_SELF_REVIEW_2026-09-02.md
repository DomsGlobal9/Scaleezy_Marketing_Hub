# Review Regeneration Visibility Hotfix — Immutable Self-Review

Date: 2026-09-02
Result: READY

- PASS — Review quietly reloads content while any card has `layout_config.regenerating=true` and stops after the marker disappears. Evidence: bounded recursive timeout in `_hub.review.tsx` with cleanup on state change/unmount.
- PASS — polling does not overlap requests, trigger the page-wide loading state, or emit repeated background error toasts. Evidence: each next timeout is scheduled only after `await load(true)` completes; quiet mode skips loading/toast mutations.
- PASS — edit submission, learning capture, revision creation, worker routing, and content lifecycle contracts are unchanged.
- PASS — TypeScript check passed (`tsc --noEmit`).
- PASS — affected-file ESLint passed.
- PASS — production frontend build passed for client, SSR, and Nitro bundles.
- PASS — full backend regression passed (1,170 tests), including revision-regeneration coverage.
- N/A — no API, schema, tenancy, RBAC, provider routing, billing, publishing, or credential change.

