# Performance, Monetization and Governed Autopilot — Immutable Self Review

## Build identity

- Base: `76d42308`
- Branch: `feat/performance-autopilot-closure`
- Contract: `docs/reviews/PERFORMANCE_AUTOPILOT_PREFLIGHT_2026-09-01.md`
- Reviewer mode run after implementation: YES

## Requirement traceability

| Req ID | Status | Evidence | Notes |
|---|---|---|---|
| PA-001 | PASS | `AnalyticsGrowthTests.test_any_platform_metric_can_be_imported_with_lineage` and `test_projection_uses_latest_cumulative_snapshot_not_sum`. | Post-level observations preserve source, freshness, content, campaign and platform lineage without double-counting cumulative snapshots. |
| PA-002 | PASS | X `test_fetch_post_metrics_normalizes_public_metrics` and YouTube `test_fetch_video_metrics_normalizes_public_statistics`. | Live adapters expose bounded provider data; any other platform remains available through the auditable import path. |
| PA-003 | PASS | `test_metric_import_is_idempotent` and database uniqueness on source/external observation identity. | Duplicate ingestion does not duplicate facts or learning events. |
| PA-004 | PASS | `test_revenue_event_is_idempotent_and_converts_lead`. | Leads and revenue are durable, tenant-owned facts with idempotent attribution. |
| PA-005 | PASS | Analytics dashboard queries durable observations and displays freshness/source, content/provider/layout lineage, leads and revenue. Frontend TypeScript, ESLint and production build pass. | No synthetic success metric is returned. |
| PA-006 | PASS | Performance sync emits only `PERFORMANCE_OBSERVED` with `NEUTRAL`; `UniversalAggregationWeightTests.test_judgment_counts_and_bookkeeping_does_not` is included in the 1,039-test regression. | Performance bookkeeping cannot silently become human-confidence weight. |
| PA-007 | PASS | `AutopilotTests.test_admin_can_trigger_an_enabled_policy` and `test_run_queues_existing_generation_then_waits_for_review`. | The policy queues the existing generation task, which continues through Context Gateway/AIRouter ownership. |
| PA-008 | PASS | `test_auto_publish_is_not_an_available_mode`, `test_emergency_stop_stops_pending_work`. | This release creates drafts or review items only; it cannot publish externally. |
| PA-009 | PASS | `test_cross_tenant_brand_and_channel_are_rejected` and `test_cross_tenant_channel_is_rejected_on_direct_orm_path`. | API, ORM, M2M and admin entry paths preserve tenant boundaries. |
| PA-010 | PASS | `test_viewer_cannot_create_or_trigger_policy` and `test_django_admin_is_observability_only`. | Workspace admins govern policies in the product; Django staff cannot bypass that control surface. |
| PA-011 | N/A | `AutopilotPolicy.Cadence` exposes only `MANUAL`; no scheduler registration exists. | Recurring AI generation and spend were deliberately excluded because they need explicit consequential-action authorization. |
| PA-012 | N/A | `AUTO_PUBLISH` is not a valid mode and is rejected by test. | External auto-publishing was deliberately excluded; existing publishing ownership is unchanged. |

## Dependency verification

| Dependency | Status | Evidence |
|---|---|---|
| Auth → workspace | PASS | Workspace-scoped viewsets plus non-member and viewer denial tests. |
| Workspace → brand/account/content | PASS | Serializer querysets, model validation, M2M signal and cross-tenant tests. |
| Input → validation | PASS | Non-negative database constraints, serializer validation and bounded platform normalization. |
| Validation → persistence | PASS | Performance observations, sync runs, leads, revenue events, policies, runs and steps are durable models with migrations. |
| Persistence → service/job | PASS | Metric sync tasks and existing `generate_content` task are used; no second job stack exists. |
| Job → honest state | PASS | Failed sync/generation states remain FAILED; incomplete generation remains WAITING_GENERATION/WAITING_REVIEW. |
| State → downstream consumer | PASS | Analytics projections, neutral learning events and admin run ledger consume durable state. |
| API → UI | PASS | Analytics and Autopilot routes compile, typecheck, lint and appear in the admin navigation. |
| Failure → visible state | PASS | Sync runs and autopilot runs persist error code/message and the UI renders them. |
| Provenance/lineage | PASS | Metric source, external ids, observed time, content/campaign/provider/layout and revenue links are preserved. |

## Test evidence

- PASS — changed-module/security tests: **34 tests, 0 failures, 0 errors**.
- PASS — full backend regression after production implementation: **1,039 tests, 0 failures, 0 errors**.
- PASS — frontend Prettier on all changed route files.
- PASS — frontend TypeScript: `tsc --noEmit`.
- PASS — targeted frontend ESLint on Analytics, Autopilot and hub navigation.
- PASS — frontend production build: client, SSR and Nitro/Cloudflare output complete.
- PASS — `manage.py makemigrations --check --dry-run`: no changes detected.
- PASS — `manage.py check`: no errors; only the expected local placeholder `SECRET_KEY` warning under explicit SQLite fallback.
- PASS — local Vite preview served `/login` with HTTP 200.
- PASS — `git diff --check`.

## Known gaps

- Recurring policy scheduling remains deferred until explicit authorization for persistent AI generation/spend.
- External auto-publish remains deferred until explicit authorization and an approved per-client publishing policy; existing publishing remains available through its current review/schedule flow.
- Live metric reads currently ship for X and YouTube. Every other platform is supported through unrestricted, source-labelled audit import until its approved API adapter is added.
- CRM/webhook delivery is not claimed. Leads and attributed revenue are durable and ready for a later explicitly selected CRM connector.

## Deviations

- The preflight originally mapped scheduled execution and auto-publish entry paths. Safety review narrowed this release to explicit admin-triggered, draft/review-only operation. No hidden scheduler or publisher workaround was introduced.

## Readiness

- PASS count: 20
- N/A count: 2
- FAIL count: 0
- NOT VERIFIED count: 0

**READY within the narrowed, review-gated scope. Slice D is complete. Slice E's manual governance foundation is complete; recurring generation and auto-publish are explicitly deferred, not represented as delivered.**
