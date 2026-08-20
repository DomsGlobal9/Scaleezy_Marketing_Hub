# Marketing Hub → Content Engine: Enhancement Plan

Bringing the capabilities specified in `Content_Engine_v2_Complete_Package` into the existing
Scaleezy Marketing Hub, without discarding what already works.

**Target:** one complete, coherent module — generate → review → approve → publish → learn.

---

## Locked decisions

| Decision | Choice | Why |
|---|---|---|
| Backend framework | **Stay on Django 6.1 + DRF** | The spec assumes FastAPI. A port costs weeks and buys nothing — every capability below works in Django. |
| Auth | **JWT now, Django's default `User`** | Closes the real risk (`AllowAny` + open CORS + encrypted tokens) without a painful `AUTH_USER_MODEL` swap. |
| Vector search | **pgvector on existing Supabase Postgres** | No new vendor, no new bill, no extra service. Comfortably handles this scale. |
| AI providers | **Open-ended registry, DB-driven, per-customer on/off, routed per capability** | Broader than the spec's fixed 5: any number of providers, switchable per customer from an admin console, and assignable per task — one AI for copy, another for images, another for video, or several competing on the same task. |
| Tenancy | **Row-scoped by workspace + enforced auth** | Not schema-per-tenant. `customer_id` already implies the parent Scaleezy system owns real tenancy. |
| Async | **Deferred to Phase 8, and not Celery by default** | Only video and multi-slide carousels genuinely need it. |

---

## What we keep (untouched)

The spec has **no equivalent** for most of this. It stops at generating and exporting files; it never
publishes anywhere.

- **Publishing stack** — `SocialConnection`, `SocialAccountSettings`, `SocialAccountAuditLog`,
  the `SocialPlatformAdapter` family (X, YouTube, Meta, LinkedIn), Fernet token encryption,
  `PublishingJob` → `PublishingJobItem` fan-out with independent per-channel retry.
- **Asset storage** — `MarketingAsset` + Supabase Storage bucket.
- **Analytics** — `DailyMetric`, `PlatformPerformance`, `CampaignROI`.
- **Frontend** — TanStack Start app, the publishing wizard (poster / video / carousel with the
  ordered slide planner), brand-kit UI, legal pages, `APIResponse` envelope.

The `SocialPlatformAdapter` pattern is also the **template** for the AI provider layer in Phase 5 —
we mirror a proven in-house pattern rather than importing the spec's plugin registry wholesale.

---

## Phase plan

Ordered by dependency. Each phase leaves the app working.

### Phase 1 — Identity, tenancy & access control

Everything later writes `created_by` and must be workspace-scoped. Doing this first means each
endpoint is written once.

**Models**
- `WorkspaceMember` — `user` FK, `workspace` FK, `role` (`OWNER`/`ADMIN`/`MANAGER`/`EDITOR`/`VIEWER`),
  `status`, unique `(user, workspace)`. Django's default `User` has no workspace link; this supplies it.

**Work**
- `djangorestframework-simplejwt`: `/api/auth/login/`, `/refresh/`, `/me/`.
- `IsWorkspaceMember` + `HasRole` permission classes; a `WorkspaceScopedQuerySet` mixin.
- Replace `AllowAny` on every viewset; scope every queryset by the caller's workspace.
- Lock `CORS_ALLOW_ALL_ORIGINS` down to an explicit allowlist.
- Frontend: login screen, token storage + refresh interceptor, 401 handling.
- Make the existing static `PERMISSION_MATRIX` reflect real server-side roles.

**Done when** no endpoint returns data without a valid token, and a member of workspace A cannot
read workspace B.

---

### Phase 2 — Brand

Currently the brand kit is **logo + phone in `localStorage`**. The spec needs a real brand record —
and every AI prompt, layout and training rule keys off it.

**Model** — `Brand` (workspace FK): `name`, `industry`, `palette` JSON, `fonts` JSON, `tagline`,
`cta_keyword`, `instagram_handle`, `competitors` JSON, `creative_brain` JSON, `layout_preference`,
`logo_asset` FK, `contact_phone`, `show_logo_on_posters`, `show_phone_on_posters`, `status`.

**Work**
- CRUD API; migrate the Settings brand-kit panel from `localStorage` → API.
- Upload the logo to the Supabase bucket (the `logoUrl` field already reserved in
  `brand-settings.ts` finally gets populated).
