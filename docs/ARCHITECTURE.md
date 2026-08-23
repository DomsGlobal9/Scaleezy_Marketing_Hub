# Scaleezy Marketing Hub — Architecture

End-to-end reference: schema, data flow, references, and how to plug in other modules.

- **Backend** — `Marketing_backend/`, Django 6.1 + DRF 3.18, Postgres (Supabase)
- **Frontend** — `Marketing_Frontend/`, TanStack Start + React 19 + Tailwind v4
- **Storage** — Supabase Storage bucket `Marketing_Poster_images`
- **AI** — Google Gemini (`google-genai`)
- **Async** — none. Everything is synchronous DRF request/response.

---

## 1) Schema

30 tables across 16 model-bearing Django apps (18 local apps; `apps.common` and `apps.layouts` hold no models). Every primary key is a UUID. Every business table hangs off `MarketingWorkspace`.

### Tenancy (`apps.workspaces`)

**`marketing_workspaces`** — the tenant root.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `customer_id` | varchar(255) | **Soft reference** to the customer in the main Scaleezy system. Deliberately not an FK — that system owns its own DB. |
| `workspace_name` | varchar(255) | |
| `timezone` | varchar(50) | default `UTC` |
| `default_language` | varchar(10) | default `en` |
| `created_at` / `updated_at` | timestamp | |

### Social accounts (`apps.social_accounts`)

**`social_connections`** — one row per connected channel.

Identity: `platform` (7 choices), `account_type`, `external_account_id`, `account_name`, `username`, `profile_url`, `profile_image_url`.
Who connected it: `connected_user_id`, `connected_user_name`, `connected_user_email`, `user_role`, `connected_by` (FK → User).
OAuth: `oauth_provider`, `oauth_user_id`, `scopes`.
Secrets: `access_token_encrypted`, `refresh_token_encrypted` — Fernet ciphertext, never plaintext, never serialized to the client.
Token lifecycle: `token_created_at`, `token_expires_at`, `last_token_refresh_at`.
State: `status` (11 choices), `publishing_enabled`, `is_default_account`, `reauthorization_required`, `last_error`, `last_verified_at`, `last_published_at`, `connected_at`, `disconnected_at`.

Constraint: `UNIQUE (workspace, platform, external_account_id)` — the same Instagram account can't be connected twice to one workspace.

Enums:
- `Platform` — `FACEBOOK`, `INSTAGRAM`, `LINKEDIN`, `X`, `TIKTOK`, `YOUTUBE`, `GOOGLE_BUSINESS`
- `Status` — `NOT_CONNECTED`, `CONNECTING`, `CONNECTED`, `PERMISSION_MISSING`, `TOKEN_EXPIRED`, `REAUTHORIZATION_REQUIRED`, `REVOKED`, `CONNECTION_FAILED`, `PUBLISHING_DISABLED`, `DISCONNECTED`, `PLATFORM_UNAVAILABLE`

**`social_account_settings`** — OneToOne with a connection. `timezone`, `allowed_start_time`, `allowed_end_time`, `daily_post_limit` (default 10), `automatic_retry_enabled`, `comments_enabled`, `analytics_enabled`, `publishing_paused`.

**`social_account_audit_logs`** — FK'd audit trail. `workspace`, `social_connection`, `user`, `action` (11 choices), `old_value`, `new_value`, `error_message`, `ip_address`, `user_agent`.

### Assets (`apps.marketing`)

**`marketing_assets`** — metadata only; bytes live in Supabase Storage.

`asset_type` (`POSTER`/`IMAGE`/`VIDEO`/`OTHER_SUPPORTED_ASSET`), `source` (`GEMINI_GENERATED`/`MANUAL_UPLOAD`), `file_name`, `file_url`, `storage_path`, `mime_type`, `file_size`, `width`, `height`, `duration`, `generation_id` (soft ref to a Gemini result), `created_by`.

### Brand Kits & Layouts (`apps.brands` & `apps.layouts`)

**`brands`** — Centralized brand identity. `logo_url`, `primary_color`, `secondary_color`, `font_family`.
**`apps.layouts`** — Compose posters natively strictly adhering to the configured brand identity.

