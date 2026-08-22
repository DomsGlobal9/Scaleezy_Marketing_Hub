# WO-09 — Application-wide UI functional audit

Every interactive element traced handler → payload → endpoint → backend reader.
154 elements across 11 routes and 6 shared components.

Baseline `d102b12`. Gates: `tsc --noEmit` clean, `vite build` clean.
Files changed: `Marketing_Frontend/src/routes/_hub.publishing.tsx`,
`Marketing_Frontend/src/routes/_hub.analytics.tsx`. No backend change.

**Totals — KEEP 109 · FIX 23 · DISABLE 15 · REMOVE 7.**
Applied in code: 17 FIX, 15 DISABLE, 6 REMOVE. Seven findings on residual
surfaces were audited but left alone (listed at the end).

Tables below list only elements that changed. Everything not listed was traced
to a real reader and kept.

## Publishing — `_hub.publishing.tsx` (68 elements, 45 KEEP)

| Element | Kind | Disposition | Evidence |
| --- | --- | --- | --- |
| Video Duration / Aspect ratio / Style selects | WRITE | **DISABLE** | Not in `generate_async`'s brief allowlist (`apps/gemini/views.py:351-362`); zero backend hits for `videoDuration`/`video_duration`. Controls disabled, keys stripped from the body. |
| Script / voiceover Textarea | WRITE | **DISABLE** | Same allowlist. Placeholder also promised "Leave blank to let AI write it" for text discarded server-side — promise removed. |
| Show brand logo / Show phone number / Phone override | WRITE | **DISABLE** | `grep -rni "logo\|phone" apps/gemini/` matches only test fixtures. The overlay lives at `apps/layouts/render.py:_overlay_logo/_overlay_phone`, reached by `/api/marketing/layouts/*`, which Publishing never calls. Brand-level defaults work; the per-generation override never existed. Copy now says so. |
| `logoUrl` payload key (no UI) | WRITE | **REMOVE** | No control, no reader. `apps/layouts/serializers.py` deliberately exposes no image-URL field. |
| `slideCount` payload key | WRITE | **REMOVE** | Derived from `slides.length`, no reader; `slides` itself is persisted (`apps/gemini/tasks.py:97,111`). |
| GripVertical slide handle | DISPLAY | **REMOVE** | Drag affordance with no `draggable`, no pointer handlers, no drag library. Reorder is the Move buttons. |
| Job Progress dialog + Retry Failed + Done | DISPLAY/ACTION | **REMOVE** | `open={!!jobs}` and `setJobs` was only ever called with `null`. ~65 lines that could not render. |
| "AI is working" panel | DISPLAY | **FIX** | Reached from three flows, always claimed to analyse an image. Copy now derives from the flow, and generation gets a Cancel that aborts the fetch and the poll rather than trapping the user for the 10-minute ceiling. |
| Reference-image analysis result | READ | **FIX** | `apiFetch` does not throw on non-2xx, so `{success:false}` fell through silently. Both branches now toast. |
| Hidden file input | ACTION | **FIX** | `value` never cleared, so re-picking the same file after a removal or failure fired no change event. Cleared on entry. |
| "Back to Dashboard" button | NAV | **FIX** | `setStep("create_or_upload")` — rewinds the wizard. Relabelled "Start over"; the header link is the dashboard. |
| Social account checkbox | WRITE | **FIX** | Ignored `publishing_enabled`, which the publisher uses to `continue` past the connection (`apps/publishing/views.py:90-91`), and allowed TOKEN_EXPIRED. New `canPublishTo` gates on CONNECTED + enabled + format, with a "Publishing Off" marker. |
| `selected` lifecycle | WRITE | **FIX** | Only setter was `toggle`. A YouTube pick survived a swap from video to poster and a completed publish. Now pruned on change and cleared after publish. |
| Accounts list container | DISPLAY | **FIX** | No loading and no empty state — a bare heading over a permanently disabled Publish button. |
| "Only connected accounts…" footnote | DISPLAY | **FIX** | Was untrue on both counts; the checkbox now implements it, so the sentence stands unchanged. |
| PUBLISH button | ACTION | **FIX** | Fell back to `asData[0].id` from `/assets/` when no image was attachable. `MarketingAsset` has no `Meta.ordering`, so it published an arbitrary earlier asset to live accounts under the new caption. Fallback removed; a failed upload now throws. |
| History Retry | ACTION | **FIX** | POSTed `/publishing/items/<id>/retry/`; the action is `detail=False` on the jobs router, so the path is `/publishing/jobs/items/<id>/retry/` (`apps/common/tests.py:122`). Every retry 404'd. |
| History Content cell + mobile title | DISPLAY | **FIX** | Read `row.asset`; `loadHistory` sets `content`. Both columns were permanently blank. |
| History mobile error line | DISPLAY | **FIX** | Guarded on `row.error !== "—"` while the value is `null`, so an empty red line rendered on every card. |
| History table + mobile list | DISPLAY | **FIX** | Empty, loading and load-failure were indistinguishable. |