- `creative_brain` JSON is the destination for Phase 6's learned rules.

**Done when** brand data survives a browser change and drives poster generation server-side.

---

### Phase 3 — ContentItem: persist what we generate

**Today Gemini output is thrown away.** `gemini/generate/` returns captions and an image URL
without writing a row — `GeminiGenerationRequest`/`Result` exist but are never populated. Headlines,
captions and hashtags live only in React state.

**Models**
- `ContentItem` (workspace, brand, asset FKs): `format` (`STATIC`/`CAROUSEL`/`VIDEO`/`REEL`),
  `status`, `version`, `parent` (self-FK for revisions), `headline`, `caption`, `cta`,
  `hashtags`, `image_versions` JSON, `ai_provider`, `ai_model`, `ai_prompt`, `ai_cost`,
  `layout_plugin`, `layout_config` JSON, `engagement_score`, `created_by`.
- `ContentSlide` — `content_item` FK, `position`, `description`, `asset` FK.
  Maps directly onto the carousel slide planner already built in the UI.

**Work**
- Wire `gemini/generate/` to persist `GeminiGenerationRequest` → `Result` → `ContentItem`.
- Content list/detail/update endpoints.
- `PublishingJob` gains an optional `content_item` FK, so a post traces back to its source.

**Done when** every generation produces a durable row and nothing is lost on refresh.

---

### Phase 4 — Review & approval loop

The front half of the spec's core loop, and completely absent today: generation goes straight to
publishing with no human gate.

**Work**
- Status machine on `ContentItem`:
  `DRAFT → GENERATING → PENDING_REVIEW → APPROVED | NEEDS_EDITS | REJECTED → PUBLISHED`.
- Endpoints: `POST /content/{id}/approve/`, `/reject/`, `/request-edits/`.
- **Review screen** (spec §7.3): tabs for Pending / Approved / Needs edits / Rejected, a content
  grid, and a card with approve / edit / reject actions.
- **Publishing gated on `APPROVED`** — a genuine behaviour change: today anything can be published.
- `NEEDS_EDITS` spawns a new `version` linked via `parent`.

**Done when** nothing reaches a social platform without an explicit human approval.

---

### Phase 5 — Pluggable AI provider layer *(your key requirement)*

Open-ended, DB-driven, switchable per customer from the console — and **routed per capability**:
one provider may handle copy, another images, another video; or several may compete on the same
task. Mirrors `SocialPlatformAdapter`.

**Capabilities** are the routing unit, not the provider:

| Capability | Used by | Today |
|---|---|---|
| `TEXT` | headline, caption, hashtags | Gemini |
| `IMAGE` | poster / carousel slides | Gemini |
| `IMAGE_ANALYSIS` | the reference-image auto-fill | Gemini |
| `VIDEO` | promo clips (Phase 3 format) | nothing |

**Models**
- `AIProvider` (global catalogue) — `key` (`gemini`, `openai`, …), `display_name`,
  `capabilities` (set of the above), `default_model`, `is_available` (global kill switch),
  `unit_cost`.
- `WorkspaceAIProvider` (account-level, per customer) — `workspace` FK, `provider` FK, `enabled`,
  `credentials_encrypted` (Fernet, same helper as the OAuth tokens), `model_override`,
  `config` JSON. Unique `(workspace, provider)`. **This is the on/off switch.**
- `WorkspaceAIRoute` (per capability) — `workspace`, `capability`, `provider`, `priority`,
  `enabled`. Unique `(workspace, capability, provider)`. **This is what says "OpenAI for images,
  Gemini for copy".**
- `AIUsageLog` — `workspace`, `provider`, `capability`, `content_item`, `units`, `cost`,
  `latency_ms`, `success`, `error`.

**Routing strategies** — per `(workspace, capability)`, so a customer can mix:
- `FAILOVER` (default) — try `priority` order, first healthy provider wins.
- `BEST_OF` — fan out to every enabled provider for that capability, score on
  quality × cost × latency, keep the winner. This is the spec's `generate_with_best`, and the
  "all work on the same" case. Costs N× per generation, so it's opt-in per capability.
- `ROUND_ROBIN` — spread load and spend across providers.

**Code**
- `AIProviderAdapter` ABC: `generate_text`, `generate_image`, `analyze_image`, `generate_video`,
  `health_check`, `estimate_cost`. A provider implements only the capabilities it declares.
  Adding a provider = one new file + one catalogue row. No core changes.
