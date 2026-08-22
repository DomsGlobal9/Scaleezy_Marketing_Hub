# OpenAI Provider Adapter Recovery Preflight — 2026-08-22

## Authority and boundary

- User-selected provider: OpenAI, as a second production-capable AI for redundancy.
- Frozen owner: PR5 `Context Gateway → AIRouter → provider adapter` architecture.
- Authorized recovery: install one OpenAI adapter, seed its catalogue metadata, expose it through the existing Admin-only provider/routing console, and make its platform credential deployable.
- Explicitly out of scope: vendor selection in product features, changes to Context Gateway or AIRouter ownership, automatic changes to existing workspace routes, PR7, and a new infrastructure stack.

## Reuse decision

| Concern | Existing contract | Decision |
| --- | --- | --- |
| Product calls | Capability requests through `AIRouter` | Preserve; product code never imports or names OpenAI. |
| Provider integration | `AIProviderAdapter` discovery under `apps/ai/adapters` | Add one discovered adapter only. |
| Credentials | Encrypted workspace credential with server-secret fallback | Preserve; plaintext is never returned or logged. |
| Redundancy | Ordered route sets with FAILOVER, ROUND_ROBIN or BEST_OF | Preserve; do not auto-route existing workspaces. |
| Administration | OWNER/ADMIN-only `/admin` console and API | Preserve. |
| HTTP dependency | Existing `httpx` installation | Reuse; add no SDK dependency. |

## Entry paths and failure contract

| Entry path | Expected behavior | Required failure behavior |
| --- | --- | --- |
| Text generation | Normalized headline/caption/hashtags result | Sanitized `AIProviderError`; router tries the next provider. |
| Image generation | Normalized `image_url` result | Empty/invalid response fails; never reports success. |
| Image analysis/caption | Multimodal request through adapter | Missing image fails before network. |
| Embedding | Normalized numeric vector | Missing text or empty vector fails. |
| Admin health test | Reports configured state without exposing key | Missing key reports unavailable. |
| Catalogue migration | Adds/updates OpenAI metadata only | Existing workspace enablement and routes remain untouched. |

## Proof plan

- Mocked adapter tests for request shape, normalized output and sanitized failures; no live or paid call.
- AI registry, router, route-set, provisioning and Admin API regression tests.
- Full backend suite, migration drift check and Django system check.
- Frontend type-check, substantive lint and production build.
- A credentialed staging smoke remains a deployment gate, not a unit-test side effect.

## Stop decision

- **PROCEED** — this fills the missing second production adapter inside frozen PR5 boundaries. PR7 remains closed.