### Content Generation & Feedback (`apps.content` & `apps.feedback`)

**`content_items`** — Stores generated content before publishing. Subject to a human-in-the-loop review gate.
**`feedback_elements`** & **`feedback`** — Tracks explicit human reviewer verdicts (e.g. tone too casual) to continuously reinforce and optimize the AI model.

### AI Orchestration (`apps.ai` & `apps.gemini`)

**`ai_providers`**, **`workspace_ai_providers`**, **`workspace_ai_routes`** — Dynamic provider layer for routing capabilities to models based on cost, context, and configurations.
**`ai_usage_logs`** — Tracks provider usage.
**`gemini_generation_requests`** & **`gemini_generation_results`** — Context-aware orchestration engine specific to Gemini endpoints.

Tenant-owned custom providers are Admin-only. An administrator explicitly supplies the provider name, model, public HTTPS API endpoint, optional encrypted credential, protocol and supported capabilities; Scaleezy does not preselect any of them. OpenAI-compatible endpoints may declare the standard text, image, vision/caption and embedding contracts. A Scaleezy universal JSON endpoint may declare any capability, including video, by accepting `{capability, model, brief}` and returning a normalized result. Custom provider rows are visible only to their owning workspace. Product workflows remain provider-neutral and call only `AIRouter` capabilities.

`workspace_ai_providers.capabilities` is the selected client's editable assignment of tasks to one configured provider/model. It may only contain capabilities that the installed adapter can actually execute. Removing an assignment atomically removes that provider from the corresponding workspace route; routing can never override the assignment or the adapter's technical capability ceiling.

### Publishing & Jobs (`apps.publishing` & `apps.jobs`)

**`publishing_jobs`** — one user action. `workspace`, `asset`, `created_by`, `status` (8 choices), `publish_mode` (`NOW`/`SCHEDULED`), `scheduled_at`, `timezone`, `created_at`, `started_at`, `completed_at`.

**`publishing_job_items`** — one row per target channel. This is the fan-out and the job↔connection join.

**`task_runs`** — Durable, queue-based background task runner to handle resilient social publishing independent of the web request lifecycle.

### Analytics & Billing (`apps.analytics` & `apps.billing`)

**`plans`** & **`subscriptions`** — SaaS tiering ensuring soft and hard AI spend limits.

| Table | Grain | Columns |
|---|---|---|
| `analytics_daily_metrics` | `(workspace, date)` | reach, engagement, posts_published, conversions |
| `analytics_platform_performance` | `(workspace, platform)` | reach, engagement, clicks, conversions, roi_multiplier |
| `analytics_campaign_roi` | `(workspace, campaign_name)` | roi_multiplier |

These are **stored aggregates**, not derived at query time from publishing data.

### Audit (`apps.audit`)

**`audit_logs`** — denormalized. `workspace` (FK) but `user`, `platform`, `account` are plain strings. `date`, `action`, `previous_state`, `next_state`, `result`, `error`.

### Brand knowledge (`apps.knowledge`, PR1)

**`knowledge_brandsource`** — the raw material a brand hands over: uploads, pasted text, links, transcripts. `workspace`, `brand`, `source_type` (14 choices), `title`, `source_url` / `storage_path` / `file_url` / `raw_text`, `mime_type`, `language`, `status` (`UPLOADED` → `QUEUED`/`PROCESSING`/`READY`/`NEEDS_REVIEW`/`FAILED`/`ARCHIVED`), `content_hash`, `metadata`, `created_by`.

**`knowledge_brandmemory`** — structured facts extracted from a source. `source` (nullable FK), `memory_type` (13 choices), `content`, `confidence`, `scope`, `permanence`, `status` (`CANDIDATE`/`CONFIRMED`/`REJECTED`/`SUPERSEDED`/`EXPIRED`), `valid_from`/`valid_until`, `supersedes` (self-FK).

Extraction itself is not implemented: `POST /api/marketing/knowledge/sources/{id}/process/` returns `501` until PR6.

