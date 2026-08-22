# Core Product Recovery Ledger

Mission authority: `SCALEEZY_MASTER_ARCHITECTURE.md` and the approved Core Recovery handoff supersede the former PR2-only execution mission for this recovery. PR0–PR6 ownership remains frozen. PR7 is out of scope.

Statuses are evidence-based: **PASS**, **FAIL**, **BLOCKED**, or **N/A**.

| Lifecycle step | Severity | Status | Live evidence | Frozen owner | Smallest compatible recovery | Required proof |
| --- | --- | --- | --- | --- | --- | --- |
| Select/switch client | P0 | PASS | Active-client selector persists context; API calls send `X-Workspace-Id`; local browser smoke created and switched between two clients without stale UI state. | PR0 | Completed compatibly. | Frontend build, isolation tests, and two-client browser smoke passed. |
| Add Client | P0 | PASS | Client creation atomically creates OWNER membership, default Brand and initial AI routing, then enters Brand Master onboarding. | PR0/PR5 | Completed compatibly. | Bootstrap success/readiness/rollback tests and live browser creation of two clients passed. |
| Tenant AI readiness | P0 | PASS | `provision_default_ai` is called inside the workspace bootstrap transaction and provisions capability routes from the installed platform catalogue. | PR5 | Completed compatibly. | New-client readiness and rollback tests passed. |
| AI administration and redundancy | P0 | PASS | AI controls live only under `/admin`; provider-neutral ordered route sets support failover/best-of/round-robin; backend permissions and a frontend route guard enforce OWNER/ADMIN access. | PR5 | Completed compatibly. | Admin/non-admin, ordered-route, atomic replacement and router strategy tests passed; Owner/Editor browser smoke passed. |
| Workspace request isolation | P0 | PASS | Frontend sends explicit workspace context and the server rejects missing, mismatched and foreign workspace/object combinations once selection is required. | PR0 | Completed compatibly. | Isolation suite and two-client browser switch passed. |
| Durable create/edit/library/return | P0 | PASS | Generation persists provider-neutral `ContentItem` records; publishing/review use the same durable item and enforce state transitions. | PR6/existing content | Completed compatibly. | Content, marketing, review and publishing integration tests passed in the 646-test suite. |
| Publishing selected-client isolation | P0 | PASS | Publishing jobs carry workspace and durable content identity; request/job/retry paths enforce membership, state and workspace consistency. | Existing publishing | Completed compatibly. | Publishing isolation, approval-gate, retry and idempotency tests passed. |
| Knowledge processing | P1 | FAIL | Architecture and UI state automatic processing/analysis is unavailable; processing action must be inspected for current 501/task behavior. | PR1/PR6 integration | Connect supported extraction through AIRouter/jobs with honest lifecycle and retry. | Success/failure/retry/provenance tests. |
| Inspiration analysis | P1 | FAIL | UI explicitly says automatic analysis unavailable; backend contract historically returned 501. | PR2/PR6 integration | Analyze through AIRouter while preserving advisory origin and provenance. | Status/origin/isolation/retry tests. |
| Rich business onboarding / Brand Master | P1 | PARTIAL | Brand Master is editable but `Brand` fields remain limited to basic identity/market context. | PR5/PR6 | Extend existing authoritative model/UI additively; recompile after edits. | Edit → compile → generation-context test. |
| Brand Brain correction | P1 | PARTIAL | Automatic rebuild hooks exist; user-facing correction propagation needs full verification. | PR4 | Complete correction paths through source-owned records, never edit derived brain directly. | Version/context change test. |
| Calibration and learning | P1 | NOT VERIFIED | PR6/learning modules and tests exist; full later-generation influence needs proof. | PR3/PR6 | Repair only broken continuity or client scoping. | Two-client influence/non-contamination test. |
| Settings boundary | P1 | PASS | Settings contains workspace, access, plan and security only; AI credentials/routing are absent and live in the guarded Admin module. | PR6 | Completed compatibly. | Settings/Admin browser boundary smoke passed. |
| Full core loop | P0 | PASS | Internal lifecycle, tenancy, RBAC, durable content/review/publishing and redundancy contracts pass together; local browser smoke covers login, client bootstrap/switch, Admin and Settings boundaries. Credentialed external AI generation and social delivery remain a deployment smoke check, not an implementation failure. | Cross-cutting | P0 implementation gate complete; keep PR7 closed. | 646-test backend suite, frontend production build and local browser smoke passed. |

## Recovery log

Update this section after each vertical slice with named tests and exact results. A code path without executed evidence remains NOT VERIFIED.

### 2026-08-22 — AI administration correction

- Root cause recorded: the recovery audit treated the first route row as the whole configuration even though the frozen PR5 contract is an ordered route set. The previous gap list named "provider overrides" but omitted two non-negotiable acceptance criteria: admin-only placement and multiple providers per capability.
- Corrected contract: product features request capabilities only; adapters contain vendor-specific integration; `AIRouter` owns selection, redundancy and strategy; workspace admins alone control enablement, credentials and route sets.
- Implemented: admin-only catalogue/provider/route APIs; ordered multi-provider route-set editor; atomic set replacement; provider-neutral foreground/background generation; provider-neutral image analysis, image captioning and video analysis; neutral `/api/marketing/ai-generation/` product endpoint with the old vendor path retained only as a compatibility alias.
- Evidence at that checkpoint: production frontend build **PASS**; Python compilation of every touched AI/backend module and migration **PASS**; active-path source scan for direct vendor-service calls and vendor-named product endpoints **PASS**. The temporary dependency-install block was later cleared; the complete executed result is recorded below.

### 2026-08-22 — P0 verification gate

- Backend: `manage.py check` **PASS**; `makemigrations --check --dry-run` **PASS**; migrations applied cleanly; complete Django suite **646 passed, 0 failed** in 586.873 seconds.
- Frontend: production build **PASS**; targeted substantive ESLint for every touched P0 frontend file **PASS**. The repository-wide lint command still reports the pre-existing CRLF/Prettier baseline and is not a P0 regression.
- Live browser: authentication **PASS**; two Add Client bootstraps **PASS**; selector switch between `P0 Alpha Client` and `P0 Beta Client` **PASS**; Admin provider/routing UI for Owner **PASS**; Settings contains no AI controls **PASS**; runtime console errors **0**.
- Access-control defect found and fixed during the gate: an Editor navigating directly to `/admin` could briefly render the empty Admin shell while its API calls were denied. The route now resolves the active-workspace role before rendering and redirects non-OWNER/non-ADMIN users to Overview. Editor denial and Owner access both re-verified in the browser; production build and targeted lint remain **PASS**.
- Provider neutrality/redundancy: capability-based route sets, ordered multi-provider membership, failover/best-of/round-robin, atomic replacement and provider-neutral product endpoints are covered by the passing AI tests. No product workflow selects a named vendor.
- Release position: **P0 CODE GATE PASS**. Before production promotion, run one credentialed staging smoke for a real AI call and one connected social publish; do not start PR7.
