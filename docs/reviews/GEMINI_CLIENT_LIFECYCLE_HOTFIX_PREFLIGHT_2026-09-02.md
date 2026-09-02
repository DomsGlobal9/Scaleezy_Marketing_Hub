# Gemini Client Lifecycle Hotfix — Immutable Preflight

- Scope: fix production `Cannot send a request, as the client has been closed` failures in Gemini adapter calls.
- Root cause: `google.genai.Client.__del__` closes its HTTP transport; adapter expressions discarded a temporary client after resolving `.models` and before the model request completed.
- Change: retain a strong local client reference for structured extraction, inspiration analysis, embedding and engagement drafting. Provider routing, credentials, capabilities, Brand Brain, billing and publishing ownership remain unchanged.
- Failure contract: upstream errors still become `AIProviderError` and AIRouter failover; no fake result or draft.
- Proof: deterministic lifetime regression test plus focused provider/inspiration generation suites; no migration.
- Stop decision: PROCEED — implementation repair only, no architecture or product-semantic change.
