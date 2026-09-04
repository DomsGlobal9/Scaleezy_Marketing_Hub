# PR30 integration — immutable release preflight

The user-authorized release PR31 was ready locally at a3ec2968 when main advanced from c25bb8cd to 6990bdee (Claude's quality-engine PR30). GitHub reported a conflict. Preserve all already-merged quality-engine work and our approved tab closure; do not rewrite published history or change architecture/product semantics while resolving the release conflict.

Root AGENTS.md, CTO_REVIEW_LOG.md, release preflight/self-review and upstream changed-file inventory were reread. Existing PR task/data-contract root files remain absent. Actual conflict: platform client detail UI. Preserve our loading/list/control behavior and upstream quality controls. Auto-merged Review, generation tasks and Platform control routes/services require compatibility checks.

Dependency scope: PlatformAdmin → client detail → existing quality-settings action; generation → saved content/quality critique → layout focus/history → review display; internal AI usage/billing flags and new upstream migrations. No new capabilities or policy changes beyond preserving main are authorized. Confirm user template choice is not overwritten by merge resolution.

Requirement/test map: frontend conflict needs type/lint/logic/build checks; generation/task/control compatibility needs existing focused tests and refreshed full backend regression; migration graph needs drift check and fresh isolated migrate/integrity. Upstream new migrations must coexist with the Brand merge migration. Use isolated test configuration, no production data/provider calls.

STOP for incompatible business intent or mandatory failing gate; report a real blocker instead of forcing a merge. Normal merge and all three deployment checks remain required after fresh evidence.