## Analytics — `_hub.analytics.tsx` (22 elements, 7 KEEP)

| Element | Kind | Disposition | Evidence |
| --- | --- | --- | --- |
| Six ChartCards (Reach, Engagement, Platform Performance, Platform comparison, Conversion trend, Campaign ROI) | READ | **DISABLE** | Bound to `DailyMetric` / `PlatformPerformance` / `CampaignROI`. A repo-wide sweep including tests, fixtures, admin and management commands finds only reads; `admin.py` is an empty stub, so not even a manual insert is possible. Recharts with `data={[]}` still paints grid, axes and a provenance badge, which reads as measured zero. Card frames kept, plot areas replaced with a "Not available yet" panel. |
| Provenance badges ("Daily metrics", etc.) | DISPLAY | **DISABLE** | Label is accurate, effect is not: a provenance pill asserts a live feed behind six permanently empty charts. |
| `GET /analytics/dashboard/` | READ | **DISABLE** | Structurally guaranteed to return three empty lists. A bare GET, so there was no payload to strip — the request itself was the inert part. Removed. |
| Platform performance table + mobile cards | READ | **DISABLE** | Header row over nothing, and a wholly blank surface on mobile. Also retired `row.roi` (serializer emits `roi_multiplier`) and an unguarded `row.reach.toLocaleString()`. |
| SectionTitle description | DISPLAY | **FIX** | "…from ingested metrics." claimed a running pipeline. Now "…once a metrics source is connected." |
| KPI loading skeleton | DISPLAY | **FIX** | `loading={kpis === null}` sat inside a `.map` over `(kpis ?? [])`, empty exactly when `kpis` is null. Branches before the map now, matching `_hub.index.tsx:178`. |
| KPI fetch error handling | READ | **FIX** | `.catch(() => setKpis([]))` turned a 403 or 500 into "nothing published". Now the typed `api()` helper with a `kpiError` band, mirroring Overview. |
| Dead `Select`* and icon imports (11) | — | **REMOVE** | Residue of the filters and invented tiles deleted in `22427b0`; `noUnusedLocals:false` hid them from tsc. |

## Review / Poster Studio / Feedback tags (24 elements, 24 KEEP)

No changes. All 24 reach implemented handlers; no inert payload key, no
unbuilt control exposed. The training-report contract still matches field for
field after the move to `learning.BrandRule` in `22427b0`, so the panel renders.
Ordering changed from `-occurrences` to `-updated_at`, so the five shown are the
freshest rather than the most-raised — cosmetic, data honest.

## Residual surfaces — root shell, /login, /privacy, /terms, 4 OAuth callbacks, shared components (40 elements, 33 KEEP)

Audited, **not applied** — outside the finding lists this work order was given.