### Brand inspirations (`apps.inspirations`, PR2)

Separate from knowledge on purpose. A source says what is *true* about a business; an inspiration says what its work should *feel* like, and carries two kinds of claim that must never be confused — what a person stated, and what a model inferred.

**`inspirations_brandinspiration`** — one reference. `workspace`, `brand`, `source` (nullable FK → `knowledge_brandsource`, the provenance link), `inspiration_type` (13 choices: image, screenshot, URL, web page, post, reel, video, ad, pin, competitor, reference, moodboard, other), `title`, `annotation` (the user's own words), `reference_url` / `storage_path` / `file_url` / `mime_type` / `file_name`, `external_platform` (free text — the platform is metadata, not an integration), `metadata`, `usage_scope` (`FULL_REFERENCE` / `SPECIFIC_ELEMENTS`) with `focus_areas`, `analysis_status` (`NOT_ANALYSED` only, until PR6), `lifecycle_status` (`ACTIVE`/`ARCHIVED`), `created_by`, `archived_by`/`archived_at`.

**`inspirations_inspirationsignal`** — one extracted or stated preference. Holds **no** workspace or brand column: tenancy is read through `inspiration`, so there is no second copy to drift. `category` (17 choices), `attribute`, `value`, `sentiment` (`LIKED`/`DISLIKED`/`NEUTRAL`, always explicit and independent of `weight`), `weight`, `confidence`, `origin` (`USER`/`AI`, immutable), `user_confirmation` (`CONFIRMED`/`PENDING`/`REJECTED`), `conflicts_with` (self-FK), `extracted_by_provider`, `created_by`, `confirmed_by`/`confirmed_at`, `superseded_at`/`superseded_by`/`superseded_reason`, and the folded copies `normalized_attribute`/`normalized_value`.

**Preference authority.** For one `(inspiration, category, normalized_attribute)` exactly one stated preference is the answer: the latest USER-origin signal that is `CONFIRMED` and not superseded. Preferences are append-only — changing your mind writes a new row and retires the old one, which stays readable with a record of what replaced it and why (`SUPERSEDED_BY_NEWER_USER_SIGNAL`, `SUPERSEDED_BY_CONFIRMED_AI_DIRECTION`, `SUPERSEDED_BY_NEWER_AI_INFERENCE`). `superseded_at`, not the foreign key, is what "active" is read from, so nulling the FK cannot revive a historical preference.

An inference **conflicts** when its folded value differs from the authority's *or* its sentiment does — either half is enough. Conflict is derived, not remembered: `services.reconcile_attribute()` recomputes it after anything that can move authority. Confirming a contradicting inference explicitly supersedes the preference it contradicts, so the brand never holds two opposite active truths; the inference keeps `origin=AI`, because a human accepted it, they did not author it. Supersession is one-way: rejecting the current preference leaves the attribute without one rather than reviving its predecessor.

Constraints: `UNIQUE (inspiration, category, normalized_attribute) WHERE origin='USER' AND superseded_at IS NULL AND user_confirmation='CONFIRMED'` — the database, not just the service, refuses two simultaneous authorities. `UNIQUE (…) WHERE origin='AI' AND superseded_at IS NULL` — a retried analysis job refreshes one row instead of piling up duplicates. `CHECK NOT (superseded_by_id = id)` — PR1-011; longer cycles are unreachable because superseding a row deactivates it and only active rows are ever superseded.

`BrandInspiration.save()` refuses a brand from another workspace, or a source from another workspace or brand. The serializers already reject those, but they only guard requests — jobs and management commands write through the ORM, where a mismatched row would afterwards look like ordinary data rather than a breach.

Retrieval eligibility is a query, not a flag: `BrandInspiration.objects.eligible_for_retrieval()` drops archived references and references whose source was archived. `InspirationSignal.objects.eligible_for_retrieval()` additionally drops superseded rows, user-rejected rows, inferences that contradict a stated preference, and inferences about an attribute that already has one — the last whether the inference agrees or not, because two rows saying the same thing get counted twice by anything that weighs signals. The net effect is **at most one retrievable signal per attribute**. The API exposes the same rule as `?eligible_only=true` and reports each row's verdict in `retrieval_eligibility`, which is checked against the queryset by `test_row_verdict_and_queryset_agree`.

Analysis is not implemented: `POST /api/marketing/inspirations/{id}/analyze/` returns `501` until PR6. Nothing in PR2 fetches a reference URL or calls a provider.

---

## 2) What we store, and how data flows

### Storage split

| Where | What |
|---|---|
| Postgres (Supabase) | All 12 tables — metadata, state, audit |
| Supabase Storage | Actual image/video bytes, bucket `Marketing_Poster_images`, path `workspace/{workspace_id}/{uuid}_{filename}` |
| Fernet-encrypted DB columns | OAuth access/refresh tokens |
| Never stored | Social passwords. Authorization happens on the platform's own OAuth page. |

`FERNET_SECRET_KEY` is read from the environment at call time. **Lose that key and every stored token becomes unrecoverable.**

### Flow A — connecting a social account

```
Frontend: "Connect Account"
  → POST /api/marketing/social-accounts/connect/   {workspace_id, platform}
  → backend picks adapter, returns authorization_url
  → browser redirects to the platform's OAuth page
  → platform redirects back to X_OAUTH_REDIRECT_URI with ?code&state
  → frontend route /oauth/callback
  → POST /api/marketing/social-accounts/oauth_callback/  {platform, code, state}
      exchange_code_for_token(code, state)
      get_account_info(access_token)
      encrypt_token() on access + refresh
      SocialConnection.objects.update_or_create(...)   ← keyed on (workspace, platform, external_account_id)
      SocialAccountAuditLog: ACCOUNT_CONNECTION | ACCOUNT_RECONNECTION
  → returns the serialized connection
```

`update_or_create` on the unique triple is what makes reconnecting idempotent — it updates the existing row rather than creating a duplicate.

### Flow B — generating content

```
Frontend campaign form
  → POST /api/marketing/gemini/generate/
     {campaignName, product, audience, location, occasion, offer, brandTone, referenceImageBase64}
  → GeminiGeneratorService.generate_marketing_content()
  → returns {postTitle, postDescription, postHashtags, posterImageUrl, metadata}
```

Side endpoints: `gemini/analyze-image/` and `gemini/generate-captions/`.

Note: `generate/` currently returns the payload **without persisting** a `GeminiGenerationRequest`/`Result` row. The tables exist; the write path does not use them yet.

### Flow C — uploading an asset

```
POST /api/marketing/assets/upload/   (multipart: workspace_id, file, source)
  → size check (50 MB cap)
  → mime sniff → asset_type
  → SupabaseStorageService.upload_file() → public URL
  → MarketingAsset row created
```

If Supabase isn't configured, or the upload fails, storage **falls back to a fake `https://mock-storage.url/...` URL and still creates the asset row**. The asset then looks valid but points nowhere — and publishing will fail later with a confusing error.

### Flow D — publishing (the core path)

```
POST /api/marketing/publishing/jobs/   {workspace_id, asset_id, social_connection_ids[], publish_mode, scheduled_at, timezone}

  transaction.atomic:
    create PublishingJob   (status QUEUED if NOW, else SCHEDULED)
    for each connection:
        skip if not publishing_enabled
        create PublishingJobItem (QUEUED)

  if publish_mode == NOW:
      execute_publishing_job(job.id)        ← synchronous, inside the HTTP request
          job → PUBLISHING, started_at = now
          for each item:
              item → PUBLISHING
              if platform == 'X':
                  decrypt_token(access_token_encrypted)
                  adapter.upload_media(token, asset.file_url)   → media_id
                  adapter.publish_post(token, text, media_id)   → {id, url}
                  item → PUBLISHED (+ external_post_id/url, published_at)
                  AuditLog: Success
              else:
                  item → FAILED "Platform not supported yet"
          job → PUBLISHED | PARTIALLY_PUBLISHED | FAILED
```

Per-item isolation is the important property: one channel failing does not stop the others, and retry targets only the failed items.

Retry endpoints: `POST publishing/jobs/{id}/retry/` (all failed items) and `POST publishing/jobs/items/{item_id}/retry/` (one item — though it currently re-runs the whole job).

### Flow E — analytics and settings (read paths)

- `GET /api/marketing/analytics/dashboard/` and `/kpis/` — read the three aggregate tables.
- `GET|PUT /api/marketing/settings/` — reads `MarketingWorkspace.objects.first()` plus the 50 most recent `AuditLog` rows.

### Response envelope

Every endpoint returns the same shape via `apps/common/responses.py`:

```json
{ "success": true, "data": {...}, "message": "...", "error": {...} }
```

`data`, `message` and `error` are omitted when null.

---

## 3) References

```
MarketingWorkspace ──┬── SocialConnection ──┬── SocialAccountSettings   (1:1, CASCADE)
                     │                      └── SocialAccountAuditLog   (SET_NULL)
                     │
                     ├── Brand ──────────────── ContentItem ────── Feedback / FeedbackElement
                     ├── Subscription ───────── Plan (FK)
                     ├── WorkspaceAIProvider ── AIProvider (FK)
                     ├── MarketingAsset ─────── PublishingJob ── PublishingJobItem
                     │        ▲                                          │
                     │        │                                          │
                     │        └── GeminiGenerationResult                 │
                     │                └── GeminiGenerationRequest (1:1)  │
                     │                                                   │
                     ├── DailyMetric / PlatformPerformance / CampaignROI │
                     └── AuditLog                        SocialConnection┘
```

### Delete behaviour

| Relationship | On delete | Why it matters |
|---|---|---|
| Everything → `MarketingWorkspace` | CASCADE | Deleting a workspace wipes the tenant |
| `PublishingJob` → `MarketingAsset` | CASCADE | **Deleting an asset destroys its publishing history** |
| `PublishingJobItem` → `SocialConnection` | CASCADE | Deleting a connection destroys its post records |
| `*.created_by` / `connected_by` → `User` | SET_NULL | Audit history survives user deletion |
| `SocialAccountAuditLog.social_connection` | SET_NULL | Audit survives disconnection |

The two CASCADEs above are worth revisiting — history disappearing when an asset is deleted is usually not what you want.

### Hard references (enforced FKs)

`SocialConnection.workspace`, `SocialAccountSettings.social_connection`, `MarketingAsset.workspace`, `PublishingJob.workspace|asset`, `PublishingJobItem.publishing_job|social_connection`, `GeminiGenerationRequest.workspace`, `GeminiGenerationResult.generation_request|asset`, all analytics tables → workspace, `AuditLog.workspace`.

### Soft references (not enforced — the extension seams)

| Field | Points at | Note |
|---|---|---|
| `MarketingWorkspace.customer_id` | Customer in the main Scaleezy system | **The main cross-module seam** |
| `MarketingAsset.generation_id` | `GeminiGenerationResult` | Redundant — the result already FKs back to the asset |
| `AuditLog.user` / `.platform` / `.account` | Users / platforms / accounts | Denormalized strings |
| `PlatformPerformance.platform` | Platform | Free-text, not the `Platform` enum |
| `CampaignROI.campaign_name` | A campaign | No campaign table exists |

### Uniqueness

- `social_connections` — `(workspace, platform, external_account_id)`
- `publishing_job_items` — `(publishing_job, social_connection)`
- `analytics_daily_metrics` — `(workspace, date)`
- `analytics_platform_performance` — `(workspace, platform)`
- `analytics_campaign_roi` — `(workspace, campaign_name)`

---

## 4) Connecting other modules (CRM, Inventory, Finance, Try-On)

### The rule: don't FK across module boundaries

`MarketingWorkspace.customer_id` already sets the pattern — a string reference to an entity another system owns, with no FK. Follow it. A cross-database FK can't be enforced anyway, and it couples your migrations to another team's schema.

Marketing consumes these modules **read-only**. Nothing here should write to CRM or Inventory.

### Three integration options

**Option A — call at read time.** Marketing calls the CRM API when it needs a segment.
- Good: never stale, nothing to store.
- Bad: their downtime becomes your downtime; slow endpoints; no historical record.
- Use for: low-volume, must-be-fresh lookups.

**Option B — snapshot what you used (recommended).** Copy the fields you actually consumed onto your own row at the moment you consume them.

```python
class Campaign(models.Model):
    workspace = models.ForeignKey(MarketingWorkspace, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)

    # soft references out to other modules
    crm_segment_id = models.CharField(max_length=255, blank=True, null=True)
    inventory_product_ids = models.JSONField(default=list, blank=True)

    # snapshot — what the segment looked like when we targeted it
    crm_segment_snapshot = models.JSONField(default=dict, blank=True)
    snapshot_taken_at = models.DateTimeField(null=True, blank=True)
```

- Good: reporting stays truthful ("we targeted 4,200 customers" stays 4,200 even after CRM changes); survives their outage.
- Bad: deliberately stale — that's the point.
- Use for: anything that feeds analytics or audit.

**Option C — sync table.** A local mirror refreshed on a schedule. Only worth it if you need to filter or join across a lot of their data. Heaviest to operate; skip until Option B stops being enough.

### Where each module plugs in

| Module | Feeds | Mechanism |
|---|---|---|
| **CRM** | Audience targeting, segments, purchase history | `crm_segment_id` + snapshot on a campaign row |
| **Inventory** | Which products to promote, stock-aware campaigns | `inventory_product_ids` JSON on campaign/asset |
| **Finance** | `CampaignROI.roi_multiplier`, budget | Finance pushes to an analytics ingest endpoint, or a scheduled pull |
| **Try-On** | Engagement signals | Event feed into `DailyMetric.engagement` |
| **Analytics** | Everything above | Write into the three aggregate tables |

### The missing table

`analytics_campaign_roi.campaign_name` is free text and there is no campaign table, yet the UI is built around campaigns. Before wiring CRM or Inventory in, add a `Campaign` model — it's the natural place for every cross-module reference to land, and it turns `campaign_name` into a real FK.

Suggested shape: `workspace` FK, `name`, `status`, date range, the soft references above, and FKs from `PublishingJob` and `CampaignROI` pointing at it.

### Ingest endpoint pattern

For push-based modules, one write endpoint per concern, authenticated with a service token (not `AllowAny`):

```
POST /api/marketing/analytics/ingest/     {workspace_id, date, reach, engagement, conversions, source_module}
```

Make it idempotent — upsert on the existing unique keys (`(workspace, date)`, `(workspace, platform)`) so a retried delivery corrects rather than duplicates.

### Rules to hold to

1. Reference other modules by **string ID**, never FK.
2. Marketing **reads**; it does not write to other modules.
3. **Snapshot** anything that feeds reporting.
4. Treat every external call as failure-prone — timeout, degrade, keep publishing working.
5. Never let another module's outage break the publish path.

---

## Known gaps

Current state, so the document isn't read as a description of finished work.

| Gap | Detail |
|---|---|
| **Settings not enforced** | `daily_post_limit`, allowed hours and `publishing_paused` are stored and shown but never checked. Only `publishing_enabled` is honored. |
| **Two audit systems** | `AuditLog` (strings) and `SocialAccountAuditLog` (FKs). Publishing writes the first, social accounts the second, settings reads only the first — so connect/disconnect never appears there. |
| **Storage fails silently** | Failed Supabase uploads still return a mock URL and create the asset row. |
| **`apps.users` is empty** | Uses the default Django `User`. Swapping to a custom user model after migrations is painful. |

---

## 5) React 18 StrictMode OAuth Callback Guards

Frontend OAuth callback routes (`oauth.callback.tsx`, `social.meta.callback.tsx`, `social.youtube.callback.tsx`) use a `useRef` guard to prevent double-firing API requests.

In React 18 StrictMode (development), `useEffect` hooks fire twice. If the OAuth callback code exchange endpoint is hit twice, the second request fails because the authorization code has already been consumed, raising `Invalid or expired OAuth state` or similar platform-level errors. The `useRef` boolean ensures the fetch is only dispatched exactly once during mount.
