# Tab-by-Tab Product Closure — Immutable Execution Preflight

## Identity

- Workstream: live Scaleezy tab-by-tab product closure
- Branch: `codex/tab-by-tab-product-closure`
- Base: `5facc0e9dbab517c05879537bf52e382f3a19db7`
- Authorized scope: inspect every visible Hub and Platform Console tab against the current architecture and live behavior; classify each surface as KEEP, FIX, MERGE, REMOVE, MISSING or BLOCKED; implement only contained fixes that improve clarity, accessibility, responsiveness, truthful state, latency or completion of an already-owned flow.
- Explicitly out of scope: tenant/RBAC redesign, Brand Brain ownership changes, Context Gateway or AIRouter bypasses, publishing-architecture replacement, destructive migrations, credential-policy changes, and speculative new modules.

## Audit order

1. Overview
2. Brand Master and its inner tabs
3. Social Media Accounts
4. Publishing / Create Studio
5. Content / Review / Library
6. Engagement
7. Analytics
8. Settings
9. Admin / AI configuration
10. Platform Console and its inner tabs

## Per-tab evidence contract

Every tab decision requires all of the following:

- Current live desktop capture and visible-state inspection
- Mobile reflow check for the primary state
- Route/component ownership and API dependency trace
- Tenant/workspace boundary check for every displayed or mutated record
- Honest loading, empty, error and success states
- Real control check: no dead buttons, hidden routes or fake completion
- KEEP/FIX/MERGE/REMOVE/MISSING/BLOCKED decision with a user-facing reason

## Delivery method

- Complete one vertical tab slice before changing the next.
- Reuse existing components, endpoints and architecture owners.
- Prefer small copy, accessibility, query or wiring fixes over structural rewrites.
- Run focused tests during each slice; run the full backend and frontend gates once before release.
- Do not merge or deploy until the consolidated closure set has zero known P0/P1 regressions.

## Stop conditions

STOP before any change that would alter PR0–PR7 architecture ownership, weaken workspace isolation, fabricate state, duplicate an existing module, introduce a provider-specific product flow, or change billing/publishing/security semantics.

