# Review Regeneration Visibility Hotfix — Immutable Preflight

Date: 2026-09-02
Scope: make Review automatically observe completion of an already queued edit regeneration.

## Dependency graph

Request edits → revision with `layout_config.regenerating` → background worker → marker cleared → content list → Review card.

## Requirements and evidence plan

- Review must refresh quietly while any revision is regenerating and stop after the marker clears.
- Polls must not overlap, flash the page-wide loading state, or repeat error toasts during a transient outage.
- Review, learning, generation, and content lifecycle contracts remain unchanged.
- Evidence: TypeScript check, production frontend build, and backend regression gate.

## Boundaries

- N/A — no API, schema, tenancy, RBAC, provider routing, billing, or publishing change.
- N/A — this does not make provider execution itself synchronous or claim an artificial completion time; it removes stale UI state.

