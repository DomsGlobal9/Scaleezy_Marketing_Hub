# Scaleezy Autonomous Social OS — Frozen Closure Contract

Status: **APPROVED FOR ADDITIVE DELIVERY**
Frozen on: 2026-09-01
Base: PR0–PR7 remain the governing ownership contracts.

## Product outcome

Scaleezy must operate one trustworthy, tenant-isolated loop:

`RESEARCH → DIRECT → CREATE → PRODUCE → REVIEW → DISTRIBUTE → ENGAGE → MEASURE → MONETIZE → LEARN → IMPROVE`

The platform may automate work, but must never invent success, cross a workspace
boundary, hide a provider failure, lose provenance, or publish outside the
client's configured authority.

## Frozen ownership — extend, never replace

| Concern | Existing owner |
|---|---|
| Tenant, membership and RBAC | PR0 workspace architecture and `X-Workspace-Id` |
| Knowledge and provenance | PR1 `apps.knowledge` |
| Brand inspiration and signals | PR2 `apps.inspirations` |
| Feedback and learned instructions | PR3 `apps.learning` / `apps.feedback` |
| Derived brand intelligence | PR4 Brand Brain compiler |
| Generation context and providers | PR5 Context Gateway and `AIRouter` |
| Onboarding, calibration and generation | PR6 services and UI |
| Platform standards and universal learning | PR7 `apps.universal` |
| Background execution | Existing Postgres-backed Django task runner |
| Publishing | Existing publishing jobs, policies and social adapters |
| Poster composition | Existing `apps.layouts` plugin registry |

No second context engine, router, learning ledger, review model, job stack, or
publishing architecture may be introduced.

## Reference-image interpretation

The supplied “AI Social Media Operating System” image is a useful product map,
not an implementation specification. Its seven visible modules map to Scaleezy
as follows:

| Reference module | Scaleezy capability | Current verdict |
|---|---|---|
| Research | Knowledge, inspirations, platform library, listening and trend intelligence | Foundation live; internet discovery and listening missing |
| Content Engine | Brand Brain, Context Gateway, copy/script/voice direction | Copy live; explicit creative-direction package and voice production incomplete |
| Production Studio | Image, poster, carousel, video, presenter/B-roll | Poster foundation live; complete multi-asset production incomplete |
| Distribution | Review, calendar, scheduled publishing, retries | Foundation live; governed autopilot planning missing |
| Engagement | Comments, mentions, DMs, triage and responses | Missing beyond connection-level settings |
| Analytics | Publishing state plus external performance | Pipeline counts live; real performance ingestion missing |
| Monetization | Lead capture, attribution, CRM handoff and revenue | Missing |
| Growth Engine | Performance-informed recurring planning | Learning foundation live; autonomous operations missing |

## Delivery programme

### Slice A — Creative Command

- Put the existing Scaleezy inspiration library inside Create Content.
- Allow unlimited platform-library and brand-inspiration selection.
- Support `USE`, `AVOID`, `PRIMARY`, and `SUPPORTING` direction per reference.
- Support full-reference or any combination of visual/copy focus areas.
- Keep campaign-only choices out of permanent Brand Brain state unless the user
  explicitly saves them.
- Add layout choice before generation, using the existing layout registry.
- Carry selected references through both synchronous and asynchronous paths.
- Persist an immutable provenance snapshot in the content generation trace.

### Slice B — Production closure

- Prove real text and image provider readiness per workspace.
- Generate raw imagery through `AIRouter`; compose branded output through
  `apps.layouts`.
- Complete per-slide carousel generation, editing and retry.
- Complete video/storyboard/voice/caption generation with durable outputs and
  honest async progress.
- Preserve partial successes and permit capability-specific retry.

### Slice C — Research and engagement

- Add provider-neutral, admin-governed discovery adapters for external creative
  references and trend signals.
- Require source URL, attribution, rights status, safe retrieval and dedupe.
- Add social listening, competitor intelligence and anomaly/trend alerts.
- Add one workspace-scoped inbox for comments, mentions and messages.
- Add assignment, collision prevention, approval, saved replies, sentiment,
  urgency and AI-assisted responses.

### Slice D — Performance and monetization

- Ingest genuine post-level reach, impressions, engagement, clicks and
  conversions with source freshness.
- Emit idempotent `PERFORMANCE_OBSERVED` events without treating bookkeeping as
  human judgement.
- Attribute outcomes to campaign, content, provider, model, inspiration,
  layout and cost.
- Add lead capture, qualification, CRM/webhook handoff, funnel state and
  revenue attribution.

### Slice E — Governed Autopilot

- Add client/brand policy, campaign plans, run ledger and run steps.
- Reuse durable jobs for planning, generation, review, publishing and retries.
- Support review-required, scheduled-approval and explicitly authorized
  auto-publish modes.
- Add cadence, timezone, channels, objectives, budgets, quotas, pause/resume and
  emergency stop.
- Make every decision, failure, retry and output visible in an Operations
  Cockpit.
- Feed genuine outcomes back into the next plan through the existing learning
  and Brand Brain contracts.

## Creative freedom

Users may select any number and combination of inspirations, industries,
platforms, formats and creative directions. Scaleezy may summarize them to fit
provider context limits, but may not silently discard a selection. Conflicts
are surfaced for the user or resolved by an explicit precedence choice.

Only non-creative safeguards remain mandatory: workspace isolation, authorized
access, safe external retrieval, source attribution, provider capability,
billing/quota enforcement and publishing authority.

## Market-parity requirements

- Unified create/publish/review calendar.
- Social listening and competitor intelligence.
- Unified engagement inbox with team ownership.
- Approval workflows and collision prevention.
- Content repurposing and channel-specific variants.
- Accessible mobile operation.
- Real performance and ROI reporting with data freshness.
- Extensible provider and integration boundaries.
- Explainable AI decisions, cost and provenance.
- Trust centre: health, failures, retries, audit and emergency controls.

## Final closure gate

The programme is not complete until two clients with different providers,
policies, libraries and connected accounts can run concurrently without any
cross-tenant read, write, task, usage log, engagement item, metric, lead or
publish. A duplicate scheduler tick must not duplicate work. A provider,
storage, social or metrics failure must remain visible and retryable. Every
success state must point to durable evidence.
