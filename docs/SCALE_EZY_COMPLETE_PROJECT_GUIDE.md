# Scaleezy Marketing Hub — Complete System Architecture & Operational Guide

## Executive Summary & Mission
**Scaleezy Marketing Hub** is an enterprise-grade, multi-tenant AI marketing and automated omnichannel social publishing platform. It empowers marketing agencies, brand managers, and enterprises to:
1. Ingest, store, and calibrate a **Brand Brain** (brand identity, voice, fonts, palette, structured memories, and design inspirations).
2. Generate hyper-personalized, multi-format marketing campaigns and brand-compliant posters using an intelligent, provider-neutral **AI Router** (Gemini, OpenAI, Custom LLM endpoints).
3. Enforce **Human-in-the-Loop Content Review & Feedback Learning Loops** to continually refine AI generation precision.
4. Seamlessly connect to major social platforms (**Meta/Instagram/Facebook, LinkedIn, X/Twitter, YouTube, TikTok, Google Business**) via encrypted OAuth.
5. Publish and schedule multi-channel campaigns with durable fan-out, per-channel failure isolation, and atomic retries.
6. Aggregate multi-platform engagement analytics, ROI metrics, and audit trails under strict **tenant isolation** and **RBAC**.

---

## 1. High-Level System Architecture

```mermaid
graph TD
    subgraph Frontend ["Marketing_Frontend (React 19 + TanStack Start + Tailwind)"]
        UI_Auth["Auth & Workspace Selector"]
        UI_Onboarding["Brand Brain & Calibration Wizard"]
        UI_Studio["Content Studio & Poster Composer"]
        UI_Social["Social Connections & OAuth"]
        UI_Publishing["Publishing Calendar & Queue"]
        UI_Analytics["Analytics & ROI Dashboard"]
    end

    subgraph Gateway ["HTTP & API Gateway Layer"]
        API_Client["Centralized API Client (api.ts)"]
        JWT_Refresh["Single-Flight Token Rotation"]
    end

    subgraph Backend ["Marketing_backend (Django 6.1 + DRF 3.18)"]
        App_Users["apps.users (Auth, RBAC, Audit)"]
        App_Workspaces["apps.workspaces (Tenancy, Roles)"]
        App_Brands["apps.brands (Brand Brain, Health)"]
        App_Knowledge["apps.knowledge (Raw Sources, Facts)"]
        App_Inspirations["apps.inspirations (Preferences, Authority)"]
        App_AI["apps.ai (AIRouter, Metering, Adapters)"]
        App_Marketing["apps.marketing & apps.content (Campaigns, Content)"]
        App_Layouts["apps.layouts (Poster Composition)"]
        App_Feedback["apps.feedback & apps.learning (Feedback Loops)"]
        App_Social["apps.social_accounts (OAuth, Fernet Encrypted Tokens)"]
        App_Publishing["apps.publishing & apps.jobs (Fan-out Dispatcher)"]
        App_Analytics["apps.analytics (KPIs, Performance)"]
        App_Billing["apps.billing (Subscriptions, Limits)"]
    end

    subgraph External_Services ["External Infrastructure & Providers"]
        DB[(PostgreSQL / Supabase DB)]
        Storage[(Supabase Storage Bucket)]
        AI_Gemini["Google Gemini (google-genai)"]
        AI_OpenAI["OpenAI / Custom LLMs"]
        Social_APIs["Social Platforms (Meta, LinkedIn, X, YT, TikTok, Google)"]
    end

    Frontend --> Gateway
    Gateway --> Backend
    Backend --> DB
    Backend --> Storage
    App_AI --> AI_Gemini
    App_AI --> AI_OpenAI
    App_Publishing --> Social_APIs
```

---

## 2. Visual Workflow Diagrams for Core Pillars

### Flow 1: Tenant Signup, Workspace Creation & Brand Bootstrap