| Element | Kind | Disposition | Evidence |
| --- | --- | --- | --- |
| `twitter:site` `@Lovable` (`__root.tsx:100`) | DISPLAY | REMOVE | Scaffold leftover; attributes every share card to another company. |
| `twitter:card` with no `og:image` (`__root.tsx:99`) | DISPLAY | FIX | Requests a large-image card the head never supplies. |
| favicon link (`__root.tsx:113`) | DISPLAY | FIX | PNG declared `image/x-icon`, and `public/favicon.png` is 1.38 MB per page load. |
| X callback error handling (`oauth.callback.tsx:16`) | ACTION | FIX | Ignores `error`/`error_description`, so a declined consent reports "Invalid OAuth callback parameters." Its three siblings handle it. |
| X callback body (`oauth.callback.tsx:59`) | DISPLAY | FIX | Spinner only; failures reported by a toast on the page the user is being bounced away from. |
| LinkedIn callback re-entry guard (`social.linkedin.callback.tsx:16`) | ACTION | FIX | The only one of four without the `fired` ref on a single-use authorization code. Latent, not live — `useNavigate` is stable and StrictMode is not mounted. |
| Usage panel fetch (`usage-panel.tsx:49`) | READ | FIX | Error swallowed then `return null`, inside a titled Panel — a card headed "Usage this period" containing nothing, with no way to tell failure from no data. |

No dead links anywhere: every `Link`/`navigate`/`href` target resolves against
`routeTree.gen.ts`. `?redirect=` is not an open redirect (`safeInternalPath`).
All four OAuth callbacks gate success on the backend envelope; none can hang.

## Backend gaps discovered but NOT implemented

WO-09 forbids backend change. Each of these needs one.

1. **Per-generation poster overrides.** `apps/layouts` already accepts
   `include_logo` / `include_phone` / `phone` and honours them; no client sends
   them, and `apps/gemini` reads none of them. A frontend-only fix exists but
   belongs to PosterStudio on `/review`, not to Publishing — scope-widening, not done.
2. **Video generation.** `generate_marketing_content` returns text plus a still
   poster. The Video tile still offers "A short promo clip" and the result is a
   poster named `.mp4`. Disabling the four sub-controls does not fix the parent tile.
3. **Video parameters.** No model field, no prompt field, for duration, aspect
   ratio, style or script.
4. **Analytics ingestion.** Nothing writes `DailyMetric`, `PlatformPerformance`
   or `CampaignROI`. Until a writer exists the six charts and the table cannot
   be re-enabled honestly.
5. **Analytics key mismatch.** If ingestion is built, note the charts read
   `month` / `posts` / `campaign` / `roi` while the serializers emit `date` /
   `posts_published` / `campaign_name` / `roi_multiplier`.
6. **`contentItemId` on the async path.** `pollGeneration` returns `null`
   because `GeminiGenerationResultSerializer` exposes no content-item id, so
   every video and carousel publish skips the approval gate.
7. **Learned-rule data migration.** Rules written to `Brand.creative_brain`
   before `22427b0` are not carried into `learning.BrandRule`, and no migration
   exists. Affected tenants see the panel fall back to the review count.
8. **`ai_prompt` stores a base64 blob.** On the sync path `_persist_content`
   receives raw `request.data`, so `ai_prompt=str(brief)[:5000]` records a
   truncated image whenever a reference image was sent.
9. **AI routing (frozen, report only).** `setRoute` deletes every route for a
   capability before creating the replacement, so a failed create leaves it
   unrouted; and both routing selects stay enabled for non-admins although the
   viewset requires ADMIN.

Correction to `PR6_UI_RATIONALIZATION.md`: it records Retry as wired to
`publishing/items/{id}/retry/` and the charts as rendering "real, currently-empty
series". The first path 404s and four of the six charts were mis-keyed as well
as unfed. Both are addressed above.
