# PR7 finding — every learning event is a confidence weight, including ones nobody meant as evidence

**Found:** 2026-08-24, while adding learning-visibility reporting (not part of the Final Core Closure Sprint).
**Status:** not a defect in PR7 as written. It is a load-bearing assumption that nothing states, and the sprint is about to break it.
**Owner:** whoever implements Slices A–D.

## What the code does

`apps/universal/aggregation.py::_event_counts()` counts **every** `LearningEvent` belonging to a CLIENT workspace, with no filter on `event_type` or `outcome`:

```python
rows = (
    LearningEvent.objects.filter(workspace__kind=MarketingWorkspace.Kind.CLIENT)
    .values('workspace_id', 'brand_id', 'event_type', 'outcome')
    .annotate(total=Count('id'))
)
```

That total then becomes a confidence multiplier on the brand's contribution to cross-client learned patterns:

```python
event_count = event_totals.get((workspace_id, getattr(brand, 'pk', None)), 0)
evidence_weight = max(1.0, float(support or 0)) * (1.0 + min(event_count, 20) * 0.05)
```

So each learning event a brand accumulates adds **+5% weight** to that brand's influence on every universal pattern it feeds, up to **+100%** at 20 events.

## Why that is safe today, and stops being safe next week

It is safe *right now* only because of an accident of coverage: today there are exactly two writers of `LearningEvent` — review feedback (`apps/learning/adapters.py`) and calibration verdicts (`apps/onboarding/services.py`). Both are genuine human judgments, so "more events" really does mean "more human evidence", and weighting by volume is defensible.

The event-type enum already declares `PUBLISHED` and `PERFORMANCE_OBSERVED`, and the sprint adds work that will naturally start writing events that are **not** human judgments:

- A `PUBLISHED` event (the obvious first step toward a performance loop) would make a brand that publishes a lot outrank a brand with better-evidenced taste, purely on volume.
- Slice A/B produce candidate memories and AI signals whose confirm/reject actions are plausible future event writers.

At that point the multiplier silently changes meaning from *"how much has a human taught this brand"* to *"how busy is this brand"* — and nothing in the code or the tests would fail to tell you.

## Evidence

I built the `PUBLISHED` event and then pulled it back out precisely because of this. The patch is held at
`scratchpad/published-learning-event.patch` (not landed, deliberately). It writes one deduped, `NEUTRAL`-outcome event per content item that reaches the world. Even at `NEUTRAL`, it lands in `_event_counts()` and moves the weight, because the aggregation does not look at outcome.

## The decision to make (not mine)

One of:

1. **Filter the weight to judgment events.** `_event_counts()` counts only the event types that represent a human verdict (today: `APPROVED`, `EDITED`, `REJECTED`, `REDO`, `EXPLICIT_RULE`, `MEMORY_CONFIRMED`, `MEMORY_REJECTED`, …). New event types then default to *not* affecting universal learning, which is the safe direction — a new writer cannot silently reweight the platform.
2. **Weight by outcome, not volume.** Count only `POSITIVE`/`NEGATIVE` outcomes, so `NEUTRAL` bookkeeping events are inert by construction.
3. **Accept it deliberately** and write that down — "publishing volume is a legitimate proxy for engagement" is a defensible product position, but it should be a decision with a comment on it, not a side effect.

Option 1 is the smallest change and the one that fails safe.

## What this is not

This is not a request to reopen PR7. Its compile, lineage, publish/retire, rank-82 injection and privacy disclosure are untouched by any of the above — the only line in question is which rows `_event_counts()` counts. Whoever adds the next `LearningEvent` writer should read this first.
