# PR02_V5_INTAKE.md — Accelerator V5 intake

Follows the shape of `docs/templates/CTO_REWORK_INTAKE_TEMPLATE.md`. This is not
a CTO review response — no review has been received. It records what the V5
execution package changed after PR2 was already implemented and pushed, so the
earlier preflight is not silently treated as still complete (G-009).

`docs/reviews/PR02_PREFLIGHT.md` is left untouched. It was accurate for the
package it was written against.

## Package received
- Package: `SCALEEZY_CLAUDE_ACCELERATOR_V5_PR2.zip`
- PR/head at intake: `marketinghub/merge` @ `d63af0e` (PR2 as first pushed)
- Verdict: none — no review returned. This is an upgraded execution standard.
- New material versus the V4 package:
  - `CLAUDE_FAST_START.md`, `CURRENT_MISSION_PR02.md` — execution path, unchanged scope
  - `docs/GOLDEN_PATTERNS.md` — ten implementation patterns, some stricter than what PR2 shipped
  - `docs/REPO_MAP.md` — navigation, no requirements
  - `docs/TEST_HARNESS_SPEC.md` — **new requirement**: reusable adversarial test helpers
- Unchanged versus V4 and already in the repo: `AGENTS.md`, `CLAUDE_START_HERE.md`,
  `docs/CTO_REVIEW_LOG.md` rules, `docs/FAST_EXECUTION_PROTOCOL.md`,
  `docs/PR2_EXECUTION_OVERRIDE.md`, `docs/templates/` (verified by `diff`).

## Gap analysis
Every V5 requirement checked against PR2 as pushed at `d63af0e`.

| V5 requirement | Already satisfied at `d63af0e`? | Action |
|---|---|---|
| GP-1 server invariant `object.workspace_id == object.brand.workspace_id` | Partly — enforced in serializers, so only for requests | **Gap.** Added `BrandInspiration.save()` invariant so ORM writers (jobs, commands, future services) cannot create a mismatched row. |
| GP-2 dynamic FK querysets scoped by request workspace | Partly — the upload and signal serializers scoped theirs; `BrandInspirationSerializer` validated instead | **Gap.** Scoped `brand`/`source` querysets there too, so a foreign id is unresolvable on every path rather than only rejected on some. |
| GP-3 immutable provenance | Yes — brand and source both frozen after creation | none |
| GP-4 workspace-scoped viewsets, no staff bypass, actions equally guarded | Yes — `test_every_mutation_path_is_404_for_another_tenant`, `test_staff_without_membership_cannot_read` | none |
| GP-5 controlled lifecycle with validated transitions | Yes — read-only status fields, named actions, `test_archive_twice_is_rejected` | none |
| GP-6 honest state, retry-safe permanent effects | Yes — 501 stub, idempotent `record_ai_signal` + partial unique constraint | none |
| GP-7 explicit origin/sentiment, AI cannot become user-confirmed, user signal outranks inference | Yes | none |
| GP-8 deterministic exclusion of revoked provenance | Yes — `eligible_for_retrieval()` on both managers | none |
| GP-9 per mutation path: happy + wrong tenant + wrong brand + role + protected field | Mostly — coverage existed but was hand-written per test, and several negative tests asserted only the status code | **Gap.** Reworked onto the shared harness so every negative assertion also proves the database did not move; added a table-driven viewer sweep over the eight paths that had no individually named role test. |
| GP-10 fix the defect class, not the instance | Partly | **Gap.** The harness is the mechanism: an attack is now a named helper reused across paths rather than a snippet copied per endpoint. |
| TEST_HARNESS_SPEC reusable helpers | No — did not exist | **Gap.** Added `apps/common/testing.py`. |

## Changes made in this pass
| Change | File | Why | Test |
|---|---|---|---|
| Tenancy invariant enforced on save | `apps/inspirations/models.py` | GP-1; closes the ORM/internal-service entry path that the preflight matrix marked "no" | `test_model_refuses_a_brand_from_another_workspace`, `test_model_refuses_a_source_from_another_brand`, `test_model_refuses_a_source_from_another_workspace` |
| Workspace-scoped `brand`/`source` querysets on the JSON serializer | `apps/inspirations/serializers.py` | GP-2; parity with the other two serializers | existing cross-tenant tests, now also asserting no row was written |
| Shared adversarial assertions | `apps/common/testing.py` (new) | TEST_HARNESS_SPEC | 20 call sites across both endpoints (4 cross-tenant FK, 2 cross-brand FK, 5 viewer-denial, 3 immutable-field, 2 protected-state, 2 visibility, 2 duplicate-action) |
| Negative tests reworked onto the harness | `apps/inspirations/tests.py` | GP-9/GP-10: every rejection now proves response **and** database non-mutation | whole suite |
| Table-driven viewer sweep | `apps/inspirations/tests.py` | eight mutation paths had no named role test | `test_viewer_is_denied_on_every_mutation_path` |
| Duplicate-action assertions | `apps/inspirations/tests.py` | TEST_HARNESS_SPEC `assert_duplicate_action_idempotent` | `test_repeating_archive_does_not_compound`, `test_repeating_analyze_does_not_compound` |
| V5 fast-path docs installed | repo root + `docs/` | the read order should be followable from the repository | n/a |

## Stale assumptions invalidated
- Preflight entry-path matrix said "Create inspiration … Job/internal: **no**". That was true of the code but described a gap, not a guarantee: nothing stopped an ORM writer. Now enforced at `save()`.
- Preflight risk scan said cross-tenant FKs are "validated server-side against the resolved workspace" — accurate for requests only. The invariant now also holds for non-request writers.
- Self-review test counts (65) and several test names are superseded; `PR02_SELF_REVIEW.md` has been updated in place with the current run.

## Scope check
No future-PR work was pulled in. No new endpoint, model, field, or migration was
added in this pass — the model change is a `save()` guard, not a schema change
(`makemigrations --check` still reports no changes). PR3+ scope (learning events,
brain compilation, context retrieval, analysis jobs) remains untouched.

## Rework gate
Every gap above has code **and** a named test. Full backend suite re-run at the
final gate; results in `docs/reviews/PR02_SELF_REVIEW.md`.
