# AI round-robin default — immutable preflight

Date: 2026-09-02
Scope: make round-robin the vendor-neutral default for multi-provider capability routes.

## Contract

- Callers continue to request capabilities, never named vendors.
- New routes default to `ROUND_ROBIN` in the model, API serializer, provisioning service, management command and admin UI.
- Existing `FAILOVER` routes migrate to `ROUND_ROBIN`; explicit `BEST_OF` routes remain untouched.
- Round-robin changes only the first candidate. If that provider fails, the existing ordered fallback loop tries every remaining eligible provider.
- One-provider routes behave exactly as before.
- Operators retain the ability to choose a different strategy per capability.

## Entry paths

| Path | Expected result | Evidence |
|---|---|---|
| Automatic tenant provisioning | New routes use round-robin | `test_it_creates_an_enabled_provider_and_both_routes` |
| Operator provisioning command | New routes use round-robin | `test_apply_creates_enabled_provider_and_both_routes` |
| Route-set API without a strategy | Serializer defaults to round-robin | affected AI API tests |
| Admin console empty route draft | UI selects round-robin | frontend typecheck/build |
| Existing production route | Migration converts failover only | migration + migration drift check |
| Multi-provider dispatch | Successful providers rotate | `test_round_robin_rotates_the_first_provider_between_calls` |
| Provider outage | Next eligible provider completes | `test_round_robin_falls_through_when_the_selected_provider_fails` |

## Boundaries

- No provider-specific behavior.
- No changes to credentials, tenancy, billing, quotas, publishing, Brand Brain or Context Gateway ownership.
- No speculative health probing or parallel spend.
