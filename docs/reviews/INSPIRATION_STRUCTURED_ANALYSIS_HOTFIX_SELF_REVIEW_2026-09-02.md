# Inspiration structured-analysis hotfix — self-review

Date: 2026-09-02
Outcome: READY

## Mandatory gates

- PASS — Root cause: Gemini received an instruction asking for JSON but no
  `GenerateContentConfig` carrying the supplied JSON schema, so an empty
  `signals` array was accepted as a successful provider call.
- PASS — Schema enforcement: adapter tests prove both TEXT extraction and
  IMAGE_ANALYSIS send `application/json` plus the exact supplied schema.
- PASS — Failover semantics:
  `test_empty_required_observations_fail_over_instead_of_looking_successful`
  proves an empty required array raises `AIProviderError`, allowing AIRouter
  to try the next routed provider.
- PASS — Honest lifecycle:
  `test_empty_analysis_is_failed_not_marked_ready` proves zero observations
  produce FAILED with an explicit error, never READY.
- PASS — Existing-data recovery:
  `test_legacy_ready_row_without_signals_can_be_reanalysed` and
  `test_legacy_ready_reference_without_observations_is_reanalysed` prove both
  the analysis service and queued generation recover previously saved empty
  READY rows without another upload.
- PASS — No fake similarity: the existing
  `test_zero_analysis_observations_fails_instead_of_claiming_similarity`
  remains green and proves poster generation is not called for an empty
  analysis.
- PASS — Focused dependency gate: 201 tests passed.
- PASS — Full backend regression: 1,168 tests passed.
- PASS — Migration drift: `makemigrations --check --dry-run` returned no
  changes detected.
- PASS — Django system check: zero errors; local placeholder SECRET_KEY
  warning only.
- N/A — Frontend build: no frontend file changed.
- PASS — Patch hygiene: `git diff --check` returned no errors.

Zero FAIL. Zero NOT VERIFIED.
