# PR7 Universal Learning — Immutable Self Review

Branch: `codex/pr7-universal-learning`  
Base: `main` at `6a50325`

## Scope evidence

- PASS — Deterministic compilation from all CLIENT workspaces, with no consent/eligibility filter and no minimum contributor floor. Evidence: `AggregationTests.test_single_client_is_emitted_and_legacy_consent_flag_is_ignored`.
- PASS — INTERNAL workspaces are excluded and contributor/supporting-brand counts are real distinct counts. Evidence: `AggregationTests.test_internal_workspaces_are_excluded_and_counts_are_real`.
- PASS — Derived rows are reproducible after deletion. Evidence: `AggregationTests.test_compile_and_delete_recompile_are_deterministic`.
- PASS — Brand-specific literals are rejected from compiled patterns. Evidence: `AggregationTests.test_brand_specific_literal_is_not_compiled`.
- PASS — Published patterns reach provider-neutral context at rank 82 with attribution and without contributor IDs. Evidence: `GatewayPatternTests.test_published_pattern_reaches_brief_attributed_without_contributor_ids`.
- PASS — Learned patterns remain weaker than universal standards and every brand-specific authority rank. Evidence: `GatewayPatternTests.test_rank_is_weaker_than_standard_and_every_brand_rank`.
- PASS — A brand position structurally removes the learned pattern before generation. Evidence: `GatewayPatternTests.test_brand_position_structurally_drops_pattern`.
- PASS — Retiring a pattern immediately changes the cache version and removes it from generation. Evidence: `GatewayPatternTests.test_retiring_pattern_invalidates_cached_context_immediately`.
- PASS — List, contributors, publish and retire are PlatformAdmin-only; reads and lifecycle actions are audited. Evidence: `PatternConsoleTests`.
- PASS — Context cache key and persisted generation trace include `learned_pattern_version`. Evidence: `context_gateway.py`, `generation.py`, and gateway retirement test.
- PASS — Management command and database-backed `@task` use the existing worker; request-triggered compile is queued and reports `QUEUED`, never fake completion.
- PASS — Super Admin console exposes compile, evidence depth, contributor lineage, publish and retire. Evidence: production build includes `platform.patterns` route.

## Verification

- PASS — 10 PR7-specific tests: 10/10.
- PASS — Affected regression: 98/98 (`apps.universal`, universal console, Context Gateway).
- PASS — `manage.py makemigrations --check --dry-run`: no changes detected.
- PASS — `manage.py check`: no errors (local placeholder-secret warning only).
- PASS — `tsc --noEmit`: exit 0.
- PASS — production frontend build: exit 0; client, SSR and Nitro bundles produced.
- PASS — `git diff --check`: no whitespace errors.

## Release position

Code gate: PASS. Production merge/deploy: BLOCKED only by the live privacy-policy sentence identified in the approved PR7 contract. The policy text was deliberately not changed without founder-approved wording.
