# PR02_CTO_REWORK_INTAKE.md

Created from `docs/templates/CTO_REWORK_INTAKE_TEMPLATE.md` after the PR2 CTO
re-review. `docs/reviews/PR02_PREFLIGHT.md` and `docs/reviews/PR02_V5_INTAKE.md`
are left untouched; this is a new file, as the template requires.

## Review received
- Date: 2026-08-21
- PR/head at intake: `marketinghub/merge` @ `6b5df47` ("harden(pr2): enforce tenancy at the model, share the attack assertions")
- Review verdict: **REWORK.** Do not start PR3.
- Exact review, verbatim:

> PR2 CTO re-review: REWORK. Do not start PR3.
>
> The V5 hardening is accepted and must remain.
>
> However, the previous CTO semantic-integrity blocker was not implemented.
>
> Implement deterministic human-preference authority:
>
> For a given inspiration + category + attribute, the latest active explicit USER signal is authoritative.
>
> AI conflicts when either normalized value OR sentiment differs from the authoritative USER signal.
>
> Historical USER signals must remain auditable but must not remain simultaneously authoritative/retrievable.
>
> Confirming a conflicting AI direction must explicitly supersede the previous authoritative USER preference so contradictory truths do not remain active.
>
> Add tests for:
>
> * same sentiment + different value;
> * different sentiment + same value;
> * multiple historical USER signals;
> * latest USER signal wins;
> * confirming conflicting AI direction;
> * AI retry cannot resurrect older USER preference;
> * simple value normalization for case/whitespace.
>
> Update eligible_for_retrieval() so only the authoritative USER preference is active for that attribute.
>
> Create docs/reviews/PR02_CTO_REWORK_INTAKE.md documenting this exact review and the resulting fixes.
>
> Run apps.inspirations tests and full backend regression.
>
> Push and stop for CTO re-review

## What was actually wrong

The shipped design had one true statement about preference conflict — *an
inference that disagrees with a stated preference must not silently win* — and
implemented the weakest possible version of it. Three holes:

1. **Nothing made a preference authoritative.** A user could state
   `TYPOGRAPHY/headline_face = "condensed grotesque", LIKED` and later
   `= "serif display", DISLIKED`. Both rows stayed active and both were
   returned by `eligible_for_retrieval()`. The brand simultaneously held two
   contradictory truths and nothing in the schema or the code said which one
   was current.
2. **Conflict was detected on sentiment alone.** `record_ai_signal` compared
   only `sentiment`. An inference saying "they like Serif Display" against a
   stated "they like Condensed Grotesque" agreed on sentiment, so it was not
   flagged, and both were retrievable. This is the case the review names first.
3. **Confirming a contradicting inference left the contradiction standing.**
   `confirm` cleared `conflicts_with` on the AI row and did nothing to the USER
   row it contradicted. The disagreement disappeared from view without being
   resolved — both rows became retrievable and opposed.

None of this was hypothetical: `test_agreeing_ai_signal_is_not_flagged_as_conflict`
asserted the buggy behaviour as correct. It has been rewritten, not deleted.

## Mental-model refresh

| Blocker | Root cause | All affected entry paths | Fix | New/updated test |
|---|---|---|---|---|
| No deterministic authority for an attribute | The identity of "a preference" was never modelled; rows were independent facts | `POST /inspiration-signals/`, direct ORM writes, `record_ai_signal` | Supersession columns + partial unique constraint `uniq_authoritative_user_signal` on `(inspiration, category, normalized_attribute)` where the row is USER, unsuperseded and CONFIRMED. Stating a preference retires the one it replaces, in one transaction, before inserting. | `test_latest_user_signal_wins_and_history_is_auditable`, `test_database_refuses_two_authoritative_user_signals`, `test_at_most_one_signal_is_retrievable_per_attribute` |
| Conflict compared sentiment only | `record_ai_signal` compared `sentiment` and nothing else | `record_ai_signal`, `confirm`, `reject`, new USER signal | `signals_conflict()` compares folded value **or** sentiment; `reconcile_attribute()` re-derives it after every event that can move authority | `test_same_sentiment_different_value_conflicts`, `test_different_sentiment_same_value_conflicts` |
| Confirming a contradicting inference resolved nothing | `confirm` cleared the flag instead of deciding the contradiction | `POST /inspiration-signals/{id}/confirm/` | `confirm_signal()` recomputes the current authority and explicitly supersedes it with reason `SUPERSEDED_BY_CONFIRMED_AI_DIRECTION` | `test_confirming_conflicting_ai_direction_supersedes_the_preference`, `test_confirming_an_agreeing_ai_signal_supersedes_nothing`, `test_confirm_uses_current_authority_not_a_stale_pointer` |
| History was neither preserved nor excluded | No supersession concept at all | all write paths | `superseded_at` / `superseded_by` / `superseded_reason`; rows stay listable and API-visible, and are excluded from retrieval | `test_latest_user_signal_wins_and_history_is_auditable` (asserts the API still lists all three and exposes the trail) |
| A retry could reopen a settled question | `record_ai_signal` rewrote content under an existing human verdict | `record_ai_signal` | On a changed inference where a human has already ruled, file a NEW row and supersede the old one rather than rewriting it | `test_ai_retry_cannot_resurrect_an_older_user_preference`, `test_reanalysis_supersedes_rather_than_rewriting_a_judged_inference` |
| Case/whitespace could split one preference in two | Raw string comparison | every path | `normalize_signal_text()` — strip, collapse internal whitespace, casefold — persisted as `normalized_value` / `normalized_attribute`, written in `save()` | `test_value_normalization_ignores_case_and_whitespace`, `test_attribute_normalization_keeps_one_authority` |
| PATCH could rewrite a stated preference in place | `value`/`sentiment` were writable | `PATCH`/`PUT /inspiration-signals/{id}/` | `category`, `attribute`, `value`, `sentiment` are immutable after creation, with a 400 pointing at "create a new signal"; `weight`/`confidence` stay editable | `test_a_stated_preference_cannot_be_edited`, `test_weight_and_confidence_remain_editable` |

