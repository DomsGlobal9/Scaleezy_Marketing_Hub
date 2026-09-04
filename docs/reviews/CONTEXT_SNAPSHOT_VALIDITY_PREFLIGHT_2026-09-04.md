# Context snapshot validity — immutable preflight addendum

Date: 2026-09-04. Parent authorization: close the newly confirmed stale/failed compilation and time-window boundary under `TAB_CLOSURE_ALL_GAPS_PREFLIGHT_2026-09-04.md`.

## Scope and decision

PROCEED within the existing Brand Brain compiler and Context Gateway owners. No persisted Brain/API shape change, migrations, schedulers, provider calls, deployment, or read-endpoint database writes. Preserve the compiler's current `valid_from <= now < valid_until` eligibility filters, precedence and source lineage. Initial preflight remains unchanged.

## Confirmed boundary

The Context Gateway reuses a matching saved schema/version without checking whether confirmed memory eligibility has changed or a rebuild failed. The warm context cache is keyed by that old brain version; its TTL cannot repair the saved snapshot. Expired facts and facts withdrawn after a failed source-revoke/confirmed-edit rebuild can therefore reach a new generation.

## Dependency and entry paths

Authenticated workspace/brand -> context resolution (synchronous generation, queued generation, context preview) -> saved snapshot health and current scoped memory-ID eligibility -> existing pure compiler if stale -> universal precedence and context cache -> provider-neutral context -> generation attribution. Existing mutation paths and historical records are preserved.

## Implementation approach

- Add a compiler-owned freshness helper using the persisted failure flag and the current eligible memory IDs, scoped by both workspace and brand. It does not assemble raw claims or copy source text into context.
- Pure-recompile only when the saved snapshot is unsafe; fail closed with a safe ContextError if current resolution fails. Unchanged snapshots retain existing compilation/cache behavior.
- During generation, use that resolved snapshot on the in-memory Brand instance so existing universal precedence and attribution readers see the same version. Never save it from the read path.

## Requirement-to-test map

| Boundary | Required evidence |
| --- | --- |
| Time crosses after compilation and cache warming | Expiring fact disappears and future fact enters at the exact boundary; old cache/version is not reused |
| Source revoked / confirmed fact edited but rebuild fails | Existing domain actions succeed, old saved snapshot remains, new context excludes withdrawn evidence |
| Compilation still unavailable | ContextError; no old context returned even with warm cache |
| Tenant/brand isolation | Foreign workspace/brand context rejected; foreign temporal records do not trigger/enter the local compilation |
| Precedence and attribution | Universal standards and source IDs use the resolved snapshot, not the stale saved version |
| Latency and no mutation | Fixed-query freshness check, unchanged brain does not recompile, database snapshot is unchanged by reads |

## Risk/stop conditions

No changes to publishing, OAuth, provider credentials, Learning authority, frozen schemas or raw-source precedence. A requirement for any wider owner must be reported before edits. Focused tests and affected-app regressions precede handoff; root owns consolidated full gate.
