# Brand Master Tab Visibility — Immutable Self Review

Date: 2026-08-31  
Branch: `codex/fix-brand-master-tabs`  
Scope: presentation-only correction for mounted Brand Master tab panels.

## Evidence

- PASS — The production defect was reproduced before editing: selecting Knowledge changed the URL to `?tab=knowledge` and made its Radix trigger active, while inactive Brand Basics and Products panels both computed to `display: block`.
- PASS — Inactive mounted panels are now hidden. Evidence: both `forceMount` usages in `_hub.brand-master.tsx` carry `data-[state=inactive]:hidden`.
- PASS — Draft preservation is unchanged. Evidence: `forceMount` remains on Brand Basics and Products & Audience, and `useBrandSettings` was not modified.
- PASS — The production bundle contains the correction. Evidence: the built Brand Master JavaScript contains the new class twice, and generated CSS contains `[data-state=inactive]{display:none}` for that variant.
- PASS — TypeScript gate: `tsc --noEmit` exited 0.
- PASS — Targeted semantic lint: ESLint on `_hub.brand-master.tsx` exited 0 with the repository's pre-existing CRLF-only Prettier rule disabled. The unmodified rule reports CRLF on 1,284 pre-existing lines and is recorded as baseline, not attributed to this two-line change.
- PASS — Production build: Vite/TanStack/Nitro build completed successfully.
- PASS — Patch hygiene: `git diff --check` exited 0.
- PASS — React best-practices review: no hook, component boundary, data fetching, accessibility, or bundle-loading behavior changed; native Radix tab semantics remain authoritative.
- N/A — Backend regression, migrations, tenant/RBAC, provider, publishing, storage, and lineage gates: no backend or data-contract code changed.

## Adversarial checks

- PASS — Direct URL selection still uses the existing validated query and controlled tab value.
- PASS — Clicking, history, reload, and deep-link behavior are untouched; only inactive-panel visibility changed.
- PASS — Hidden panels remain mounted, so incomplete local product rows are not discarded when switching tabs.
- PASS — Only the two intentionally forced panels receive the visibility class; shared Tabs behavior and all other screens remain unchanged.

## Readiness

Zero FAIL and zero NOT VERIFIED items. Ready to deploy and verify once against the live DOM after the frontend deployment completes.
