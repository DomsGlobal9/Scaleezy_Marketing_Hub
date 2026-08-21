# PR2 — Inspiration Intelligence Foundation — Execution Override

This is the immediate authorized next PR after approved PR1.

## Build ONLY
BrandInspiration → original source/provenance → InspirationSignal → explicit user annotation → AI/user origin distinction → liked/disliked/neutral semantics → tenant/brand isolation → API → tests.

## Do NOT build yet
- multimodal AI analysis pipeline
- Brand Brain compiler
- Context Gateway/retrieval
- generation integration
- universal learning
- performance learning
- full onboarding/calibration UI

## Mandatory integrity
- Inspiration belongs to authenticated workspace and brand.
- If inspiration references BrandSource, source must belong to same workspace AND same brand.
- Brand cannot be reassigned after creation without explicit future transfer workflow.
- Signal must belong to its inspiration's workspace/brand transitively.
- User-confirmed and AI-inferred signals must never be indistinguishable.
- AI inference cannot silently overwrite explicit user preference.
- Like/dislike/neutral must be explicit semantics, not inferred from arbitrary weight alone.
- Revoked/archived source/reference must become ineligible for future retrieval.
- No raw cross-tenant sharing.
- Original inspiration and derived signals remain separately addressable.

## Required adversarial tests
- Tenant A creates inspiration against Tenant B brand.
- Tenant A references Tenant B source.
- Same workspace Brand A inspiration references Brand B source.
- PATCH attempts to move inspiration to another brand.
- Viewer mutation denied.
- Signal attached to another tenant/brand inspiration denied.
- Direct mutation cannot convert AI-derived signal into user-confirmed origin without authorized action.
- Archived/revoked reference eligibility is represented honestly.