```mermaid
sequenceDiagram
    autonumber
    actor User as Marketer / Agency Admin
    participant UI as Frontend Client (/signup)
    participant AuthView as apps.users (SignupView)
    participant WorkspaceApp as apps.workspaces
    participant BrandApp as apps.brands
    participant AIApp as apps.ai.provisioning
    participant DB as PostgreSQL Database

    User->>UI: Enters Email, Password, Brand Name, Website
    UI->>AuthView: POST /api/auth/signup/
    Note over AuthView: Rate-Limited (5/hour per IP)
    
    rect rgb(240, 248, 255)
        Note over AuthView, DB: Atomic Transaction
        AuthView->>DB: 1. Create Django User
        AuthView->>WorkspaceApp: 2. Create MarketingWorkspace (Tenant Root)
        AuthView->>WorkspaceApp: 3. Create WorkspaceMember (Role: OWNER)
        AuthView->>BrandApp: 4. Create Brand (Status: PENDING)
        AuthView->>AIApp: 5. provision_default_ai(workspace)
        AIApp->>DB: Assign default AI Provider & Route
    end

    AuthView-->>UI: 201 Created {Access Token, Refresh Token, Workspace ID, Brand ID}
    UI->>UI: Stores Tokens & Sets Active Workspace ID
    UI-->>User: Redirects to Brand Brain Calibration Wizard
```

---

### Flow 2: Brand Brain Ingestion & Preference Authority Engine

```mermaid
flowchart TD
    subgraph Ingestion ["1. Knowledge & Inspiration Ingestion"]
        A1["Raw Documents (PDF, Guidelines, Text)"] -->|POST /sources/| B1["apps.knowledge (KnowledgeBrandSource)"]
        B1 --> C1["Extract Structured Facts (KnowledgeBrandMemory)"]
        
        A2["Design Inspirations (Images, Moodboards, Competitors)"] -->|POST /inspirations/| B2["apps.inspirations (BrandInspiration)"]
        B2 --> C2["Extract Preference Signals (InspirationSignal)"]
    end

    subgraph AuthorityEngine ["2. Preference Authority & Reconciliation Engine"]
        C2 --> D{"Signal Origin Check"}
        D -->|User Stated| E["Human Authority (Origin = USER, Weight = 1.0)"]
        D -->|AI Inferred| F["Model Inference (Origin = AI, Confidence = 0.8)"]
        
        E --> G{"Conflict Check (reconcile_attribute)"}
        F --> G
        
        G -->|Values Agree| H["Signal Confirmed & Retrievable"]
        G -->|Values Contradict| I["Human Authority Prevailed! AI Inference Rejected / Flagged"]
        G -->|User Updated Mind| J["Old Preference Superseded (Append-Only Audit)"]
    end

    subgraph ContextEngine ["3. Context Assembly for AI Generation"]
        C1 --> K["Brand Brain Context Pack"]
        H --> K
        J --> K
        K --> L["Context Gateway (System Prompts)"]
    end
```

---

### Flow 3: Provider-Neutral AI Content Generation & Poster Composition

```mermaid
sequenceDiagram
    autonumber
    actor User as Marketer
    participant Studio as Content Studio (Frontend)
    participant API as api.ts Client
    participant ContentApp as apps.content & apps.marketing
    participant AIRouter as apps.ai (AIRouter)
    participant LayoutEngine as apps.layouts (Poster Composer)
    participant Provider as AI Provider (Gemini / OpenAI)
    participant Storage as Supabase Storage Bucket

    User->>Studio: Submits Campaign Brief (Topic, Audience, Tone, Offer)
    Studio->>API: POST /api/marketing/gemini/generate/ (with Brief + X-Workspace-Id)
    API->>ContentApp: Validate Brief & Scope by Workspace
    ContentApp->>AIRouter: execute(capability='TEXT_GENERATION', brief, context)
    
    Note over AIRouter: Checks WorkspaceAIProvider & Route
    AIRouter->>Provider: Dispatches normalized prompt to configured LLM
    Provider-->>AIRouter: Returns Copywriting, Captions & Hashtags
    AIRouter->>ContentApp: Returns Generated Copy
    
    ContentApp->>LayoutEngine: compose_poster(copy, brand_palette, logo_url)
    LayoutEngine->>LayoutEngine: Renders brand-aligned canvas poster
    LayoutEngine->>Storage: Uploads image bytes to /workspace/{id}/{uuid}.png
    Storage-->>LayoutEngine: Returns Public Asset URL
    
    LayoutEngine->>ContentApp: Create MarketingAsset & ContentItem (Status: DRAFT)
    ContentApp-->>API: 200 OK {postTitle, postDescription, posterImageUrl, contentItemId}
    API-->>Studio: Renders interactive preview on Canvas
```