- `registry.py` — auto-discovers adapters by `key`.
- `AIRouter.dispatch(capability, workspace, context)` — resolves the route for that capability,
  filters to enabled + healthy + credentialed, applies the strategy, writes `AIUsageLog`.
  Callers ask for a *capability*, never a provider.

**Console**
- Django admin for the global catalogue.
- Frontend **Settings → AI Providers**, two tiers:
  1. *Providers* — per-provider toggle, credential entry, *Test connection* (`health_check`).
  2. *Routing* — one row per capability, drag-to-order the providers assigned to it, pick the
     strategy. This is where "images → OpenAI, copy → Gemini" is expressed.

**Done when** a customer can be switched from Gemini to another provider for images only, leaving
copy untouched, without a deploy.

---

### Phase 6 — Feedback capture & training engine

The spec's stated reason for existing, and currently 0% present.

**Models**
- `Feedback` — `content_item`, `user`, `verdict` (`approve`/`needs_edits`/`reject`),
  `element_tags` array, `feedback_text`, `fix_request`, `sentiment`, `urgency`,
  `before_asset` / `after_asset`, `pattern_extracted` JSON, `rules_updated` JSON.
- `embedding` — `pgvector` `VectorField` on `Feedback`, with an IVFFlat index.

**Work**
- Enable the `vector` extension on Supabase; add `pgvector`.
- Tag-picker UI on the review card, driven by the element vocabulary (**blocked — see below**).
- `TrainingEngine`: embed → find similar past feedback → extract pattern → append rule to
  `Brand.creative_brain` → surface a training report.
- Learned rules feed back into the next generation's prompt.

**Done when** rejecting a poster for the same reason twice measurably changes the next prompt.

---

### Phase 7 — Layout & export engine

The zip ships working PIL code (`poster_patterns_v2.py`, `build_daily.py`) — port it rather than
rewrite.

- Layout plugins: `agency_column`, `jil_sander`, `cos_split`, `data_hero`, `ghost_word`, `vs_table`.
- Compose posters **locally from brand palette + fonts + photo**, instead of asking Gemini for the
  whole image. This is what makes output consistently on-brand.
- Export sizes per platform: IG 1080×1350 / 1080×1080 / 1080×1920, FB 1200×630, X 1600×900,
  LinkedIn 1200×627, plus PDF.
- Logo and phone overlays (already wired through the UI) get applied here, server-side.

---

### Phase 8 — Async, quotas & cost control

- Move video and carousel generation off the request thread. Publishing is already synchronous and
  will hit gateway timeouts at scale.
- `Subscription` + quota checks before generation; `AIUsageLog` aggregates into spend caps.
- Scheduled publishing finally executes — `publish_mode=SCHEDULED` currently creates a job that
  nothing ever runs.

---

## Sequencing

```
Phase 1 Auth ──▶ Phase 2 Brand ──▶ Phase 3 ContentItem ──▶ Phase 4 Review
                                          │                      │
                                          └──▶ Phase 5 AI ◀──────┘
                                                    │
                                          Phase 6 Feedback/Training
                                                    │
                                    Phase 7 Layout ─┴─ Phase 8 Async/Quotas
```

Phases 1–4 are the spine; nothing else is stable without them. Phase 5 can run in parallel with 3–4
once `ContentItem` exists.

---

## Blocked — needs your colleague

**The 52-element feedback vocabulary is never enumerated.** `CREATIVE_BRAIN.md` lists nine group
names with counts — Typography (8), Copy & Message (10), Line-by-line (10), Logo & Branding (6),
Visual & Background (6), Layout (5), Audio (3), Format & Technical (4), Strategy (4) — but no
element names anywhere in the package.

Those counts also **sum to 56, not 52**.

This taxonomy is the input to the whole training engine, so it can't be guessed. Phase 6 needs the
actual list before the tag picker or pattern extraction can be built. Phases 1–5 and 7 are
unaffected.

---

## Also worth noting

- **Two audit systems** already exist (`AuditLog` with denormalised strings, `SocialAccountAuditLog`
  with real FKs). Phase 1 is the natural point to collapse them.
- **`MarketingAsset.generation_id`** is a soft reference duplicating `GeminiGenerationResult.asset`.
  Phase 3 should remove one.
- **`PublishingJob` CASCADE-deletes with its asset** — deleting an asset destroys its publishing
  history. Worth changing while touching these models.
