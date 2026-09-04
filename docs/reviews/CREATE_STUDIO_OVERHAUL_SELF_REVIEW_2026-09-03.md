# Create Studio Overhaul — Evidence Gate

## Build identity

- Branch: `codex/create-studio-overhaul`
- Base: `1284dba6`
- Final release commit: this document ships with the release delta; the assigned SHA is reported in the deployment handoff
- Reviewer mode run: YES — three parallel adversarial passes, integration with `origin/main` at `3429d6a1`, and the final merged gate
- Status: **READY**

## Requirement traceability

| ID | Status | Evidence at this snapshot | Final note |
|---|---|---|---|
| CS-01 no Brand/default template | PASS | layout preference removed from compiler/context/generation fallback; serializer read-only; focused layout tests | Reconfirm after final diff |
| CS-02 explicit mode | PASS | resolver/API mode matrix and frontend TypeScript checks | Reconfirm build after final fixes |
| CS-03 exact poster template | PASS | template is poster-only; missing/invalid layout tests pass; failed composition keeps the paid draft visible and non-retryable | Full suite green |
| CS-04 tenant/lifecycle-safe references | PASS | queued jobs and regeneration re-resolve live workspace/brand-scoped references; revoked Brand and Platform references stop before provider spend | Focused regeneration test and full suite green |
| CS-05 revision provenance | PASS | regeneration/request-edits focused tests passed | Re-run after reference revalidation fix |
| CS-06 all entry flows reachable | PASS | Create Studio exposes all three explicit modes, transient upload, saved references, and a poster-only `Save reference & create poster` upload/public-URL path | Final typecheck and production build green |
| CS-07 honest, non-duplicating failure states | PASS | paid result remains COMPLETED when only composition fails; persistent UI warning links to Poster Studio; stuck-job sweep preserves result | Focused tests and full suite green |

## Dependency verification

| Dependency | Status | Evidence |
|---|---|---|
| Auth → workspace → role | PASS | existing scoped viewsets/permissions retained; focused API suite passed |
| Workspace → brand/reference | PASS | resolver scopes Brand Inspiration to workspace + brand |
| Input → validation | PASS | explicit mode, incompatible-source, required-template/reference tests |
| Validation → durable job | PASS | async generation tests at pre-fix snapshot |
| Job → honest state | PASS | composition failure is a completed generation with `composition.status=FAILED`; retry cannot repeat provider spend |
| State → UI | PASS | poller returns the preserved result and Create Studio renders a persistent remediation warning |
| Review → revision | PASS | creative direction carry, explicit template preservation and legacy-layout tests |
| Revocation → new provider call | PASS | revoked Brand/Platform reference regeneration returns `REFERENCE_UNAVAILABLE`; all provider mocks remain uncalled |
| Provenance/lineage | PASS | request-edits carries creative direction; manual Poster Studio render stamps the explicit catalogue choice and preserves the previous direction as source lineage |

## Evidence already established

- Full backend: **1,182 tests passed at the prior code state**. This is historical evidence only and does not clear the final delta.
- Focused backend: **78 tests passed** in an earlier changed-module gate.
- Combined focused backend: **144 tests passed** across async generation, creative command, create-from-inspiration, layouts and Autopilot at the pre-final-fix snapshot.
- Additional review/request-edits gate: **17 tests passed**.
- Frontend typecheck: `tsc --noEmit` passed at the pre-final-fix snapshot.
- Frontend build: passed at the pre-final-fix snapshot.
- Semantic ESLint on touched frontend files: zero errors; one existing fast-refresh warning. Windows CRLF caused Prettier-only noise and is not semantic proof.
- Migration check: `makemigrations --check --dry-run` → `No changes detected`.
- Django check: passed with only the expected local placeholder `SECRET_KEY` warning when local check-only environment values were supplied.
- Diff hygiene: `git diff --check` passed.

## Mandatory final post-fix gates

- [x] Focused backend generation/layout/content/Autopilot/guardrail tests — 162/162 merged contract tests passed; final backend semantic audit set 88/88 passed
- [x] Revoked-reference regeneration and legacy queued-reference tests — passed; provider spend asserted zero after revocation
- [x] Selected-template composition failure/poller no-duplicate-spend test — passed in the final full suite
- [x] Poster Studio explicit-choice provenance test — passed in the final full suite
- [x] Frontend typecheck — exit 0, no diagnostics after the final UI fix
- [x] Frontend production build — Vite client, SSR and Nitro/Cloudflare builds completed successfully after the final UI fix
- [x] Final full post-merge backend regression with a valid test `FERNET_SECRET_KEY` — **1,241 tests passed, 0 failures in 56.556s**
- [x] `makemigrations --check --dry-run` and `manage.py check` — no changes detected; check passed with only the expected local placeholder-key warning
- [x] Git diff hygiene — `git diff --check` exit 0; only harmless Windows LF→CRLF notices
- [x] Confirm `.claude/settings.local.json` is excluded from the commit — release staging uses explicit product/docs paths only
- [ ] Manual/browser flow — **N/A for this automated release gate:** the selected in-app browser could not initialize because its host kernel assets path is unavailable (`os error 3`). No alternate browser was substituted. A live authenticated smoke remains the immediate post-Render check.

## Known gaps / deviations

- No deferred product gaps are approved in this scope.
- Compatibility database column retention is intentional and non-functional; destructive removal is deferred to a separately approved migration.
- The in-app browser host failure prevents an automated visual/authenticated smoke in this workspace; this is tooling, not an application failure. Build/type/API gates are green and a live smoke follows deployment.

## Readiness

- PASS: 12
- N/A: 1
- FAIL: 0
- NOT VERIFIED: 0

**READY = YES.** The only N/A is the unavailable in-app-browser host; no product or security gate is waived.