---

### Flow 4: Human-in-the-Loop Review Gate & Closed-Loop Reinforcement

```mermaid
flowchart TD
    A["Generated ContentItem (Status: PENDING_REVIEW)"] --> B{"Reviewer Action"}
    
    B -->|Approve| C["Mark Status = APPROVED"]
    C --> D["Move to Publishing Calendar / Queue"]
    
    B -->|Manual Edit| E["Update Copy / Swap Image"]
    E --> F["Log ContentRevision"]
    F --> G["Log FeedbackElement (MODIFIED)"]
    
    B -->|Reject| H["Mark Status = REJECTED"]
    H --> I["Select Structured Feedback Tags (e.g. Tone too informal, Palette mismatch)"]
    I --> J["Log FeedbackElement (REJECTED)"]
    
    G --> K["apps.learning (Preference Evidence Aggregator)"]
    J --> K
    K --> L["Generate LearnedPattern"]
    L --> M["Auto-tune Future Prompt Instructions in Brand Brain"]
```

---

### Flow 5: Social OAuth Handshake & Military-Grade Fernet Token Encryption

```mermaid
sequenceDiagram
    autonumber
    actor User as Brand Admin
    participant UI as Frontend (/social)
    participant Backend as apps.social_accounts
    participant SocialPlatform as Social Provider (Meta / LinkedIn / X / TikTok)
    participant DB as PostgreSQL Database

    User->>UI: Clicks "Connect Instagram"
    UI->>Backend: POST /api/marketing/social-accounts/connect/ {platform: 'INSTAGRAM'}
    Backend-->>UI: Returns Official OAuth URL with State & Scopes
    UI->>SocialPlatform: Redirects user to consent screen
    User->>SocialPlatform: Grants publishing permissions
    SocialPlatform-->>UI: Redirects to /oauth/callback?code=AUTH_CODE&state=STATE
    
    UI->>Backend: POST /api/marketing/social-accounts/oauth_callback/ {code, state, platform}
    Backend->>SocialPlatform: Exchange code for Access & Refresh Tokens
    SocialPlatform-->>Backend: Returns raw plaintext tokens
    
    rect rgb(255, 240, 245)
        Note over Backend: Security Boundary
        Backend->>Backend: Fernet.encrypt(access_token)
        Backend->>Backend: Fernet.encrypt(refresh_token)
        Backend->>DB: update_or_create(workspace, platform, external_id)<br/>Stores access_token_encrypted, refresh_token_encrypted
        Backend->>DB: Log SocialAccountAuditLog (ACCOUNT_CONNECTION)
    end
    
    Backend-->>UI: 200 OK (Sanitized Profile Info — No Tokens in JSON!)
    UI-->>User: Displays "Connected & Active" Badge
```

---

### Flow 6: Omnichannel Publishing Pipeline & Fault-Isolated Fan-Out