## The rule, stated once

For one `(inspiration, category, normalized_attribute)`:

- The **authoritative** preference is the latest USER-origin signal that is
  CONFIRMED and not superseded. The partial unique constraint permits only one;
  `authoritative_user_signal()` also orders by `-created_at, -pk` so "latest
  wins" is stated in the code and stays deterministic if the constraint is ever
  dropped.
- An inference **conflicts** when its folded value differs from the authority's,
  **or** its sentiment does. Either half is enough.
- `eligible_for_retrieval()` returns **at most one row per attribute**. It drops
  superseded rows, rejected rows, inferences flagged as conflicting, and
  inferences about an attribute that has a stated preference — the last one
  whether the inference agrees or not, because two rows saying the same thing
  get counted twice by anything that weighs signals, and "agrees" only holds
  until the next re-analysis. `test_at_most_one_signal_is_retrievable_per_attribute`
  asserts the invariant directly.
- Supersession is a **one-way door**. Rejecting the current preference leaves the
  attribute with none; it does not revive the one that was replaced. Resurrection
  would make the active truth depend on the order of past rejections, which is
  the non-determinism this rework removes.
  (`test_rejecting_the_authority_does_not_revive_its_predecessor`)

## Code changed

| File | Change |
|---|---|
| `apps/inspirations/models.py` | `normalize_signal_text()`; `SupersessionReason`; `superseded_at`/`superseded_by`/`superseded_reason`, `normalized_attribute`/`normalized_value`; `save()` keeps the folded columns in step (and adds them to `update_fields` when their source is written); `QuerySet.active()` / `.for_attribute()` / `.authoritative_user_signals()`; `eligible_for_retrieval()` rewritten with the `Exists()` authority clause; `retrieval_eligibility()` gained `SUPERSEDED_*` and `USER_PREFERENCE_TAKES_PRECEDENCE`; two partial unique constraints, one check constraint, one index |
| `apps/inspirations/services.py` | `authoritative_user_signal()`, `active_ai_signal()`, `signals_conflict()`, `supersede()`, `link_supersession()`, `reconcile_attribute()`, `record_user_signal()`, `confirm_signal()`, `reject_signal()`; `record_ai_signal()` rewritten with the three-case rule |
| `apps/inspirations/views.py` | `perform_create`, `confirm`, `reject` delegate to the services so every path shares one implementation of authority; `InspirationSignalError` surfaces as a 400 `PREFERENCE_CONFLICT` rather than a 500 |
| `apps/inspirations/serializers.py` | supersession trail and folded columns exposed read-only; stated preferences immutable after creation |
| `apps/inspirations/migrations/0002_preference_authority.py` | new columns, backfill, index, constraint swap |
| `apps/inspirations/tests.py` | `PreferenceAuthorityTests` (27 tests); `test_agreeing_ai_signal_is_not_flagged_as_conflict` rewritten |

## Migration

`0002_preference_authority`. Additive columns, a `RunPython` backfill of the
folded columns (batched, with a frozen copy of the normalisation function so the
migration keeps doing what it did the day it was written), one index, then the
constraint swap: `uniq_ai_signal_per_inspiration_attribute` is replaced by
`uniq_active_ai_signal` (same key, now on the folded attribute and scoped to
unsuperseded rows) and `uniq_authoritative_user_signal` is added.

