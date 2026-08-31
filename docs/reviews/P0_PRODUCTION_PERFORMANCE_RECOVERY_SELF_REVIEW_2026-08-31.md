# P0 Production Performance Recovery — Immutable Self Review

Date: 2026-08-31

Branch: `codex/p0-performance-recovery`

Base: `878bb0ea`

Scope: Brand Master bootstrap latency, repeated tenant/readiness queries, production database connection reuse, and test-gate cycle time.

## Requirement evidence

- PASS — PERF-001 preserves selected-client isolation while removing duplicate authorization reads. Evidence: cached membership reuse requires the exact workspace id, user id and ACTIVE membership status; any mismatch falls back to the database and fails closed. The complete workspace/onboarding group passed 114/114 tests, including the new zero-query reuse and cross-tenant mismatch cases.
- PASS — PERF-002 evaluates each readiness evidence queryset once. Evidence: `brand_readiness()` stores six counts and reuses them for scoring and the response; the query ceiling test permits at most six `COUNT` statements and passed.
- PASS — PERF-003 provides one selected-workspace Brand Master bootstrap. Evidence: `GET /api/marketing/brand-master/current/` returns the full existing Brand serializer plus the exact existing overview payload; aggregate, lifecycle and context/brand groups passed 106/106 tests.
- PASS — Existing current-brand lifecycle behavior is preserved. Evidence: both old and aggregate endpoints use `get_current_brand()`; pending/rejected/archived regression tests pass. The resolver can create the same approval-aware default brand that the pre-existing `/brands/current/` GET created; no new lifecycle transition was introduced.
- PASS — PERF-004 removes the steady-state frontend waterfall. Evidence: Brand Master performs one aggregate bootstrap and hydrates both force-mounted editors only when the returned brand id exactly matches the target id. Save, refresh, dirty-state and inactive-tab behavior remain intact.
- PASS — Rolling deployment remains compatible. Evidence: only an HTTP 404 from the new aggregate route falls back to the legacy current-brand then overview reads; authentication, tenant, network and server failures are rethrown.
- PASS — PERF-005 reuses healthy PostgreSQL connections. Evidence: production-settings probe returned `django.db.backends.postgresql 37 True`, proving the override, health check and backend; production password hashing remained `PBKDF2PasswordHasher`.
- PASS — Test-only password hashing is isolated. Evidence: `MD5PasswordHasher` is assigned only inside `_RUNNING_TESTS`; the production-settings probe above retained Django's PBKDF2 default. This reduced the complete backend gate from tens of minutes to seconds without changing runtime security.

## Release gates

- PASS — Complete backend regression: all 972 discovered tests passed in eight isolated app groups (90 + 106 + 115 + 117 + 147 + 114 + 115 + 168), zero failures and zero errors.
- PASS — Frontend type check: `npx tsc --noEmit` exited 0.
- PASS — Frontend production build: Vite client, SSR and Nitro/Cloudflare build exited 0.
- PASS — Django system check exited 0. The local placeholder-secret warning is environment-only and absent when a release-gate secret is supplied.
- PASS — Migration drift check: `makemigrations --check --dry-run` exited 0 with `No changes detected`.
- PASS — Patch hygiene: `git diff --check` exited 0.
- PASS — Three independent read-only reviews found no tenant, RBAC, lifecycle, runtime, race, stale-data or architecture regression. One rolling-deploy risk was found and fixed before this review was frozen.

## Adversarial checks

- PASS — A cached membership for workspace A cannot authorize workspace B; exact-id mismatch forces a fresh lookup and returns no data when unauthorized.
- PASS — A caller-supplied `brand_id` query cannot steer the aggregate; the selected workspace returns its own brand and overview.
- PASS — A rejected client receives its existing archived brand and no replacement brand is minted.
- PASS — Preloaded editor data cannot cross brands because hydration requires exact brand-id equality.
- PASS — Failed authentication, authorization, tenant selection, network calls and 5xx responses are not hidden by the deployment fallback.
- PASS — PR0–PR6 ownership remains frozen: no schema, Brand Brain compiler, Context Gateway, AIRouter, publishing, billing, storage or product-state contract changed.

## Readiness

Zero FAIL and zero NOT VERIFIED items. Ready to commit, push, deploy and verify against the live Brand Master request path.