```mermaid
sequenceDiagram
    autonumber
    actor User as Marketer
    participant UI as Publishing Queue (Frontend)
    participant PubApp as apps.publishing
    participant Dispatcher as execute_publishing_job()
    participant MetaAdapter as Instagram / Facebook Adapter
    participant XAdapter as X (Twitter) Adapter
    participant LinkedInAdapter as LinkedIn Adapter
    participant DB as PostgreSQL Database

    User->>UI: Schedules / Clicks "Publish Now" across Instagram, X, and LinkedIn
    UI->>PubApp: POST /api/marketing/publishing/jobs/
    
    rect rgb(240, 248, 255)
        Note over PubApp, DB: Fan-Out Creation
        PubApp->>DB: Create PublishingJob (Status: QUEUED)
        PubApp->>DB: Create PublishingJobItem 1 (Instagram, QUEUED)
        PubApp->>DB: Create PublishingJobItem 2 (X/Twitter, QUEUED)
        PubApp->>DB: Create PublishingJobItem 3 (LinkedIn, QUEUED)
    end

    PubApp->>Dispatcher: execute_publishing_job(job.id)
    Note over Dispatcher: Decrypts Fernet Tokens In-Memory Only
    
    par Channel 1: Instagram
        Dispatcher->>MetaAdapter: publish(media_url, caption)
        MetaAdapter-->>Dispatcher: Success (post_id: 101)
        Dispatcher->>DB: Update Item 1 -> PUBLISHED
    and Channel 2: X (Twitter)
        Dispatcher->>XAdapter: publish(media_url, text)
        XAdapter-->>Dispatcher: Success (tweet_id: 202)
        Dispatcher->>DB: Update Item 2 -> PUBLISHED
    and Channel 3: LinkedIn
        Dispatcher->>LinkedInAdapter: publish(media_url, text)
        LinkedInAdapter-->>Dispatcher: Error (Token Expired)
        Dispatcher->>DB: Update Item 3 -> FAILED (error: "Token Expired")
    end

    Note over Dispatcher, DB: Fault Isolation
    Dispatcher->>DB: Update Master PublishingJob -> PARTIALLY_PUBLISHED
    Dispatcher-->>UI: Returns Job Summary
    
    Note over UI: UI shows Instagram: OK, X: OK, LinkedIn: FAILED with "Retry" button
    User->>UI: Clicks "Retry Failed Items"
    UI->>PubApp: POST /api/marketing/publishing/jobs/{id}/retry/
    Note over PubApp: Retries ONLY Item 3 (No duplicates on Instagram or X!)
```

---

### Flow 7: Multi-Platform Analytics Aggregation & ROI Engine

```mermaid
flowchart LR
    subgraph DataCollection ["1. Data Harvesting & Social Webhooks"]
        M1["Meta Insights API"] --> Collector["Analytics Aggregator Service"]
        X1["X Analytics API"] --> Collector
        L1["LinkedIn Metrics API"] --> Collector
        Y1["YouTube Analytics API"] --> Collector
    end

    subgraph AggregationTables ["2. High-Performance Aggregate Tables"]
        Collector -->|Daily Rollup| T1[("AnalyticsDailyMetrics\n(workspace, date)\n[reach, engagement, clicks, posts]")]
        Collector -->|Channel Breakdown| T2[("AnalyticsPlatformPerformance\n(workspace, platform)\n[impressions, shares, roi_multiplier]")]
        Collector -->|Campaign Attribution| T3[("AnalyticsCampaignROI\n(workspace, campaign_name)\n[revenue_attributed, roi_multiplier]")]
    end

    subgraph Delivery ["3. Frontend Analytics Hub"]
        T1 --> Dashboard["GET /api/marketing/analytics/dashboard/"]
        T2 --> Dashboard
        T3 --> Dashboard
        Dashboard --> UI_Charts["Executive KPI Cards, Time-Series Charts & Channel ROI Breakdowns"]
    end
```

---

## 3. Deep-Dive Backend Directory & App Breakdown