No column or table is dropped and no data is deleted. The constraint swap is
ordered after the backfill so the new uniqueness rules are evaluated against
folded values that exist.

## Stale assumptions invalidated
- `PR02_SELF_REVIEW.md` R6 previously read "AI inference never silently overrides
  an explicit preference — PASS". That was true only of sentiment. The row has
  been rewritten and now cites the value-difference tests.
- `PR02_FLOW_MATRIX.md` described `conflicts_with` as set when "the inference
  disagrees" without saying on what. Updated.
- `PR02_SECURITY_ATTACK_MATRIX.md` PROV-02 cited
  `test_agreeing_ai_signal_is_not_flagged_as_conflict` as evidence that
  agreement was handled correctly. That test asserted the defect; it has been
  rewritten and the row now cites the new coverage.
- The V5 intake's claim that GP-7 ("explicit user signal outranks AI inference")
  was already satisfied was wrong on the value axis. Corrected here rather than
  by editing that file.

## Scope check
No PR3+ work was pulled in. No `LearningEvent` is emitted, no brain compilation,
no retrieval ranking, no analysis job, no UI. The V5 hardening is untouched and
still tested: the model-level tenancy invariant, the workspace-scoped FK
querysets and the shared assertions in `apps/common/testing.py` are all still in
place, and the V5 test classes still pass unmodified.

## Defects found while implementing, and fixed

An adversarial probe of the new semantics turned up four holes in the first cut
of this rework. All four are fixed and pinned by tests.

| Defect | Why it mattered | Fix | Test |
|---|---|---|---|
| Re-confirming a withdrawn preference returned a 500 | Reject preference A, state preference B, then `POST /{A}/confirm/`: A goes back to CONFIRMED and collides with B on `uniq_authoritative_user_signal`. And had the constraint not caught it, an OLDER preference would have become authoritative — the opposite of "latest wins". | `confirm_signal()` refuses when a newer stated preference is authoritative, with a 400 pointing at "state a new preference". Re-confirming is still allowed when nothing replaced it. | `test_reconfirming_a_withdrawn_preference_is_refused`, `test_reconfirming_a_withdrawn_preference_is_allowed_when_nothing_replaced_it` |
| Superseded rows could still be confirmed or rejected | Editing history. The row stays out of retrieval either way because supersession outranks confirmation, so the call could only mislead the caller. | `confirm_signal()` / `reject_signal()` refuse on a superseded row. | `test_history_cannot_be_confirmed_or_rejected` |
| `normalized_attribute` was `max_length=320` | `attribute` caps at 255 characters, but casefolding can treble a string: U+FB04 folds to "ffl", so 255 characters fold to 765. The write would fail on PostgreSQL and truncate silently on SQLite — and a truncated key means the uniqueness rule guards the wrong thing. | `max_length=765`. | `test_normalized_attribute_survives_worst_case_case_folding` |
| `QuerySet.update()` and `bulk_update()` bypass `save()` | They would change `attribute` while `normalized_attribute` kept pointing at the old key: the row stops being findable by its own attribute, and `uniq_authoritative_user_signal` silently stops guarding it. | The queryset refuses to bulk-write `attribute`/`value` without their folded twins; `bulk_create()` folds its rows. Fields that feed no folded column are still bulk-updatable. | `test_queryset_update_cannot_desynchronise_the_folded_columns`, `test_bulk_create_folds_its_rows` |

## Deliberate extensions beyond the literal review
Both are flagged for the CTO to accept or reject.

1. **The attribute key is folded, not just the value.** The review names value
   normalization. But if `Headline_Face` and `headline_face` are different
   attributes, two USER signals can be simultaneously authoritative for what a
   person calls one thing — which is the exact failure being fixed.
   (`test_attribute_normalization_keeps_one_authority`)
2. **A re-analysis that changes a judged inference supersedes it instead of
   rewriting it.** Rewriting would leave a CONFIRMED or REJECTED verdict
   attached to content the person never saw — the same defect as an inference
   overwriting a preference, one level down. Unreviewed inference churn is still
   rewritten in place, so retries stay idempotent.
   (`test_reanalysis_supersedes_rather_than_rewriting_a_judged_inference`)

Also worth an explicit yes or no: **an inference that agrees with a stated
preference is no longer retrievable.** This follows from "only the authoritative
USER preference is active for that attribute", but it is a behaviour change from
what PR2 shipped, so it should be a decision rather than an inference on my part.

## Rework gate
Every blocker above has code and a named test. Results are recorded in
`docs/reviews/PR02_SELF_REVIEW.md`.
