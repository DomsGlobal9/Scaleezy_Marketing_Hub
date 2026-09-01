# Research & Engagement Closure — Immutable Preflight

Date: 2026-09-01
Branch: `feat/research-engagement`
Frozen predecessors: PR0–PR7, Creative Command, Production Closure

## Authorized outcome

Close the next product loop without changing frozen ownership:

`RESEARCH → ADOPT AS INSPIRATION → CREATE → PUBLISH → ENGAGE → LEARN`

The slice adds provider-neutral public-web creative research and a governed,
workspace-scoped engagement inbox. It reuses the existing AI Router,
Inspirations, Social Connections, Brand Brain and Learning Fabric. It does not
introduce a second intelligence store, a second provider router, or automatic
public replies.

## Dependency graph

`Authenticated member → selected workspace → Brand → ResearchRun → AIRouter(RESEARCH) → verified ResearchFinding → explicit adoption → BrandInspiration`

`Connected social account → guarded platform sync → EngagementItem → assignment/lock → AIRouter(ENGAGEMENT_RESPONSE) draft → human approval → resolution`

## Entry paths

| Path | Required integrity rule |
|---|---|
| Create/list research runs | Active workspace membership; brand belongs to that workspace |
| Background research task | Re-load run, brand and workspace from one persisted graph; no caller-supplied tenant switch |
| Provider findings | Structured, bounded, deduplicated; public HTTPS source verified before adoption |
| Adopt research finding | Same workspace/brand; idempotent; creates the existing `BrandInspiration` record with attribution and rights status |
| Engagement sync | Connected account belongs to selected workspace; only supported platform adapters run |
| Engagement CRUD/actions | Workspace scoped; lifecycle transitions through named actions; assignment and lock are explicit |
| AI reply draft | Existing AI Router only; no provider name in product code; no automatic send |
| Approval/resolution | Editor role; records actor and timestamp; never reports SENT unless a platform call succeeds |

## Requirement-to-test map

- Cross-tenant research and engagement access is refused.
- Cross-workspace brand, connection, assignee and saved-reply ids are refused.
- Research results with unsafe, unreachable or non-text URLs are not adoptable.
- Duplicate findings and duplicate platform events are idempotent.
- A finding can be adopted only once and keeps source attribution/rights state.
- Missing research/reply routes fail honestly with no fabricated result.
- AI reply generation produces a draft only.
- Collision locking prevents two operators from silently owning the same item.
- Inbox sync never exposes OAuth tokens and stores bounded source payloads.
- Read-only roles cannot create runs, adopt findings, assign, approve or resolve.

## RED / stop-condition audit

- PR0 tenancy/RBAC: preserved; established mixins and role gates are reused.
- PR2 Inspirations: preserved; adopted discoveries become `BrandInspiration`.
- PR3/PR7 learning: preserved; no new learning owner is introduced.
- PR5 AI ownership: preserved; all AI calls go through `AIRouter` by capability.
- Publishing: untouched.
- Secrets: existing encrypted social tokens are read by platform adapters only;
  no new secret field or credential format is introduced.
- Autonomy: public replies remain human-governed in this slice.

## Risks and controls

- Provider-hallucinated URLs: verify through the existing redirect-safe,
  public-address-pinned, streamed fetcher before allowing adoption.
- Copyright/rights ambiguity: rights defaults to `UNKNOWN`; discovery stores
  citation metadata, not copied media; the user explicitly chooses adoption.
- External API variance: normalize only supported X and YouTube reads; other
  platforms report unsupported rather than fake success.
- Queue failure: persisted run state moves to `FAILED` with a bounded error.
- Cost: research and reply drafting have independent admin-routable
  capabilities and inherit spend approval/quota enforcement.

## Exit gate

Focused model/API/task/adapter tests, tenant attack tests, migration drift,
backend regression, frontend type/lint/format/build, and an immutable
self-review with zero FAIL or NOT VERIFIED.
