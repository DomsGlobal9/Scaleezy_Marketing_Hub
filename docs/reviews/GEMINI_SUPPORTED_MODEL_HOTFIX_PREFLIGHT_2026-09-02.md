# Gemini supported-model hotfix — immutable preflight

Date: 2026-09-02

## Defect

The Gemini adapter catalogue default remained `gemini-1.5-pro` after the generation service moved to `gemini-2.5-flash`. Structured inspiration analysis uses the adapter model, so production returned `404 NOT_FOUND` before poster generation.

## Contract

- Use the stable `gemini-2.5-flash` identifier already owned by `GeminiGeneratorService.TEXT_MODEL`.
- Refresh the global Gemini catalogue default during deployment.
- Migrate only exact retired workspace overrides (`gemini-1.5-pro` and `models/gemini-1.5-pro`); preserve every other administrator-selected model.
- Make provider health testing query the exact configured model and verify `generateContent` support without spending generation tokens.
- Preserve capability routing, round-robin, provider fallback, credentials, tenant boundaries and generation persistence.

## Evidence required

- Adapter default equals the generator service model.
- Retired model migration is idempotent and preserves a supported custom override.
- Health check rejects a 404 model without exposing upstream details or credentials.
- Inspiration/Gemini/AI focused tests pass.
- Migration drift, frontend build and full backend regression remain clean.
