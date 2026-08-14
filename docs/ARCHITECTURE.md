# Scaleezy Marketing Hub — Architecture

End-to-end reference: schema, data flow, references, and how to plug in other modules.

- **Backend** — `Marketing_backend/`, Django 6.1 + DRF 3.18, Postgres (Supabase)
- **Frontend** — `Marketing_Frontend/`, TanStack Start + React 19 + Tailwind v4
- **Storage** — Supabase Storage bucket `Marketing_Poster_images`
- **AI** — Google Gemini (`google-genai`)
- **Async** — none. Everything is synchronous DRF request/response.

---

## 1) Schema

12 tables across 8 Django apps. Every primary key is a UUID. Every business table hangs off `MarketingWorkspace`.

### Tenancy

**`marketing_workspaces`** — the tenant root.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `customer_id` | varchar(255) | **Soft reference** to the customer in the main Scaleezy system. Deliberately not an FK — that system owns its own DB. |
| `workspace_name` | varchar(255) | |
| `timezone` | varchar(50) | default `UTC` |
| `default_language` | varchar(10) | default `en` |
| `created_at` / `updated_at` | timestamp | |

### Social accounts

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

### Assets

**`marketing_assets`** — metadata only; bytes live in Supabase Storage.

`asset_type` (`POSTER`/`IMAGE`/`VIDEO`/`OTHER_SUPPORTED_ASSET`), `source` (`GEMINI_GENERATED`/`MANUAL_UPLOAD`), `file_name`, `file_url`, `storage_path`, `mime_type`, `file_size`, `width`, `height`, `duration`, `generation_id` (soft ref to a Gemini result), `created_by`.

### Publishing

**`publishing_jobs`** — one user action. `workspace`, `asset`, `created_by`, `status` (8 choices), `publish_mode` (`NOW`/`SCHEDULED`), `scheduled_at`, `timezone`, `created_at`, `started_at`, `completed_at`.

**`publishing_job_items`** — one row per target channel. This is the fan-out and the job↔connection join.

`publishing_job` (FK), `social_connection` (FK), `status` (`QUEUED`/`PUBLISHING`/`PUBLISHED`/`FAILED`/`RETRYING`/`CANCELLED`), `external_post_id`, `external_post_url`, `error_code`, `error_message`, `retry_count`, `queued_at`, `published_at`, `failed_at`.

Constraint: `UNIQUE (publishing_job, social_connection)` — a job cannot double-post to the same account.

### AI generation

**`gemini_generation_requests`** — the campaign brief. `workspace`, `user`, `prompt_data`, plus the structured fields the form collects: `campaign_name`, `product`, `target_audience`, `location`, `occasion`, `offer`, `brand_tone`, `content_format`, `visual_direction`. Then `status` (`PENDING`/`GENERATING`/`COMPLETED`/`FAILED`), `provider` (fixed `GOOGLE_GEMINI`), `model`, `error_message`.

**`gemini_generation_results`** — OneToOne with the request. `asset` (FK, nullable), `generated_text`, `generated_asset_url`, `metadata` (JSON).

### Analytics — pre-aggregated

| Table | Grain | Columns |
|---|---|---|
| `analytics_daily_metrics` | `(workspace, date)` | reach, engagement, posts_published, conversions |
| `analytics_platform_performance` | `(workspace, platform)` | reach, engagement, clicks, conversions, roi_multiplier |
| `analytics_campaign_roi` | `(workspace, campaign_name)` | roi_multiplier |

These are **stored aggregates**, not derived at query time from publishing data.

### Audit (second system)

**`audit_logs`** — denormalized. `workspace` (FK) but `user`, `platform`, `account` are plain strings. `date`, `action`, `previous_state`, `next_state`, `result`, `error`.

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
| **Scheduled jobs never run** | `publish_mode=SCHEDULED` creates the job and stops. Nothing picks it up. Needs a cron/management command. |
| **Only X publishes** | `services.py` branches on `if platform == 'X'`. Facebook/Instagram/LinkedIn adapters exist and work for OAuth, but publishing fails with "Platform not supported yet". |
| **Settings not enforced** | `daily_post_limit`, allowed hours and `publishing_paused` are stored and shown but never checked. Only `publishing_enabled` is honored. |
| **Two audit systems** | `AuditLog` (strings) and `SocialAccountAuditLog` (FKs). Publishing writes the first, social accounts the second, settings reads only the first — so connect/disconnect never appears there. |
| **Gemini results not persisted** | `generate/` returns content without writing `GeminiGenerationRequest`/`Result`. |
| **Storage fails silently** | Failed Supabase uploads still return a mock URL and create the asset row. |
| **No auth** | Every viewset is `AllowAny`; `CORS_ALLOW_ALL_ORIGINS = True`. |
| **Sync publishing blocks the request** | N remote API calls inside one HTTP request. Will hit gateway timeouts. |
| **Split API base URL in frontend** | `analytics`, `index` and `settings` hardcode `http://localhost:8000`; everything else uses `VITE_API_URL`. Breaks on deploy. |
| **`apps.users` is empty** | Uses the default Django `User`. Swapping to a custom user model after migrations is painful. |
