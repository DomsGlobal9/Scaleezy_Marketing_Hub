# PR6 — Application-wide screen & settings rationalization

Audit of every frontend route against the seven questions (job, still in
product, right location, backend real, UI wired, duplicated, legacy
dependency), with the disposition applied in code.

Baseline: `d102b12` on `marketinghub/merge`.

## Route dispositions

| Route | Job it serves | Disposition | What changed |
| --- | --- | --- | --- |
| `/` Overview | Where the work stands today | **FIX** | KPI tiles were eight hard-coded strings (`24.8K reach`, `3.8x ROI`) served to every workspace by `AnalyticsKPIView`; three whole sections (Connected Intelligence, the "Scaleezy Intelligence" diagram, two invented campaigns with reach/conv/ROI) were decoration. Replaced with real brand readiness + real pipeline counts, each tile linking to the screen that owns it. |
| `/brand-master` | Everything Scaleezy knows about a brand | **KEEP + MERGE target** | Was read-only showcase. Now the single intelligence home: Brand basics, Knowledge and Inspirations are operational inline, Rules is writable, Attention resolves conflicts, Teach Scaleezy embeds the PR6 flow. Tab is in the URL (`?tab=`), so every card/counter/CTA can target one. |
| `/onboarding` Brand Setup | Teaching a brand | **MERGE → `/brand-master?tab=teach`** | Competing permanent destination for the same job. Route kept as a redirect for deep links and resume; removed from navigation. |
| `/accounts` | Connect channels to publish through | **FIX** | Rebuilt on the real `SocialConnection` shape. Reconnect/Pause/Manage wrote to React state only; the ConnectDialog had a hard-coded "Scaleezy Fashion / Scaleezy Couture" account picker and a Connect button that fired `onConnected` without connecting; disconnect used bare `fetch` with no auth header; the audit table read a hard-coded `AUDIT_LOGS` constant. All now hit real endpoints (`connect`, `verify`, `disconnect`, `PATCH`) or are gone. |
| `/publishing` | Create → select channels → publish | **FIX** | Kept. Removed the fake "Save Draft"; wired Retry to `publishing/items/{id}/retry/` and View to `external_post_url`; the schedule date/time/timezone inputs were `defaultValue` decorations that never reached `scheduled_at` — now validated and sent. |
| `/review` | Approve before anything reaches an audience | **KEEP** | Already fully wired (list, tabs, counts, approve/reject/request-edits, feedback tags, poster studio). Its learning chain was broken at the backend — see below. |
| `/analytics` | Channel performance | **FIX** | Eight invented StatCards and four decorative filter dropdowns removed. Real publishing counts shown; charts keep their real (currently empty) sources with a truthful empty state that says metrics are not ingested yet rather than estimating them. |
| `/settings` | Workspace / account / provider config | **FIX** — see below | |
| `/login`, `/oauth/callback`, `/social/*/callback` | Auth and OAuth returns | **KEEP** | Real, wired, no changes. |
| `/privacy`, `/terms` | Legal | **KEEP** | Static by design. |

## Settings tabs removed / moved

Settings now contains only workspace/system/account/provider/permission
configuration. Everything removed either saved nowhere or belonged elsewhere.

