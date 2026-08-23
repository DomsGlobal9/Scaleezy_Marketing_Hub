# AI Provider Catalogue Deploy Recovery Preflight — 2026-08-23

## Decision

- **PROCEED.** The live Add provider dialog proves the production database still contains only Gemini and OpenAI even though the adapter commit was pushed.
- Scope is limited to an additive data migration that installs the five already-approved provider catalogue rows.
- PR0–PR6 ownership remains unchanged. P1 and PR7 remain closed.

## Contract

| Requirement | Implementation | Proof |
| --- | --- | --- |
| Provider rows exist even when a hosting dashboard overrides `sync_ai_catalogue` | `ai.0007_seed_openai_compatible_providers` | Migration test and focused AI tests |
| Global provider kill switch is operator-owned | Existing rows retain `is_available` | Disabled-row regression test |
| Tenants opt in explicitly | Migration creates no workspace provider or route rows | Migration source review |
| Repeat deploys are safe | Key-based idempotent upsert | Migration invoked twice in regression test |

## Risk boundary

- No schema change, deletion, credential write, workspace mutation, routing mutation, or frontend change.
- Reverse is deliberately non-destructive because tenant configuration may later reference these catalogue rows.
- Provider endpoints, models, capability ownership, and provider-neutral AIRouter behavior remain in the installed adapter layer.

