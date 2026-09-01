# Production Closure — Immutable Self Review

## Reviewed delta

- Base: `cdb34ba9`
- Branch: `feat/production-closure`
- Contract: `docs/reviews/PRODUCTION_CLOSURE_PREFLIGHT_2026-09-01.md`
- Scope: real carousel and video creation through the frozen Context Gateway,
  `AIRouter`, durable storage, asynchronous request state, content persistence,
  and Publishing preview/editor.

## Requirement evidence

| ID | Verdict | Evidence |
|---|---|---|
| PC-001 | PASS | `ProductionClosureTests.test_video_settings_route_to_video_and_persist_a_durable_video_asset` proves VIDEO is selected by capability and receives the provider-neutral brief. |
| PC-002 | PASS | The same test proves duration, aspect, style and script survive API → request row → worker → VIDEO dispatch. |
| PC-003 | PASS | The VIDEO result is copied into workspace storage and persisted as a `MarketingAsset.AssetType.VIDEO` with MIME type, duration and durable URL. |
| PC-004 | PASS | `test_carousel_generates_and_persists_every_ordered_slide` proves one IMAGE dispatch per ordered slide and ordered `ContentItem.slides`. |
| PC-005 | PASS | The carousel test proves durable slide URLs are returned in result metadata and persisted on the content item; the frontend renders those URLs. |
| PC-006 | PASS | `test_missing_video_route_fails_without_a_fake_result`, `test_failed_carousel_retry_reuses_completed_copy_and_slides`, and `test_worker_persistence_failure_never_claims_completed` prove required failures remain FAILED with no fabricated result. |
| PC-007 | PASS | Full 995-test backend regression is green; targeted frontend typecheck/lint and production build are green. |
| PC-008 | PASS | Full tenant/RBAC/approval regression is green; new slide retry is reached through the existing workspace-scoped content viewset and only accepts DRAFT carousel content. |

## Adversarial review

| Attack path | Verdict | Evidence |
|---|---|---|
| Provider media points to private infrastructure | PASS | `_public_media_url` uses the shared public-HTTPS validator, every redirect target is revalidated before a request, and `test_private_provider_media_url_is_rejected_before_download` proves loopback rejection. |
| Provider sends an unbounded body | PASS | `_download_generated_media` streams with 20 MB image / 250 MB video caps and rejects both oversized declared and streamed bodies. |
| Carousel partially fails | PASS | Successful slides and copy are checkpointed; request remains FAILED; retry dispatches only the missing slide. |
| Worker loses storage after provider spend | PASS | Persistence errors move the request to FAILED and create no result; COMPLETED is written only after the durable draft and result exist. |
| Polling leaks or repeatedly transfers full prompt/reference image | PASS | `GeminiGenerationRequestSerializer` returns explicit safe fields plus compact progress and excludes `prompt_data`; asserted by the retry/progress test. |
| Provider identity becomes product logic | PASS | Generation branches only by `Capability`; no vendor name, model default or credential appears in production selection logic. |
| Provider is silently defaulted | PASS | No provisioning or catalogue behavior changed; a missing VIDEO/IMAGE route fails visibly. |

## Gates

- PASS — backend full regression: **995 tests, 0 failures, 0 errors**.
- PASS — frontend Prettier check for `_hub.publishing.tsx`.
- PASS — frontend TypeScript: `tsc --noEmit`.
- PASS — targeted frontend ESLint for `_hub.publishing.tsx`.
- PASS — frontend production build (client, SSR and Nitro/Cloudflare output).
- PASS — `manage.py makemigrations --check --dry-run`: no changes detected.
- PASS — `manage.py check`: no errors. A test-only `SECRET_KEY` produced the
  expected development-placeholder warning; no repository or deployment
  setting was changed.
- PASS — `git diff --check`.

## Boundary confirmation

- PASS — PR0–PR7 ownership and schemas remain intact.
- PASS — no migration.
- PASS — no credential or provider default.
- PASS — existing publishing platform adapters were not changed.
- N/A — native multi-asset carousel publishing and format-specific Instagram,
  Facebook and LinkedIn video publishing remain a separate publishing slice,
  as frozen in the preflight. The UI now says slides are generated and saved,
  not falsely that native multi-slide publishing is already complete.

## Final verdict

**READY** — zero FAIL and zero NOT VERIFIED within the frozen Production
Closure scope.