| Django App (`apps/`) | Business Purpose | Key Models | Key Endpoints / Services |
|---|---|---|---|
| **`users`** | Authentication, JWT management, signup rate throttling, audit logging. | `User`, `AuthAuditLog`, `SignupWebsiteClaim` | `/api/auth/signup/`, `/api/auth/login/`, `/api/auth/refresh/`, `/api/auth/me/` |
| **`workspaces`** | Multi-tenant isolation root, workspace memberships, client codes, roles (`OWNER`, `ADMIN`, `MEMBER`, `VIEWER`). | `MarketingWorkspace`, `WorkspaceMember` | `/api/marketing/workspaces/`, `/api/marketing/workspaces/switch/` |
| **`brands`** | Brand identity, colors, fonts, tone guidelines, brand health scoring. | `Brand`, `BrandBusinessProfile` | `/api/marketing/brands/`, `/api/marketing/brands/{id}/health/` |
| **`onboarding`** | Brand onboarding steps, setup wizard, brand calibration. | `OnboardingState`, `CalibrationRecord` | `/api/marketing/onboarding/` |
| **`knowledge`** | Ingestion of raw brand documents, guidelines, URLs, and extraction of structured brand memories. | `KnowledgeBrandSource`, `KnowledgeBrandMemory` | `/api/marketing/knowledge/sources/`, `/api/marketing/knowledge/memories/` |
| **`inspirations`** | Visual references, competitor moodboards, design signals, and preference authority engine. | `BrandInspiration`, `InspirationSignal` | `/api/marketing/inspirations/`, `/api/marketing/inspirations/signals/` |
| **`ai`** | Provider-neutral AI routing, custom LLM registration, capability mapping, usage and spend metering. | `AIProvider`, `WorkspaceAIProvider`, `WorkspaceAIRoute`, `AIUsageLog` | `AIRouter.execute()`, `/api/marketing/ai/providers/`, `/api/marketing/ai/routes/` |
| **`gemini`** | Gemini-specific orchestration, image analysis, caption generation, multimodal prompts. | `GeminiGenerationRequest`, `GeminiGenerationResult` | `/api/marketing/gemini/generate/`, `/api/marketing/gemini/analyze-image/` |
| **`marketing`** | Marketing assets metadata, image/video uploads, campaign configurations. | `MarketingAsset`, `Campaign` | `/api/marketing/assets/upload/`, `/api/marketing/campaigns/` |
| **`layouts`** | Programmatic canvas poster composition respecting brand kit tokens (colors, typography, logo placement). | *(Service layer & layout engines)* | `PosterCompositionService`, `/api/marketing/layouts/compose/` |
| **`content`** | Draft content items, revisions, multi-channel copy variations, review gate. | `ContentItem`, `ContentRevision` | `/api/marketing/content/`, `/api/marketing/content/{id}/review/` |
| **`feedback`** | Structured human-reviewer feedback on generated assets and copy. | `Feedback`, `FeedbackElement`, `FeedbackVocabulary` | `/api/marketing/feedback/` |
| **`learning`** | Learning loop models, preference evidence, learned generation patterns. | `LearnedPattern`, `PreferenceEvidence` | `/api/marketing/learning/patterns/` |
| **`social_accounts`** | Social media integrations, OAuth handshake, Fernet encryption, account settings, audit trails. | `SocialConnection`, `SocialAccountSettings`, `SocialAccountAuditLog` | `/api/marketing/social-accounts/connect/`, `/api/marketing/social-accounts/oauth_callback/` |
| **`publishing`** | Omnichannel publishing jobs, fan-out dispatcher, scheduling, retry engine. | `PublishingJob`, `PublishingJobItem` | `/api/marketing/publishing/jobs/`, `/api/marketing/publishing/jobs/{id}/retry/` |
| **`jobs`** | Durable background task execution infrastructure. | `TaskRun` | `/api/marketing/jobs/` |
| **`analytics`** | Aggregated daily KPIs, channel performance, ROI tracking. | `AnalyticsDailyMetrics`, `AnalyticsPlatformPerformance`, `AnalyticsCampaignROI` | `/api/marketing/analytics/dashboard/`, `/api/marketing/analytics/kpis/` |
| **`billing`** | SaaS subscription plans, capability quotas, soft & hard spend limits. | `Plan`, `Subscription`, `CapabilityLimit` | `/api/marketing/billing/subscription/` |
| **`audit`** | Comprehensive security and administrative audit logging. | `AuditLog` | `/api/marketing/audit/` |
| **`universal`** | Universal cross-tenant inspiration repository and platform-wide benchmark patterns. | `PlatformInspiration`, `UniversalPattern` | `/api/marketing/universal/inspirations/` |
| **`common`** | Shared utilities: standard response envelopes (`APIResponse`), `WorkspaceQuerySetMixin`, permission classes (`IsWorkspaceAdmin`, etc.). | *(No DB models)* | Standard envelope: `{success, data, message, error}` |

---

## 4. Frontend Architecture & UI Modules

The frontend is built with **React 19**, **TanStack Start/Router**, **Tailwind CSS**, and **Lucide Icons**:

### Key UI Modules
1. **Authentication & Session Manager (`/login`, `/signup`, `/oauth/callback`)**:
   - Intercepts requests via `api.ts`, automatically attaches `Bearer <token>` and `X-Workspace-Id`.
   - Single-flight transparent JWT token refreshing on 401 without user disruption.
