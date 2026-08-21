# CURRENT_MISSION_PR02.md — Claude Fast Path

## One objective
Implement PR2 Inspiration Intelligence Foundation on `marketinghub/merge` with first-pass CTO acceptance.

## Read only this fast path first
1. `AGENTS.md`
2. this file
3. `docs/REPO_MAP.md`
4. `docs/GOLDEN_PATTERNS.md`
5. relevant existing code
Use the larger architecture files only when a contract question arises.

## Build
BrandInspiration → original source/provenance → InspirationSignal → explicit annotation → origin distinction (USER vs AI) → sentiment (LIKED/DISLIKED/NEUTRAL) → tenant/brand-safe APIs → tests.

## Reuse
- `apps.common.mixins.WorkspaceScopedMixin`
- existing RBAC in `apps.common.permissions`
- `apps.brands.Brand`
- `apps.knowledge.BrandSource` and its PR1 validation/lifecycle patterns
- repository serializer/ViewSet/router conventions
- existing test factories/fixtures where available

## Do not build
AI image/video analysis, Brand Brain compiler, Context Gateway, generation integration, universal/performance learning, calibration/onboarding UI.

## Vertical slices
### Slice A — BrandInspiration
Model + migration + serializer + ViewSet/routes + tenant/brand/source validation + tests.

### Slice B — InspirationSignal
Model + serializer + API + origin/sentiment integrity + tests.

### Slice C — lifecycle/provenance hardening
Immutability, archived/revoked eligibility representation, negative tests, API consistency.

### Slice D — adversarial/full gate
Run security matrix, module tests, then full backend regression once.

## Mandatory attacks
- Tenant A → Tenant B brand
- Tenant A → Tenant B source
- same workspace Brand A → Brand B source
- PATCH brand reassignment
- Viewer mutation
- signal → other tenant inspiration
- origin escalation AI → USER
- archived/revoked reference eligibility
- alternate mutation paths where applicable

## Push gate
Zero mandatory FAIL.
Zero mandatory NOT VERIFIED.
Every PASS cites a named test or exact evidence.
Push PR2 only; stop before PR3.
