# Immediate Review Learning — Immutable Self-Review

## Outcome

- PASS — The first tagged corrective review now creates or strengthens one brand-scoped `LEARNED` / `SOFT` rule, recompiles Brand Brain, and reaches the next generation context without waiting for a second occurrence.
- PASS — Generic inferred preferences and generic learned rules still require the frozen two-event corroboration threshold.
- PASS — No tenant, RBAC, provider, publishing, PR7 governance, or schema contract changed.

## Requirement evidence

| Gate | Result | Concrete evidence |
|---|---|---|
| First correction learns | PASS | `TrainingEngineTests.test_first_tagged_rejection_writes_a_soft_cited_rule`; `ReviewIntegrationTests.test_first_tagged_rejection_changes_the_next_prompt`; `ReviewIntegrationTests.test_first_tagged_request_edits_also_learns` |
| Actionable input on every API path | PASS | `ContentReviewTests.test_reject_requires_an_active_feedback_tag`; `ContentReviewTests.test_request_edits_requires_actionable_guidance`; `FeedbackAPITests.test_direct_corrective_feedback_requires_a_tag_and_guidance` |
| Brand Brain and generation context update | PASS | `TrainingEngineTests.test_a_learned_rule_survives_a_brand_brain_rebuild`; `TrainingEngineTests.test_review_learning_reaches_the_generation_context`; compile failure state is exposed by `test_brain_compile_failure_is_exposed_as_not_current` |
| Evidence provenance | PASS | `TrainingEngineTests.test_immediate_rule_proves_the_event_against_its_feedback_source`; `RuleAuthorityTests.test_immediate_review_path_refuses_non_feedback_evidence`; service resolves every event to its matching Feedback, user, brand, item, verdict, tag and exact dedupe key |
| Retry and ordering safety | PASS | `test_replaying_the_same_training_pass_does_not_double_count`; `test_replaying_an_older_review_does_not_overwrite_newer_guidance`; evidence is set-unioned and no-new-evidence replay is a semantic no-op |
| Concurrent first-review safety | PASS | `_upsert_learned_rule` locks the stable brand/workspace row before lookup/create; repeat-strengthening and full regression tests remain green |
| Tenant/brand isolation | PASS | `test_learning_stays_inside_the_workspace`; shared writer still rejects foreign workspace and brand evidence |
| Human authority | PASS | Immediate path accepts only attributable negative `Feedback` evidence and always writes `SOFT`; generic one-event inference remains rejected by `test_generic_inference_still_requires_corroboration` |
| Honest UI | PASS | Review requires a tag plus guidance before submit; it compares pre/post occurrence counts and Brand Brain health before claiming the next generation learned; Brand Master copy distinguishes rules from calibration preferences |
| Untagged free text | N/A | Deliberately refused as an immediate rule because it has no stable taxonomy claim key; corrective endpoints now require a valid active tag rather than silently accepting non-learning input |

## Verification

- PASS — Full backend regression: **1,050 tests**, **0 failures**, **0 errors**; final stable backend snapshot; 85.120 seconds.
- PASS — Focused content/feedback/learning suite: **131 tests**, **0 failures**, **0 errors**.
- PASS — `manage.py check`: no issues.
- PASS — `makemigrations --check --dry-run`: no changes detected.
- PASS — TypeScript `tsc --noEmit`: exit 0.
- PASS — ESLint on all changed frontend files: 0 errors; one pre-existing Fast Refresh warning in `feedback-tags.tsx`.
- PASS — Production frontend build: exit 0.
- PASS — `git diff --check`: clean.

## Environment note

The first unconfigured full-suite attempt failed in an unchanged AI encryption test because this worktree has no `.env` and no `FERNET_SECRET_KEY`. The exact test failed standalone without the key and passed standalone with a process-local valid test key. The final full regression used that process-local key; no secret was written to the repository.

## Final decision

- READY TO COMMIT.
- Zero FAIL and zero NOT VERIFIED gates.