2. **Dashboard Overview (`/`)**:
   - Real-time KPIs (Total Reach, Engagement Rate, Active Campaigns, Published Posts).
   - Quick Actions (Create Campaign, Connect Channel, Ingest Brand Assets).
3. **Brand Brain Studio (`/brand-brain`)**:
   - Brand Kit Editor (Logo, Hex colors, Font pairings).
   - Knowledge Base Uploader (Upload company docs, FAQs, voice guidelines).
   - Inspiration Moodboards (Visual card gallery with liked/disliked signal tags).
4. **Campaign & Content Generator (`/create`, `/content-studio`)**:
   - Step-by-step Campaign Wizard (Target audience, Tone, Product, Occasion, Offer).
   - Multimodal generation (Copywriting variants + dynamic brand-aligned poster generator).
   - Interactive Poster Canvas preview.
5. **Content Review & Approval Queue (`/review`)**:
   - Visual approval workflow with inline feedback buttons (Thumbs up/down, tone adjustments).
6. **Publishing Calendar & Channel Manager (`/publishing`, `/social`)**:
   - Multi-account connection cards with status indicators (Connected, Token Expired, Needs Re-auth).
   - Interactive scheduling calendar and publishing history queue with status pills (`PUBLISHED`, `FAILED`, `SCHEDULED`).
7. **Analytics Hub (`/analytics`)**:
   - Channel breakdown (Instagram vs LinkedIn vs X vs YouTube).
   - ROI and conversion attribution graphs.

---

## 5. Security, Tenancy & Correctness Guarantees

| Security Pillar | How Scaleezy Implements It |
|---|---|
| **Multi-Tenant Data Isolation** | Every DB query is scoped by `MarketingWorkspace`. Cross-workspace access attempts are rejected at the ORM mixin level and serializer level. |
| **Secret Encryption at Rest** | Social OAuth access/refresh tokens and custom AI provider API keys are encrypted using **Fernet (AES-128-CBC + HMAC-SHA256)**. Secrets are never exposed to the frontend. |
| **Idempotent Social Connections** | Connections are constrained by `UNIQUE(workspace, platform, external_account_id)`, ensuring re-authentications update existing records without creating orphaned rows. |
| **Per-Channel Fault Isolation** | Publishing jobs fan out into distinct `PublishingJobItem` rows. A failure on one social network does not abort or contaminate other target platforms. |
| **Append-Only Preference Authority** | Design and brand preferences in `apps.inspirations` utilize immutable signal histories and conflict-reconciliation algorithms to prevent contradicting AI behaviors. |
| **Zero Fake Completions** | System states accurately reflect real processing. Unimplemented or failing upstream tasks return explicit status codes (`501` or `FAILED`) rather than spoofing success. |

---

## 6. How to Run the Project Locally

### 1. Backend Setup
```powershell
cd Marketing_backend
# 1. Activate Python 3.12 Virtual Environment
.\.venv\Scripts\Activate.ps1

# 2. Run Database Migrations
python manage.py migrate

# 3. Start Backend Server (runs on http://127.0.0.1:8000)
python manage.py runserver
```

### 2. Frontend Setup
```powershell
cd Marketing_Frontend
# 1. Ensure .env has VITE_API_URL configured:
# VITE_API_URL=http://localhost:8000

# 2. Install dependencies (if not installed)
npm install

# 3. Start Frontend Dev Server (runs on http://localhost:5173 or 8080)
npm run dev
```

---

## 7. Key Talking Points for Team Lead / CTO Presentation

1. **Enterprise-Ready Architecture**: Clean separation of concerns across 18 specialized Django domain apps, TanStack frontend, and decoupled storage/AI layers.
2. **Provider-Agnostic AI Scalability**: Not locked into a single AI vendor. The `AIRouter` dynamically dispatches tasks between Google Gemini, OpenAI, and custom internal LLMs based on capability and cost.
3. **True Human-in-the-Loop AI**: Brand Brain memories and Inspiration preference authority continuously adapt from explicit reviewer feedback.
4. **Resilient Omnichannel Dispatch**: Multi-platform publishing with atomic retries, per-item status isolation, and encrypted OAuth token lifecycle management.
5. **Rigorous Multi-Tenancy**: Built from the ground up with workspace-isolated data access, role-based permissions, and complete audit logging.
