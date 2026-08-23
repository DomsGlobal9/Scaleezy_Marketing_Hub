# Custom AI Onboarding Preflight — 2026-08-23

## Decision

- **PROCEED as a P0 Admin-console correction.** The current Add provider dialog still chooses the first installed provider and silently falls back to its default model. It cannot onboard a provider chosen by the workspace administrator.
- The new path accepts an explicit name, public HTTPS endpoint, optional API key/token, exact model, protocol, and administrator-selected capability set. No provider, model, protocol or capability is preselected.
- PR0–PR6 remain frozen ownership contracts. P1 pauses for this correction; PR7 remains closed.

## Dependency graph

Admin role → selected workspace → custom provider validation → explicit protocol and capabilities → tenant-owned catalogue row → encrypted workspace credential → explicit model → independent capability routes → AIRouter → generic protocol adapter → usage log.

## Entry paths

| Path | Rule |
| --- | --- |
| Catalogue GET | Global installed providers plus only the selected workspace's custom providers |
| Installed provider POST | Explicit provider and explicit model from the UI |
| Custom provider POST | Admin-only; atomic provider/config creation; name, URL, model, protocol and at least one capability required; key/token accepted when the endpoint requires one |
| Provider PATCH | Provider identity and endpoint remain immutable |
| Route replace-set | Custom adapter must actually support the requested capability |
| Delete | Remove selected-workspace routes/config; delete its owned custom catalogue row |
| Router/job | Resolve custom providers through the generic adapter without vendor branches |

## Security and failure rules

- Custom endpoints must be HTTPS, have no embedded credentials, query, or fragment, and resolve only to public addresses. Loopback, private, link-local, multicast, reserved and unspecified addresses are rejected.
- Credentials use the existing write-only Fernet-encrypted field.
- A custom provider is visible and configurable only inside its owning workspace.
- Custom onboarding creates no route automatically and cannot claim readiness until its authenticated health check passes.
- OpenAI-compatible custom endpoints may declare text, image generation, image analysis, image captions and embeddings. Video is excluded because that protocol has no standard video contract.
- The Scaleezy universal JSON protocol can declare every routing capability, including video generation and analysis. Its endpoint accepts `{capability, model, brief}` and returns a normalized result object.
- Declaring a capability makes the provider eligible for that route; the administrator still chooses and saves each ordered redundancy set. No route is created silently.

## Requirement → proof

| Requirement | Proof |
| --- | --- |
| No provider/model defaults in Add dialog | Frontend source check, typecheck and build |
| No protocol/capability defaults | Frontend source check and API required-field test |
| Onboard chosen custom AI | Admin API creation test and router adapter test |
| Every capability can be routed | Universal JSON all-capability route-set and execution test |
| Tenant isolation | Cross-workspace catalogue/config injection tests |
| SSRF boundary | Unsafe URL validation tests |
| Encrypted credentials | Existing encryption assertion plus custom-path assertion |
| No vendor coupling | Generic adapter build and route tests |
