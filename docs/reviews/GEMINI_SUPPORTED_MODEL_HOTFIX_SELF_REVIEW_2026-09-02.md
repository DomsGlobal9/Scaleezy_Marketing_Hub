# Gemini supported-model hotfix — self-review

Date: 2026-09-02
Outcome: READY

## Mandatory gates

- PASS — Root cause: `GeminiAdapter.default_model` was `gemini-1.5-pro` while `GeminiGeneratorService.TEXT_MODEL` was `gemini-2.5-flash`.
- PASS — Supported default: `test_adapter_default_matches_the_supported_generation_model` proves both paths agree.
- PASS — Existing data: `test_retired_defaults_and_overrides_are_refreshed_without_touching_custom_models` proves the migration is idempotent and preserves other administrator-selected models.
- PASS — Honest provider test: `test_health_check_rejects_a_retired_model_without_generation` proves a 404 is detected before generation without leaking the credential or upstream response.
- PASS — Provider-neutral fallback: AIRouter and round-robin code are unchanged; provider failures continue to fall through normally.
- PASS — Focused backend gate: 164 tests passed.
- PASS — Migration drift: `manage.py makemigrations --check --dry-run` returned `No changes detected`.
- PASS — Full backend regression: 1,152 tests passed.
- N/A — Frontend verification: no frontend file changed.
- PASS — Patch hygiene: `git diff --check` returned no errors.

Zero FAIL. Zero NOT VERIFIED.
