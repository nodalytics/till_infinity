# Conditioning by default

**Status:** design, 2026-09-11. Not yet approved.

## The problem: four times, and a human rule has not fixed it

Simpson's paradox has reversed a pooled figure on this project **four times**:

| | pooled said | conditioned said |
| --- | --- | --- |
| `aligning.md` | trading against a live higher timeframe costs nothing | costs 2.5-4.1 points at 3m and 5m, nothing at 1m, and **reverses** at 15m |
| `forecasting.md` | three clean tables | all three were defects |
| `trapping.md` | trap-from-break predicts at AUC 0.6187 | 0.567 within a timeframe; the rest was the timeframe |
| `instruments.md` (2026-09-11) | Boom 1000 is the worst instrument at -0.595R | **36 of its 48 closes are one strategy**, and `sweep-aware` runs +1.134R on the same instrument |

The last one is the clearest. The reported instrument mean and the strategy's
mean were **the same number, -0.595R**, because that strategy *was* the sample.
An entire investigation - three measurements, two of them replays - ran on a
composition rather than an instrument.

Each time, the lesson was written down. Each time, the next cut was pooled
again. **The rule is correct and does not survive contact with a new question**,
which is the signature of a rule that needs to be mechanical rather than
remembered.

## What this builds

A reporting helper that makes the conditioned view the default one, and makes a
reversal impossible to miss.

Any comparison of a metric across buckets reports:

1. the pooled table, as now;
2. the same cut **within** each stratum - by default `strategy` and `interval`,
   the two that have caused every reversal here;
3. a **warning line** when the pooled ordering disagrees with the within-stratum
   ordering, naming the strata that disagree.

The third is the point. The first two are available today by writing more code,
and the reason they are not written is that nobody writing a cut believes their
particular cut is the one that will reverse.

## Design

`till_infinity/shared/strata.py`, in the package for the reason the replay
kernel is: `research/` has no lint or test gate.

```python
def compare(
    rows: Sequence[Mapping[str, Any]],
    *,
    value: str,
    bucket: Callable[[Mapping], str] | str,
    within: Sequence[str] = ("strategy", "interval"),
    min_n: int = 100,
) -> Comparison
```

`Comparison` renders to text and carries the pooled table, the per-stratum
tables, and `reversals` - the strata whose best and worst buckets differ from
the pooled ones.

### The warning is the product

    pooled          best=low   worst=high   gap 0.412R
      strategy=thesis-only  best=low  worst=high   gap 0.598R   n=36
      strategy=sweep-aware  best=high worst=low    gap 0.204R   n=4   ** REVERSED **

    ** the pooled ordering does not hold in 1 of 4 strata. The pooled figure is
       a composition of populations that disagree; read the strata.

Stated in the same voice as the rest of this project's output: what happened,
and what it means for the reader.

### Where `min_n` bites, and why it is not a filter

A stratum below `min_n` is reported with its count and **excluded from the
reversal check**, not hidden. `sweep-aware` at n=4 on Boom is exactly such a
stratum, and it is the one that carried the finding. Hiding it would have
reproduced the original error with an extra step; silently counting it as a
reversal would make every noisy cell shout.

## Scope

**In:** the helper, the reversal check, text rendering, and migration of the
three harnesses that already cut by buckets (`sweepregimes`, `sweepstops`,
`spikeside`).

**Out:**

* The other 100 harnesses. Most do not compare across buckets.
* Any statistical test of whether a reversal is significant. The check is
  ordinal - does the ranking hold - because that is the failure that has
  actually occurred four times, and a significance test on top would invite
  arguing with the warning rather than reading the strata.
* Choosing strata automatically. `strategy` and `interval` are the default
  because they caused all four; a caller who knows a third names it.

## Testing

1. A dataset built so the pooled ordering reverses within every stratum produces
   a reversal warning naming all of them.
2. A dataset where the ordering holds everywhere produces none.
3. A stratum below `min_n` is reported and excluded from the reversal check.
4. An absent stratum key does not crash - rows missing `strategy` group under a
   named "unknown" stratum rather than vanishing, because a row silently
   dropped from a comparison is the failure this exists to prevent.
5. **The Boom case, as a fixture.** The real shape - one stratum holding 75% of
   the rows and carrying the entire pooled effect - reproduced from the measured
   numbers, asserting the warning fires.

## What it does not fix

A reversal warning tells you the pooled figure is a composition. It does not
tell you which stratum is the right one to act on, and it cannot see confounders
nobody named - the Boom investigation also needed the *idea* that strategy might
matter. What it removes is the case where nobody looked.
