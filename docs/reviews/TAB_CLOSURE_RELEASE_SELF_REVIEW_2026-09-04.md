# Tab closure release — immutable integration self-review

## Identity and scope

Date: 2026-09-04. Feature branch: `codex/tab-by-tab-product-closure`. Reviewed merge combines contact integration `2816c7cf` and current main `c25bb8cd127d82262d3dbfc669aa75141536a21a` (Claude's merged signup PR24). Governing preflight: `TAB_CLOSURE_RELEASE_PREFLIGHT_2026-09-04.md`.

This release carries the already-approved tab-closure commits plus the integrated legal business name/contact person fields. Preserve earlier immutable reports as historical snapshots. `PRELOADED_BRAIN_VALIDITY_SELF_REVIEW_2026-09-04.md` closes the earlier compiler finding; `BRAND_CONTACT_FIELDS_SELF_REVIEW_2026-09-04.md` records field provenance and actual local save/reload/failure/mobile evidence. No new feature, credential, infrastructure or production-record change is introduced by this merge.

## Conflict resolution and adversarial review

- PASS — Brand fields exist once, with original migration identity, limits 255/150, accessible optional inputs and the existing shared save queue. Administrative contact fields remain outside Brand Brain/learning compilation.
- PASS — Signup queue retains our opt-in pagination, totals, search, loading/retry behavior and upstream legal name/location/contact person/phone details. The pending-count endpoint retains the platform-admin permission boundary. Upstream intake/notification work is preserved.
- PASS — Empty `0007_merge_contact_guardrails` joins both existing 0006 migrations. No field is duplicated, renamed or dropped. The new graph has one leaf and a fresh database migrates successfully.
- PASS — All merge conflict markers resolved; final whitespace check passes. Only resolved frontend files and one upstream signup JSX label received formatting corrections; no lint rule or CI workflow was disabled.
- PASS — Untracked scratch files, client audit screenshots and `.claude/` are excluded from release. The committed contact screenshot uses synthetic local data. No application secrets were added.

## Fresh combined verification

| Gate | Status | Evidence |
| --- | --- | --- |
| Full backend regression | PASS | `manage.py test --noinput --verbosity 1`: 1,376 tests in 133.974 seconds, OK, exit 0; zero system-check issues. Isolated in-memory SQLite with process-only test configuration. |
| Migration drift | PASS | `makemigrations --check --dry-run`: No changes detected. |
| Fresh migration/integrity | PASS | Isolated migrate, createcachetable and `production_integrity --allow-sqlite`: one Brand leaf, physical legal_name/contact_person/guardrails columns, no unapplied migrations, all 27 critical models, database-cache round-trip and system checks verified. Production-only configuration checks deliberately not certified by local DEBUG. |
| Frontend logic | PASS | Existing generation-state and list-response tests: 11/11. |
| Frontend typecheck | PASS | `tsc --noEmit`, exit 0. |
| Frontend lint | PASS | Full ESLint: zero errors, 14 existing warnings. |
| Frontend production build | PASS | Client, SSR and Nitro stages completed, exit 0. |
| Existing browser evidence | PASS for recorded scope | Contact report records real local form/API persistence, Unicode, failed-save retention/retry, clears and 390px layout. This merge preserves that field flow; no new full browser/product/provider certification is claimed. |

## Release acceptance and external verification

READY for normal PR checks/review and merge, with mandatory local FAIL=0 / NOT VERIFIED=0. Remote PR and deployment gates follow this snapshot and must be reported separately, not assumed successful here.

GitHub deployment metadata for current main c25bb8cd showed successful Vercel frontend and Render worker, but failed Render backend. Its exact failure cause is not established without logs. The migration merge is included and locally verified; only a successful backend deployment of the new release SHA will establish release success. Verify the frontend, backend and worker commit/status independently. Public availability alone does not prove a revision is deployed. Paid providers, real publishing/OAuth, notification delivery, production load and every data-filled browser path are not certified by these tests.

The PR-readiness checklist guided preservation of both merge intents and review/check gates. Deployment checks distinguish frontend and worker success from backend success; none may substitute for the other.
