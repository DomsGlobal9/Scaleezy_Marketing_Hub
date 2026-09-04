# Social Accounts — contained closure checkpoint

Reviewed 2026-09-04 against the current branch and the live selected-client account page. This is a local implementation checkpoint, not a deployment claim.

## Keep / fix / remove

| Surface | Decision | Implemented |
| --- | --- | --- |
| Account overview | KEEP + FIX | Unknown or failed loads no longer become zero accounts; malformed payloads fail visibly; previous rows survive refresh failure; retry and live loading states added. |
| Connect Account | KEEP + FIX | Header focuses the platform chooser instead of silently selecting Facebook. Platforms stay available after an account is connected, permitting Add Another. |
| Manage / verify / reconnect / disconnect | KEEP + FIX | ADMIN/OWNER UI gates fail closed. Backend mutations require the existing ADMIN role. Provider-owned identity and health fields are read-only. |
| Default account switch | REMOVE UI ONLY | No active consumer enforces its meaning. Existing persisted field remains for compatibility. |
| Publishing toggle | KEEP + CLARIFY | Enable/Disable names match the actual publishing-enabled flag, rather than implying the separate scheduling policy pause. Worker enforcement remains a priority finding below. |
| LinkedIn callback | FIX | One-shot exchange guard, matching the other OAuth callbacks. UI now accurately describes the supported personal-profile destination. |
| Account activity | KEEP + FIX | Retryable failure, labelled filters, and accessible loading state. Complete mutation-audit coverage remains separate work. |
| Provider-field promises | REMOVE COPY | Removed unverified claims that every displayed field is retrieved automatically. |

## Backend integrity

- Generic SocialConnection POST/PUT/DELETE are unavailable. OAuth owns creation; disconnect preserves history. Tests prove a refused DELETE leaves publishing records intact.
- Only `publishing_enabled` and the retained compatibility field `is_default_account` are writable through the client serializer.
- MarketingAsset generic POST/PUT/PATCH are unavailable. Authenticated binary upload, scoped reads/deletion, and internal generation/layout writes remain intact.
- Tests exercise JSON and multipart arbitrary URLs, loopback/private/link-local targets, storage metadata forgery, tenant mismatch, storage failure and internal generated assets.
- Removed X's unused media download. Existing text/link fallback remains; this change does not claim to implement X image attachment.
- Publishing's old URL-only asset creation fallback is removed. Normal generated assets have IDs and uploaded images use binary upload. Missing saved media now gives a clear recovery error instead of trusting an arbitrary URL.

## Evidence

- Production references: `14-social-accounts-desktop.jpg` (initial loading), `15-social-accounts-loaded.jpg`, `16-social-accounts-connect-dialog.jpg`, `17-social-accounts-mobile.jpg`.
- No live account was connected, verified, disconnected or modified during this audit.
- Focused social role/history suite: PASS, 8 tests.
- Social accounts plus tenant isolation: PASS, 96 tests.
- Asset boundary plus X tests: PASS, 17 tests.
- Full backend regression after these backend changes: PASS, 1,264 tests in 63.622 seconds, zero failures; Django system checks zero issues.
- Frontend TypeScript: PASS. Targeted Social Accounts lint: PASS. Production client/SSR/Nitro build: PASS.
- Diff whitespace check: PASS.
- Full source lint: FAIL — 18,979 formatting errors and 14 warnings, including CRLF/Prettier failures across untouched files. Broad formatting was not mixed into this slice.
- Post-change authenticated browser verification: NOT VERIFIED; saved screenshots show the deployed reference, not the new branch.

## Not closed by this checkpoint

1. A queued publishing worker does not re-check `publishing_enabled` before provider dispatch. This was reproduced with a mocked provider and is the next publishing safety fix; changing the toggle label does not resolve it.
2. OAuth callback state authority, verification error classification, reconnect health reset, and mutation audit completeness need separate focused backend work.
3. Runtime OAuth availability, true LinkedIn organization destination selection, and the existing separate publishing-policy settings are not fabricated as completed features.

Release disposition: NOT READY for an all-tabs-complete or live-verified claim. Keep the checkpoint separate from the remaining publishing and release gates.