| Panel | Disposition | Reason |
| --- | --- | --- |
| Brand Kit (name, industry, tagline, tone, CTA, logo, phone, poster toggles, default layout) | **MOVE → Brand Master ▸ Brand basics** | Brand intelligence. It was the only place to edit identity, which is why Brand Setup told users to "open brand settings". |
| Publishing defaults (behaviour, default account, allowed-from/until, daily limit, automatic retry) | **REMOVE** | Five inputs and a switch, all `defaultValue`/`defaultChecked`, none read on save, no backend column. The "Default account" list was three hard-coded handles. |
| Notifications (5 alert switches) | **REMOVE** | No notification system exists; no field to persist to. |
| Security ▸ "Require reauthorization every 60 days" | **REMOVE** | No-op toggle. |
| Security ▸ Active sessions | **REMOVE** | Two hard-coded people ("Anjali Manager · Chrome, Hyderabad"). No session store. |
| Role permissions matrix | **REMOVE (replaced)** | A static `PERMISSION_MATRIX` constant rendered as if it were configuration; nothing was editable and it did not read the backend's `ROLE_RANK`. Replaced by "Your access", which shows the caller's real memberships and roles from `/api/auth/me/`. |
| Workspace name / timezone / language | **FIX** | `Save changes` PUT the whole `workspace` object built from `defaultValue` inputs that were never bound, so it saved the loaded values back. Name is now bound, dirty-tracked, admin-gated (matching the server's ADMIN check) and reports real failures. Timezone and default language were removed: `MarketingWorkspace` stores them but nothing consumes them (`grep` finds only `admin.py`), so they were configuration with no effect. |
| Plan / usage | **KEEP** | Reads `/billing/`, read-only by design. |
| AI providers & routing | **KEEP** | Real catalogue/providers/routes/test endpoints; routes through AIRouter, does not bypass it. |
| OAuth connection history | **MOVE → Security panel, real data** | Now reads the `AuditLog` rows the publishing service actually writes. |

## Legacy functionality discovered

1. **Two writers to one Brand Brain.** `apps/feedback/training.py` wrote
   learned rules straight onto `Brand.creative_brain` — the column
   `apps/brands/services/brand_brain.py` owns and overwrites on every
   compile. Every rebuild silently deleted what the review loop had learned,
   and between rebuilds `brain_version` no longer described the snapshot's
   own contents. Fixed: review learning now writes a LEARNED, always-SOFT
   `learning.BrandRule` citing the `LearningEvent`s behind it, and the
   compiler picks it up like any other rule. `capture()` records the evidence
   before the training pass so a rule can name what it was learned from.
2. **`DEMO_ACCOUNTS` / `AUDIT_LOGS` / `PUBLISHING_HISTORY` / `MEDIA_ASSETS`**
   in `lib/marketing-data.ts` — empty arrays left over from the pre-API
   build, still used as initial state so a load failure looked like an empty
   product. Removed; the file now holds only platform vocabulary, plus a
   `supported` flag so Google Business (no adapter) is not offered as
   connectable.
3. **Sidebar "Shared Intelligence Layer" box** — copy describing CRM /
   Inventory / Finance integrations that do not exist in this product.
4. **`/onboarding` as a peer destination** — the Brand Setup vs Brand Master
   question the mission calls out.

## Broken / stale controls fixed

- Brand Brain went stale after every teaching action: nothing recompiled it
  except the manual Rebuild button, so readiness and generation read a
  snapshot from before the change. `rebuild_brand_brain_safely()` now runs
  after brand edits, logo changes, memory confirm/reject, source archive,
  inspiration archive, signal create/confirm/reject, rule create/deactivate,
  preference retire and review learning. Best-effort: the record is the
  truth, so a compile failure is logged, never raised into the write.
- Knowledge upload forced `source_type=DOCUMENT` and `title=filename`, so a
  transcript could not be stored as a transcript. Now declared by the caller
  and validated against the model's choices.
- Knowledge had no UI at all beyond a read-only list — no upload, no text
  paste, no link, no fact capture, no archive. Now full inline PR1.
- Inspirations had no add path and no way to state a preference; the only
  action was confirm/reject on AI signals that cannot exist yet. Now full
  inline PR2 with USER-origin signals.
- Readiness dimensions and overview counters were display-only; each is now
  a link to the tab that fixes it.
- Attention showed conflicts with no resolution path. Each conflicting claim
  now has the action that settles it (reject fact / withdraw preference /
  deactivate rule / retire preference).
- Publishing schedule inputs, per-item retry, post permalink (above).

## Remaining intentional surfaces

- **Analytics charts** render real, currently-empty series. Nothing ingests
  reach/engagement/conversion metrics yet; the page says so instead of
  estimating. `DailyMetric`, `PlatformPerformance` and `CampaignROI` have no
  writer anywhere in the codebase — a genuine gap, not a wiring defect.
- **Automatic document reading** (`sources/{id}/process/`) and **automatic
  inspiration analysis** (`inspirations/{id}/analyze/`) return 501. Neither
  is exposed as a button; the copy states the capability is unavailable and
  facts/signals are captured by hand.
- **Google Business Profile** is listed with no Connect action — no OAuth
  adapter exists.
- **`src/components/ui/form.tsx`** fails typecheck against react-hook-form
  7.85 (pre-existing, unrelated, no route imports it).
