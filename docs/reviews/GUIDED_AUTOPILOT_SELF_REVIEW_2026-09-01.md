# Guided Autopilot and Research — Immutable Self-Review

Date: 2026-09-01
Branch: `codex/guided-autopilot`
Contract: `GUIDED_AUTOPILOT_PREFLIGHT_2026-09-01_V2.md`

## Outcome

Scaleezy now derives editable Autopilot and Growth Engine starting text from the selected client's Brand Master. The common path is one explicit action; advanced controls remain available but are no longer prerequisites. The change does not schedule or publish content automatically.

## Requirement evidence

| Requirement | Result | Evidence |
| --- | --- | --- |
| Brand-aware Autopilot defaults | PASS | `buildGuidedPolicyText()` uses the current brand's name, industry, audience, products/services, tone, tagline, description and CTA. Frontend typecheck and production build pass. |
| Preserve user edits | PASS | `_hub.autopilot.tsx` fills only blank fields during same-client reloads. `Refill from Brand Master` is the only explicit overwrite. Existing workspace switching performs a full document reload, preventing sibling-workspace state reuse. |
| One-action first run | PASS | `createAndRun()` creates through the existing policy endpoint and triggers only the ID returned by that response. `test_admin_can_create_then_trigger_a_guided_policy` passes. |
| Repeat one-action use | PASS | Guided names are capped at 120 characters and advanced to the next available suffix, so a second run cannot reuse the workspace/brand/name unique key. |
| Honest partial failure | PASS | Create failure and trigger-after-create failure have separate messages; a saved policy remains visible and retryable. |
| Honest durable-queue state | PASS | `queue_run()` records `FAILED`, `QUEUE_ENQUEUE_FAILED`, completion time, a failed finish step and no task ID before returning `503`. `test_trigger_records_queue_enqueue_failure_honestly` passes. |
| Queue retry remains usable | PASS | Queue-enqueue failures are excluded from the daily-generation allowance and format rotation. The queue-failure test retries a limit-1 policy successfully on the same day. |
| Brand-aware unrestricted research | PASS | `buildGuidedResearchText()` supplies an editable query and focus areas while preferred sources remain blank, preserving unrestricted public-web discovery. |
| No hidden publishing | PASS | No publishing endpoint or scheduler is called. Existing Autopilot review/publish gate tests remain green in the focused suite and full regression. |
| Tenant and RBAC boundaries | PASS | Existing workspace-scoped policy, run and research endpoints remain authoritative. No permission class, workspace resolver or `X-Workspace-Id` behavior changed. Focused RBAC and tenant tests pass. |
| Frozen architecture preserved | PASS | No schema, migration, Context Gateway, AIRouter, billing, credential, review or publishing ownership change. |

## Verification evidence

- PASS — `manage.py test apps.autopilot --verbosity 1`: 10 tests, zero failures.
- PASS — baseline full Django regression before the final retry-only hardening: 1,080 tests, zero failures. After the three adversarial fixes and latest-main fast-forward, the complete affected Autopilot suite was rerun (10 tests, zero failures); a second full regression was intentionally not duplicated.
- PASS — `manage.py check`: zero issues.
- PASS — `manage.py makemigrations --check --dry-run`: no changes detected.
- PASS — TypeScript `tsc --noEmit`.
- PASS — targeted ESLint for `_hub.autopilot.tsx`, `_hub.growth.tsx` and `guided-workflows.ts`.
- PASS — frontend production build, including client, SSR and Nitro output.
- PASS — `git diff --check` (line-ending conversion notices only; no whitespace errors).
- N/A — live visual comparison was not a release gate for this functional slice; the selected in-app browser could not initialize on the host, so no screenshot-based claim is made. Deployment smoke verification remains a separate post-deploy activity.

## Adversarial paths

- PASS — viewer cannot create or trigger a policy (existing focused test).
- PASS — a different workspace cannot trigger the policy (existing focused test).
- PASS — automatic publishing remains rejected (existing focused test).
- PASS — generated work still enters the governed draft/review path (existing focused test).
- PASS — queue failure cannot leave a run falsely shown as queued (new focused test).
- PASS — a queue failure does not consume the policy's only daily run, and the immediate retry receives a task ID (new focused test).
- PASS — repeated guided creation advances to an available, API-valid mission name instead of hitting the unique constraint.
- PASS — selected-client change cannot retain another client's guided draft because workspace switching reloads the document and Growth keys the research panel by brand ID.

## Release notes

- The branch was fast-forwarded to latest `origin/main` (`b8d4b650`) before final verification and contains only the guided-workflow slice plus its evidence files on top.
- `.claude/` is user-owned and intentionally excluded.
- The feature is safe to deploy after integration with the latest main and the normal deployment pipeline.
